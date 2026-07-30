//! The native record fetcher.
//!
//! Bridges `ceres-database` into asyncio. A fetcher holds a lazily-connecting pool over the
//! same database the Python layer resolved, and `fetch` returns an awaitable producing a
//! [`RecordBatch`](crate::entities::RecordBatch), so a record listing goes from the driver
//! to JSON without any Python entity objects in between.

use std::sync::Arc;

use ceres_database::{Parameter, RecordStore};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes as PyBytesType, PyFloat, PyInt, PyString};
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::entities::{RecordBatch, RecordTable};

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
        let Some(filter) = ceres_database::RecordFilter::parse(table, &pairs) else {
            return Ok(None);
        };

        let store = self.store.clone();
        let awaitable = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let records = store
                .fetch_filter(table, &filter)
                .await
                .map_err(to_value_error)?;
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
        let Some(filter) = ceres_database::RecordFilter::parse(table, &pairs) else {
            return Ok(None);
        };

        let store = self.store.clone();
        let awaitable = pyo3_async_runtimes::tokio::future_into_py(py, async move {
            store
                .count_filter(table, &filter)
                .await
                .map_err(to_value_error)
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
