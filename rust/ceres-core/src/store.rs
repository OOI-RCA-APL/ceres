//! The query layer's connection to its database.
//!
//! The Python query layer compiles its statements through the native filter compiler and
//! runs them here so one pool serves the whole process rather than the native path
//! sitting beside a second one. Rows come back keyed by column, in the Python types the
//! entity models hold, which lets a manager build its objects without a driver's
//! type mappers in between.

use std::sync::Arc;

use ceres_database::{Cell, Parameter, RecordStore, Table};
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyString};
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::entities::{RecordBatch, RecordTable};
use crate::interop::to_value_error;

/// Extract a compiled statement parameter, one of the primitives bind processors produce.
pub(crate) fn extract_parameter(value: &Bound<'_, PyAny>) -> PyResult<Parameter> {
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

    if value.is_instance_of::<PyBytes>() {
        return Ok(Parameter::Bytes(value.extract()?));
    }

    // The PostgreSQL driver takes timestamps and UUIDs natively so its bind processors
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

/// A natively-connected database the query layer reads and writes through.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
pub struct Store {
    pub(crate) store: Arc<RecordStore>,
}

#[gen_stub_pymethods]
#[pymethods]
impl Store {
    /// Open the store a connection describes.
    ///
    /// A writable store runs the connection's `init` statements because it is the
    /// connection a database opens for itself. A read-only store serves queries on a
    /// pool of its own and never runs them.
    #[new]
    #[pyo3(signature = (connection, writable=true))]
    fn new(connection: &crate::connection::Connection, writable: bool) -> PyResult<Self> {
        let store = if writable {
            connection.store()?
        } else {
            connection.reader()?
        };

        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Execute a compiled record query, as an awaitable `RecordBatch`.
    ///
    /// The statement text and parameters come from the query layer's own compiler so any
    /// filter it can express runs natively with identical semantics. Rows go from the
    /// driver to JSON without any Python entity objects in between.
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

    /// Execute a statement that returns rows, as an awaitable list of column mappings.
    ///
    /// `table` names the table the rows come from, which says whether a column
    /// of text holds a UUID, a timestamp, or a name. A statement belonging to no table,
    /// as a migration runs, passes `None` and reads values as stored.
    #[pyo3(signature = (sql, parameters, table=None))]
    fn fetch<'py>(
        &self,
        py: Python<'py>,
        sql: String,
        #[gen_stub(override_type(type_repr = "list[typing.Any]"))] parameters: Vec<
            Bound<'_, PyAny>,
        >,
        table: Option<&str>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let table = named(table)?;
        let parameters = parameters
            .iter()
            .map(extract_parameter)
            .collect::<PyResult<Vec<_>>>()?;
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let rows = store
                .fetch_dynamic(table, &sql, parameters)
                .await
                .map_err(to_value_error)?;
            // The mappings are unbound before the future resolves because a bound
            // object holds the interpreter's lifetime and cannot cross a thread.
            Python::attach(|py| {
                rows.iter()
                    .map(|row| mapping(py, row).map(|held| held.unbind()))
                    .collect::<PyResult<Vec<_>>>()
            })
        })
    }

    /// Execute a statement that returns rows, as chunks read as they arrive.
    ///
    /// The chunked twin of `fetch`. Rows reach the caller as they arrive so a query
    /// over a large table costs one chunk of memory rather than the whole result.
    #[pyo3(signature = (sql, parameters, table=None))]
    fn stream(
        &self,
        sql: String,
        #[gen_stub(override_type(type_repr = "list[typing.Any]"))] parameters: Vec<
            Bound<'_, PyAny>,
        >,
        table: Option<&str>,
    ) -> PyResult<RowChunks> {
        let table = named(table)?;
        let parameters = parameters
            .iter()
            .map(extract_parameter)
            .collect::<PyResult<Vec<_>>>()?;
        let store = self.store.clone();
        // One chunk of depth lets the query read ahead of the reader by exactly one,
        // which overlaps the two without letting either run away from the other.
        let (sender, receiver) = std::sync::mpsc::sync_channel(1);
        let runtime = pyo3_async_runtimes::tokio::get_runtime();
        let handle = runtime.handle().clone();
        runtime.spawn_blocking(move || {
            let outcome = handle.block_on(async {
                let mut sink = |rows: Vec<ceres_database::Row>| {
                    // A closed channel is the reader having gone away, which ends the
                    // query rather than reporting anything.
                    sender
                        .send(Ok(rows))
                        .map_err(|_| ceres_database::Error::Decode("the reader stopped".into()))
                };
                store
                    .stream_dynamic(table, &sql, parameters, &mut sink)
                    .await
            });

            if let Err(error) = outcome {
                let _ = sender.send(Err(error));
            }
        });

        Ok(RowChunks {
            chunks: Arc::new(std::sync::Mutex::new(receiver)),
        })
    }

    /// Execute a statement that returns no rows, as an awaitable count of rows touched.
    fn execute<'py>(
        &self,
        py: Python<'py>,
        sql: String,
        #[gen_stub(override_type(type_repr = "list[typing.Any]"))] parameters: Vec<
            Bound<'_, PyAny>,
        >,
    ) -> PyResult<Bound<'py, PyAny>> {
        let parameters = parameters
            .iter()
            .map(extract_parameter)
            .collect::<PyResult<Vec<_>>>()?;
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            store
                .execute_dynamic(&sql, parameters)
                .await
                .map_err(to_value_error)
        })
    }

    /// Run a script of `;`-separated statements, as an awaitable.
    fn execute_script<'py>(&self, py: Python<'py>, sql: String) -> PyResult<Bound<'py, PyAny>> {
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            store.execute_script(&sql).await.map_err(to_value_error)
        })
    }
}

