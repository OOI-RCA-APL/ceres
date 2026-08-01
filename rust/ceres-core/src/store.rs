//! The query layer's connection to its database.
//!
//! The Python query layer compiles its statements through the native filter compiler and
//! runs them here, so one pool serves the whole process rather than the native path
//! sitting beside a second one. Rows come back keyed by column, in the Python types the
//! entity models hold, which is what lets a manager build its objects without a driver's
//! type mappers in between.

use std::sync::Arc;

use ceres_database::{Cell, RecordStore, Table};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::fetcher::{extract_parameter, to_value_error};

/// A natively-connected database the query layer reads and writes through.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct Store {
    store: Arc<RecordStore>,
}

#[gen_stub_pymethods]
#[pymethods]
impl Store {
    /// Open a store over a SQLite database file.
    #[staticmethod]
    fn sqlite(path: &str) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let store = RecordStore::sqlite_writable(path).map_err(to_value_error)?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Open a store over a Turso database file.
    #[staticmethod]
    fn turso(path: &str, mvcc: bool) -> PyResult<Self> {
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        Ok(Self {
            store: Arc::new(RecordStore::turso(path, mvcc)),
        })
    }

    /// Open a store over a PostgreSQL database.
    #[staticmethod]
    #[pyo3(signature = (
        host,
        database,
        user,
        port=None,
        password=None,
        settings=Vec::new(),
        parameters=Vec::new(),
    ))]
    fn postgres(
        host: &str,
        database: &str,
        user: &str,
        port: Option<u16>,
        password: Option<&str>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
    ) -> PyResult<Self> {
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let store =
            RecordStore::postgres(host, port, database, user, password, settings, parameters)
                .map_err(to_value_error)?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Execute a statement that returns rows, as an awaitable list of column mappings.
    ///
    /// `table` names the table the rows come from, which is what says whether a column
    /// of text holds a UUID, a timestamp, or a name. A statement belonging to no table,
    /// which is what a migration runs, passes `None` and reads values as stored.
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
            // The mappings are unbound before the future resolves, because a bound
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
    /// The chunked twin of `fetch`. A caller iterating a result rather than collecting it
    /// holds one chunk at a time, so a query over a large table costs a chunk of memory
    /// rather than the whole result, and the first rows reach the caller before the last
    /// ones have been read.
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
#[pyclass(module = "ceres_core", frozen)]
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
                .map_err(|error| pyo3::exceptions::PyValueError::new_err(error.to_string()))?;

            match received {
                // A disconnected channel is the query having run to its end.
                Err(_) => Ok(None),
                Ok(Ok(rows)) => Python::attach(|py| {
                    // The mappings are unbound before the future resolves, because a
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
    match table {
        None => Ok(None),
        Some(name) => Table::parse(name).map(Some).ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err(format!("no table is named {name:?}"))
        }),
    }
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
        // The models hold aware UTC instants, so a naive one would read in local time
        // wherever it was compared or rendered.
        Cell::Timestamp(held) => held.and_utc().into_bound_py_any(py)?,
        Cell::Uuid(held) => held.into_bound_py_any(py)?,
        Cell::Json(held) => crate::interop::to_python(py, held)?.into_bound(py),
    })
}
