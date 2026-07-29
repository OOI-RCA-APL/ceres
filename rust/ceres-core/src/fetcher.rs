//! The native record fetcher.
//!
//! Bridges `ceres-database` into asyncio. A fetcher holds a lazily-connecting pool over the
//! same database the Python layer resolved, and `fetch` returns an awaitable producing a
//! [`RecordBatch`](crate::entities::RecordBatch), so a record listing goes from the driver
//! to JSON without any Python entity objects in between.

use std::sync::Arc;

use ceres_database::{RecordStore, RecordTable};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::entities::RecordBatch;

/// A natively-connected view of a Ceres database, serving record reads.
///
/// Built from resolved connection parameters rather than a configuration, because the
/// Python layer resolves per-instance details like temporary SQLite paths. Connections
/// open lazily on first use.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordFetcher {
    store: Arc<RecordStore>,
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
    #[staticmethod]
    #[pyo3(signature = (host, database, user, port=None, password=None))]
    fn postgres(
        host: &str,
        database: &str,
        user: &str,
        port: Option<u16>,
        password: Option<&str>,
    ) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let store =
            RecordStore::postgres(host, port, database, user, password).map_err(to_value_error)?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Fetch a record listing ordered by timestamp, as an awaitable `RecordBatch`.
    #[pyo3(signature = (table, limit=None, offset=None))]
    fn fetch<'py>(
        &self,
        py: Python<'py>,
        table: &str,
        limit: Option<u64>,
        offset: Option<u64>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let table = RecordTable::parse(table).map_err(to_value_error)?;
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let records = store
                .fetch(table, limit, offset)
                .await
                .map_err(to_value_error)?;
            Ok(RecordBatch { records })
        })
    }
}

fn to_value_error(error: ceres_database::Error) -> PyErr {
    PyValueError::new_err(error.to_string())
}
