//! The native record fetcher.
//!
//! Bridges `ceres-database` into asyncio. A fetcher holds a lazily-connecting pool over the
//! same database the Python layer resolved, and `fetch` returns an awaitable producing a
//! [`RecordBatch`](crate::entities::RecordBatch), so a record listing goes from the driver
//! to JSON without any Python entity objects in between.

use std::sync::mpsc::{Receiver, sync_channel};
use std::sync::{Arc, Mutex};

use ceres_database::{Parameter, RecordStore};
use ceres_entities::Records;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes as PyBytesType, PyFloat, PyInt, PyString};
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::entities::{EntityTable, RecordBatch, RecordTable};

/// Extract a compiled statement parameter, one of the primitives bind processors produce.
fn extract_parameter(value: &Bound<'_, PyAny>) -> PyResult<Parameter> {
    if value.is_none() {
        return Ok(Parameter::Null);
    }

    if value.is_instance_of::<PyBool>() {
        return Ok(Parameter::Bool(value.extract()?));
    }

    if value.is_instance_of::<PyInt>() {
        return Ok(Parameter::Integer(value.extract()?));
    }

    if value.is_instance_of::<PyFloat>() {
        return Ok(Parameter::Float(value.extract()?));
    }

    if value.is_instance_of::<PyString>() {
        return Ok(Parameter::Text(value.extract()?));
    }

    if value.is_instance_of::<PyBytesType>() {
        return Ok(Parameter::Bytes(value.extract()?));
    }

    // The PostgreSQL driver takes timestamps and UUIDs natively, so its bind processors
    // pass the objects through rather than rendering text.
    if let Ok(aware) = value.extract::<chrono::DateTime<chrono::Utc>>() {
        return Ok(Parameter::Timestamp(aware.naive_utc()));
    }

    if let Ok(naive) = value.extract::<chrono::NaiveDateTime>() {
        return Ok(Parameter::Timestamp(naive));
    }

    if let Ok(id) = value.extract::<uuid::Uuid>() {
        return Ok(Parameter::Uuid(id));
    }

    Err(PyTypeError::new_err(format!(
        "{} is not a statement parameter the native engine understands",
        value.get_type().name()?
    )))
}