/// A streamed result, handed over one chunk of rows at a time.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
pub struct RowChunks {
    chunks: Arc<std::sync::Mutex<std::sync::mpsc::Receiver<StreamedRows>>>,
}

/// One chunk as the streaming query produced it, or what stopped the query.
type StreamedRows = Result<Vec<ceres_database::Row>, ceres_database::Error>;

#[gen_stub_pymethods]
#[pymethods]
impl RowChunks {
    /// The next chunk of column mappings, `None` once the query is spent.
    ///
    /// Waiting for a chunk blocks a thread of its own rather than the event loop so a
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
                .map_err(to_value_error)?;

            match received {
                // A disconnected channel is the query having run to its end.
                Err(_) => Ok(None),
                Ok(Ok(rows)) => Python::attach(|py| {
                    // The mappings are unbound before the future resolves because a
                    // bound object holds the interpreter's lifetime and cannot cross a
                    // thread.
                    rows.iter()
                        .map(|row| mapping(py, row).map(|held| held.unbind()))
                        .collect::<PyResult<Vec<_>>>()
                        .map(Some)
                }),
                Ok(Err(error)) => Err(to_value_error(error)),
            }
        })
    }
}

/// The table a statement reads, by name, refusing one no table answers to.
fn named(table: Option<&str>) -> PyResult<Option<Table>> {
    table.map(crate::filters::table_of).transpose()
}

/// One row as a mapping of column name to the Python value the column holds.
fn mapping<'py>(py: Python<'py>, row: &ceres_database::Row) -> PyResult<Bound<'py, PyDict>> {
    let mapping = PyDict::new(py);
    for (name, cell) in row {
        mapping.set_item(name, value(py, cell)?)?;
    }

    Ok(mapping)
}

/// One cell as the Python object the entity models hold for that column.
fn value<'py>(py: Python<'py>, cell: &Cell) -> PyResult<Bound<'py, PyAny>> {
    use pyo3::IntoPyObjectExt;

    Ok(match cell {
        Cell::Null => py.None().into_bound(py),
        Cell::Bool(held) => held.into_bound_py_any(py)?,
        Cell::Integer(held) => held.into_bound_py_any(py)?,
        Cell::Float(held) => held.into_bound_py_any(py)?,
        Cell::Text(held) => held.into_bound_py_any(py)?,
        Cell::Bytes(held) => PyBytes::new(py, held).into_any(),
        // The models hold aware UTC instants so a naive one would read in local time
        // wherever it was compared or rendered.
        Cell::Timestamp(held) => held.and_utc().into_bound_py_any(py)?,
        Cell::Uuid(held) => held.into_bound_py_any(py)?,
        Cell::Json(held) => crate::interop::to_python(py, held)?.into_bound(py),
    })
}
