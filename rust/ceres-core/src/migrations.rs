//! Schema migrations, exposed for the Python database layer.
//!
//! The runner itself lives in `ceres-database`, embedded scripts included. This module
//! carries the registry and the runner across the boundary so `ceres.database` delegates
//! migration work rather than holding a runner of its own.

use std::collections::HashMap;
use std::sync::Arc;

use ceres_database::migrations::{MigrateError, MigrationReporter, ReporterError, parse_dialect};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pyfunction, gen_stub_pymethods};

use crate::store::Store;

/// A single ordered schema migration backed by one or more SQL scripts.
///
/// Scripts are keyed by dialect (`sqlite`/`postgresql`), `None` for one shared across
/// dialects. The known migrations come embedded from `migrations()`, and constructing one
/// directly serves tests that migrate a database through scripts of their own.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
#[derive(Clone)]
pub struct Migration {
    pub(crate) inner: ceres_database::migrations::Migration,
}

#[gen_stub_pymethods]
#[pymethods]
impl Migration {
    #[new]
    fn new(
        id: i64,
        name: String,
        #[gen_stub(override_type(type_repr = "dict[str | None, str]"))] scripts: HashMap<
            Option<String>,
            String,
        >,
    ) -> PyResult<Self> {
        let scripts = scripts
            .into_iter()
            .map(|(dialect, script)| match dialect {
                None => Ok((None, script)),
                Some(name) => match parse_dialect(&name) {
                    Some(dialect) => Ok((Some(dialect), script)),
                    None => Err(PyValueError::new_err(format!(
                        "{name:?} is not a migration script dialect"
                    ))),
                },
            })
            .collect::<PyResult<Vec<_>>>()?;

        let inner = ceres_database::migrations::Migration::new(id, name, scripts)
            .map_err(PyValueError::new_err)?;
        Ok(Self { inner })
    }

    /// Unique sequential identifier parsed from the script filename prefix.
    #[getter]
    fn id(&self) -> i64 {
        self.inner.id()
    }

    /// Kebab-case name parsed from the script filename (e.g. `init`).
    #[getter]
    fn name(&self) -> &str {
        self.inner.name()
    }

    /// Return the SQL text for `dialect`, or `None` when this migration has no script
    /// for it (a recorded no-op).
    ///
    /// `dialect` accepts either spelling of a backend's name, and `turso` renders the
    /// SQLite script since the two take the same schema.
    fn render(&self, dialect: &str) -> Option<&str> {
        self.inner.render(parse_dialect(dialect))
    }

    fn __repr__(&self) -> String {
        format!(
            "Migration(id={}, name={:?})",
            self.inner.id(),
            self.inner.name()
        )
    }
}

/// Return every known migration, in application order.
#[gen_stub_pyfunction]
#[pyfunction]
pub fn migrations() -> Vec<Migration> {
    ceres_database::migrations::all()
        .iter()
        .map(|inner| Migration {
            inner: inner.clone(),
        })
        .collect()
}

/// Every script that creates the schema for `dialect`, in the order they run.
///
/// The bookkeeping table's DDL comes first since it is what records the rest as they are
/// applied, and a migration with no script for the dialect contributes nothing.
#[gen_stub_pyfunction]
#[pyfunction]
pub fn migration_ddl(dialect: &str, migrations: Vec<Migration>) -> PyResult<Vec<String>> {
    let dialect = parse_dialect(dialect)
        .ok_or_else(|| PyValueError::new_err(format!("{dialect:?} is not a database dialect")))?;
    let migrations: Vec<_> = migrations
        .into_iter()
        .map(|migration| migration.inner)
        .collect();
    Ok(ceres_database::migrations::ddl(&migrations, dialect))
}

/// Return the warning to log before a migration that discards data runs, by name.
#[gen_stub_pyfunction]
#[pyfunction]
pub fn destructive_migration_warning(name: &str) -> Option<&'static str> {
    ceres_database::migrations::destructive_warning(name)
}