/// A natively-connected view of a Ceres database, serving record reads.
///
/// Built from resolved connection parameters rather than a configuration, because the
/// Python layer resolves per-instance details like temporary SQLite paths. Connections
/// open lazily on first use.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordFetcher {
    pub(crate) store: Arc<RecordStore>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordFetcher {
    /// Open a fetcher over a SQLite database file.
    #[staticmethod]
    fn sqlite(path: &str) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let store = RecordStore::sqlite(path).map_err(to_value_error)?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Open a fetcher over a PostgreSQL database.
    ///
    /// `settings` are per-connection server settings like `search_path`, matching the ones
    /// the query layer passes its own driver.
    #[staticmethod]
    #[pyo3(signature = (host, database, user, port=None, password=None, settings=Vec::new()))]
    fn postgres(
        host: &str,
        database: &str,
        user: &str,
        port: Option<u16>,
        password: Option<&str>,
        settings: Vec<(String, String)>,
    ) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let store = RecordStore::postgres(host, port, database, user, password, settings)
            .map_err(to_value_error)?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Execute a compiled record query, as an awaitable `RecordBatch`.
    ///
    /// The statement text and parameters come from the query layer's own compiler, so any
    /// filter it can express runs natively with identical semantics.
    fn fetch_sql<'py>(
        &self,
        py: Python<'py>,
        table: RecordTable,
        sql: String,
        #[gen_stub(override_type(type_repr = "list[typing.Any]"))] parameters: Vec<
            Bound<'_, PyAny>,
        >,
    ) -> PyResult<Bound<'py, PyAny>> {
        let table = table.into();
        let parameters = parameters
            .iter()
            .map(extract_parameter)
            .collect::<PyResult<Vec<_>>>()?;
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let records = store
                .fetch_sql(table, &sql, parameters)
                .await
                .map_err(to_value_error)?;
            Ok(RecordBatch { records })
        })
    }

    /// Execute a compiled record query, as chunks the caller walks one at a time.
    ///
    /// The chunked twin of `fetch_sql`, for a dump that renders and writes as it reads.
    /// The query runs on its own thread and hands each decoded chunk over, so the reader
    /// sets the pace and neither side ever holds more than a chunk.
    fn stream_sql(
        &self,
        table: RecordTable,
        sql: String,
        #[gen_stub(override_type(type_repr = "list[typing.Any]"))] parameters: Vec<
            Bound<'_, PyAny>,
        >,
    ) -> PyResult<RecordChunks> {
        let table = table.into();
        let parameters = parameters
            .iter()
            .map(extract_parameter)
            .collect::<PyResult<Vec<_>>>()?;
        let store = self.store.clone();
        // One chunk of depth lets the query read ahead of the reader by exactly one,
        // which overlaps the two without letting either run away from the other.
        let (sender, receiver) = sync_channel(1);
        let runtime = pyo3_async_runtimes::tokio::get_runtime();
        let handle = runtime.handle().clone();
        runtime.spawn_blocking(move || {
            let outcome = handle.block_on(async {
                let mut sink = |records: Records| {
                    // A closed channel is the reader having gone away, which ends the
                    // query rather than reporting anything.
                    sender
                        .send(Ok(records))
                        .map_err(|_| ceres_database::Error::Decode("the reader stopped".into()))
                };
                store.stream_sql(table, &sql, parameters, &mut sink).await
            });

            if let Err(error) = outcome {
                // The reader raises whatever the query could not finish. A send that
                // fails here is the reader already gone, which needs no report.
                let _ = sender.send(Err(error));
            }
        });

        Ok(RecordChunks {
            chunks: Arc::new(Mutex::new(receiver)),
        })
    }

    /// Fetch a record listing ordered by timestamp, as an awaitable `RecordBatch`.
    #[pyo3(signature = (table, limit=None, offset=None))]
    fn fetch<'py>(
        &self,
        py: Python<'py>,
        table: RecordTable,
        limit: Option<u64>,
        offset: Option<u64>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let table = table.into();
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let records = store
                .fetch(table, limit, offset)
                .await
                .map_err(to_value_error)?;
            Ok(RecordBatch { records })
        })
    }

    /// Fetch the records matching filter query pairs, as an awaitable `RecordBatch`.
    ///
    /// The pairs parse against the native filter subset, and a request outside it
    /// answers `None` synchronously so the caller delegates to the query layer.
    #[gen_stub(override_return_type(type_repr = "typing.Any"))]
    fn fetch_pairs<'py>(
        &self,
        py: Python<'py>,
        table: RecordTable,
        pairs: Vec<(String, String)>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        let table = table.into();
        let Ok(filter) = ceres_database::RecordFilter::parse(table, &pairs) else {
            return Ok(None);
        };

        let store = self.store.clone();
        let awaitable = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let records = store.fetch_filter(&filter).await.map_err(to_value_error)?;
            Ok(RecordBatch { records })
        })?;
        Ok(Some(awaitable))
    }

    /// Count the records matching filter query pairs, as an awaitable count.
    ///
    /// Like `fetch_pairs`, a request outside the native subset answers `None`
    /// synchronously so the caller delegates.
    #[gen_stub(override_return_type(type_repr = "typing.Any"))]
    fn count_pairs<'py>(
        &self,
        py: Python<'py>,
        table: RecordTable,
        pairs: Vec<(String, String)>,
    ) -> PyResult<Option<Bound<'py, PyAny>>> {
        let table = table.into();
        let Ok(filter) = ceres_database::RecordFilter::parse(table, &pairs) else {
            return Ok(None);
        };

        let store = self.store.clone();
        let awaitable = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            store.count_filter(&filter).await.map_err(to_value_error)
        })?;
        Ok(Some(awaitable))
    }
}

/// The native filter subset's key classification for one record table.
///
/// Answers `(supported, delegated)`, and the classification test holds their union to
/// exactly the fields the Python filter models declare.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn record_filter_keys(table: RecordTable) -> (Vec<&'static str>, Vec<&'static str>) {
    let table = table.into();
    (
        ceres_database::RecordFilter::supported_keys(table),
        ceres_database::RecordFilter::delegated_keys(table),
    )
}

/// The native filter subset's key classification for one non-record entity table.
///
/// Answers `(supported, delegated)` like the record classification, and the same test
/// holds their union to exactly the fields the Python filter models declare.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn entity_filter_keys(table: EntityTable) -> (Vec<&'static str>, Vec<&'static str>) {
    let table = table.into();
    (
        ceres_database::EntityFilter::supported_keys(table),
        ceres_database::EntityFilter::delegated_keys(table),
    )
}

/// A streamed record query's chunks, taken one await at a time.
///
/// Dropping this ends the query, because the next chunk it tries to hand over has
/// nowhere to go.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordChunks {
    chunks: Arc<Mutex<Receiver<Result<Records, ceres_database::Error>>>>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordChunks {
    /// The next chunk, as an awaitable `RecordBatch`, `None` once the query is spent.
    ///
    /// Waiting for a chunk blocks a thread of its own rather than the event loop, so a
    /// slow query leaves the caller's asyncio loop free.
    fn next<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let chunks = self.chunks.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let received = pyo3_async_runtimes::tokio::get_runtime()
                .spawn_blocking(move || {
                    let receiver = chunks.lock().expect("the chunks outlive every reader");
                    receiver.recv()
                })
                .await
                .map_err(|error| PyValueError::new_err(error.to_string()))?;

            match received {
                // A disconnected channel is the query having run to its end.
                Err(_) => Ok(None),
                Ok(Ok(records)) => Ok(Some(RecordBatch { records })),
                Ok(Err(error)) => Err(to_value_error(error)),
            }
        })
    }
}

fn to_value_error(error: ceres_database::Error) -> PyErr {
    PyValueError::new_err(error.to_string())
}

/// A natively-connected writer for record entities.
///
/// Entities extract into native records synchronously, then a whole flush upserts in one
/// transaction on the writer's own pool. Built from resolved connection parameters like
/// the fetcher, and matching the query layer's connection semantics.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordWriter {
    writer: Arc<ceres_database::RecordWriter>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordWriter {
    /// Open a writer over a SQLite database file.
    #[staticmethod]
    fn sqlite(path: &str) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let writer = ceres_database::RecordWriter::sqlite(path).map_err(to_value_error)?;
        Ok(Self {
            writer: Arc::new(writer),
        })
    }

    /// Open a writer over a PostgreSQL database, with per-connection server settings.
    #[staticmethod]
    #[pyo3(signature = (host, database, user, port=None, password=None, settings=Vec::new()))]
    fn postgres(
        host: &str,
        database: &str,
        user: &str,
        port: Option<u16>,
        password: Option<&str>,
        settings: Vec<(String, String)>,
    ) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let writer =
            ceres_database::RecordWriter::postgres(host, port, database, user, password, settings)
                .map_err(to_value_error)?;
        Ok(Self {
            writer: Arc::new(writer),
        })
    }

    /// Upsert groups of record entities atomically, as an awaitable.
    ///
    /// Each group pairs a record table name with the entities to write there. Raises
    /// `ValueError` when an entity cannot extract natively, before anything writes.
    fn write<'py>(
        &self,
        py: Python<'py>,
        #[gen_stub(override_type(type_repr = "list[tuple[RecordTable, list[typing.Any]]]"))]
        groups: Vec<(RecordTable, Vec<Bound<'_, PyAny>>)>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let batches = groups
            .iter()
            .map(|(table, entities)| crate::entities::records_from_entities(*table, entities))
            .collect::<PyResult<Vec<_>>>()?;
        let writer = self.writer.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            writer.upsert(batches).await.map_err(to_value_error)
        })
    }
}