/// Forward the runner's progress to a Python reporter object.
///
/// A raised exception aborts the run before the announced migration is applied, and comes
/// back to the caller as itself rather than as a runner failure.
struct PyReporter {
    reporter: Py<PyAny>,
    handles: HashMap<i64, Py<Migration>>,
}

impl PyReporter {
    fn handle(
        &self,
        py: Python<'_>,
        migration: &ceres_database::migrations::Migration,
    ) -> Py<Migration> {
        self.handles
            .get(&migration.id())
            .expect("every migration in the run was handed over")
            .clone_ref(py)
    }
}

impl MigrationReporter for PyReporter {
    fn starting(
        &mut self,
        migration: &ceres_database::migrations::Migration,
        index: usize,
        total: usize,
    ) -> Result<(), ReporterError> {
        Python::attach(|py| {
            self.reporter
                .call_method1(py, "starting", (self.handle(py, migration), index, total))
        })
        .map(drop)
        .map_err(|error| Box::new(error) as ReporterError)
    }

    fn finished(
        &mut self,
        migration: &ceres_database::migrations::Migration,
    ) -> Result<(), ReporterError> {
        Python::attach(|py| {
            self.reporter
                .call_method1(py, "finished", (self.handle(py, migration),))
        })
        .map(drop)
        .map_err(|error| Box::new(error) as ReporterError)
    }
}

/// A run failure as the exception the caller should see.
///
/// A reporter's own exception travels back as itself so a caller's failure is not
/// re-worded as a migration's.
fn to_py_error(error: MigrateError) -> PyErr {
    match error {
        MigrateError::Reporter(boxed) => match boxed.downcast::<PyErr>() {
            Ok(raised) => *raised,
            Err(other) => PyValueError::new_err(other.to_string()),
        },
        other => PyValueError::new_err(other.to_string()),
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl Store {
    /// Check whether the schema has been created in the database, as an awaitable.
    ///
    /// The question is whether any table the schema owns is there, not whether the
    /// database holds a table at all, so a table a configuration's `init` hook created
    /// never makes an empty database look bootstrapped.
    fn initialized<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            ceres_database::migrations::initialized(&store)
                .await
                .map_err(crate::interop::to_value_error)
        })
    }

    /// The IDs of every migration recorded as applied, ascending, as an awaitable.
    ///
    /// Creates the bookkeeping table first so an empty database answers with an empty
    /// list rather than an error.
    fn applied_migration_ids<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let store = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            ceres_database::migrations::applied_ids(&store)
                .await
                .map_err(crate::interop::to_value_error)
        })
    }

    /// Apply every pending migration in order, as an awaitable list of applied IDs.
    ///
    /// Each migration's script and the record that it ran go over as one batch so a
    /// migration cannot land without being recorded and then run twice. `reporter` is
    /// told which migration is starting and when it finished, for a caller showing
    /// progress.
    #[pyo3(signature = (migrations, reporter=None))]
    fn migrate<'py>(
        &self,
        py: Python<'py>,
        migrations: Vec<Py<Migration>>,
        #[gen_stub(override_type(type_repr = "typing.Any | None"))] reporter: Option<Py<PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let natives: Vec<_> = migrations
            .iter()
            .map(|migration| migration.borrow(py).inner.clone())
            .collect();
        let handles: HashMap<i64, Py<Migration>> = migrations
            .into_iter()
            .map(|migration| {
                let id = migration.borrow(py).inner.id();
                (id, migration)
            })
            .collect();
        let mut reporter = reporter.map(|reporter| PyReporter { reporter, handles });
        let store: Arc<ceres_database::RecordStore> = self.store.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let outcome = match reporter.as_mut() {
                Some(reporter) => {
                    ceres_database::migrations::migrate(&store, &natives, reporter).await
                }
                None => {
                    let mut silent = ceres_database::migrations::SilentReporter;
                    ceres_database::migrations::migrate(&store, &natives, &mut silent).await
                }
            };

            outcome.map_err(to_py_error)
        })
    }
}
