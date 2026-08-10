//! Resolved database connection parameters.
//!
//! The Python layer resolves its configuration once, temporary paths and secrets
//! included, into a [`Connection`], and every native consumer opens from it so the
//! stores and the record writer cannot connect differently.

use ceres_database::{RecordStore, RecordWriter};
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::interop::to_value_error;

/// Where one database lives and the statements its connections run.
///
/// The `init` statements belong to the writable store alone because it is the
/// connection a database opens for itself, while every pool takes the per-connection
/// pair.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
#[derive(Clone)]
pub struct Connection {
    kind: Kind,
    on_init: Vec<String>,
    on_connect: Vec<String>,
    on_close: Vec<String>,
}

/// The backend a connection reaches, with what reaching it takes.
#[derive(Clone)]
enum Kind {
    Sqlite {
        path: String,
    },
    Turso {
        path: String,
        mvcc: bool,
    },
    Postgres {
        host: String,
        database: String,
        user: String,
        port: Option<u16>,
        password: Option<String>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
    },
}

#[gen_stub_pymethods]
#[pymethods]
impl Connection {
    /// Describe a SQLite database file.
    ///
    /// The statement lists are the configuration's own, for the first connection and
    /// for the two ends of every connection's life, run after each backend's.
    #[staticmethod]
    #[pyo3(signature = (path, on_init=Vec::new(), on_connect=Vec::new(), on_close=Vec::new()))]
    fn sqlite(
        path: String,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Self {
        Self {
            kind: Kind::Sqlite { path },
            on_init,
            on_connect,
            on_close,
        }
    }

    /// Describe a Turso database file, with its journaling mode.
    #[staticmethod]
    #[pyo3(signature = (path, mvcc, on_init=Vec::new(), on_connect=Vec::new(), on_close=Vec::new()))]
    fn turso(
        path: String,
        mvcc: bool,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Self {
        Self {
            kind: Kind::Turso { path, mvcc },
            on_init,
            on_connect,
            on_close,
        }
    }

    /// Describe a PostgreSQL database.
    ///
    /// `settings` are per-connection server settings like `search_path`, and
    /// `parameters` are the connection string's own, applied by name.
    #[staticmethod]
    #[pyo3(signature = (
        host,
        database,
        user,
        port=None,
        password=None,
        settings=Vec::new(),
        parameters=Vec::new(),
        on_init=Vec::new(),
        on_connect=Vec::new(),
        on_close=Vec::new(),
    ))]
    #[allow(clippy::too_many_arguments)]
    fn postgres(
        host: String,
        database: String,
        user: String,
        port: Option<u16>,
        password: Option<String>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Self {
        Self {
            kind: Kind::Postgres {
                host,
                database,
                user,
                port,
                password,
                settings,
                parameters,
            },
            on_init,
            on_connect,
            on_close,
        }
    }
}

impl Connection {
    /// Open the writable store this connection describes, `init` statements included.
    pub(crate) fn store(&self) -> PyResult<RecordStore> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        match &self.kind {
            Kind::Sqlite { path } => RecordStore::sqlite_writable(
                path,
                self.on_init.clone(),
                self.on_connect.clone(),
                self.on_close.clone(),
            )
            .map_err(to_value_error),
            Kind::Turso { path, mvcc } => Ok(RecordStore::turso(
                path,
                *mvcc,
                self.on_init.clone(),
                self.on_connect.clone(),
                self.on_close.clone(),
            )),
            Kind::Postgres { .. } => self.postgres_store(self.on_init.clone()),
        }
    }

    /// Open a read pool with no `init` statements, for a read-only store.
    pub(crate) fn reader(&self) -> PyResult<RecordStore> {
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        match &self.kind {
            Kind::Sqlite { path } => {
                RecordStore::sqlite(path, self.on_connect.clone(), self.on_close.clone())
                    .map_err(to_value_error)
            }
            Kind::Turso { path, mvcc } => Ok(RecordStore::turso(
                path,
                *mvcc,
                Vec::new(),
                self.on_connect.clone(),
                self.on_close.clone(),
            )),
            Kind::Postgres { .. } => self.postgres_store(Vec::new()),
        }
    }

    /// Open the record writer's pool, which never runs `init` statements.
    pub(crate) fn writer(&self) -> PyResult<RecordWriter> {
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        match &self.kind {
            Kind::Sqlite { path } => {
                RecordWriter::sqlite(path, self.on_connect.clone(), self.on_close.clone())
                    .map_err(to_value_error)
            }
            Kind::Turso { path, mvcc } => Ok(RecordWriter::turso(
                path,
                *mvcc,
                self.on_connect.clone(),
                self.on_close.clone(),
            )),
            Kind::Postgres {
                host,
                database,
                user,
                port,
                password,
                settings,
                parameters,
            } => RecordWriter::postgres(
                host,
                *port,
                database,
                user,
                password.as_deref(),
                settings.clone(),
                parameters.clone(),
                self.on_connect.clone(),
                self.on_close.clone(),
            )
            .map_err(to_value_error),
        }
    }

    /// Open a PostgreSQL store carrying the given `init` statements.
    fn postgres_store(&self, on_init: Vec<String>) -> PyResult<RecordStore> {
        let Kind::Postgres {
            host,
            database,
            user,
            port,
            password,
            settings,
            parameters,
        } = &self.kind
        else {
            unreachable!("only the postgres arms call this");
        };

        RecordStore::postgres(
            host,
            *port,
            database,
            user,
            password.as_deref(),
            settings.clone(),
            parameters.clone(),
            on_init,
            self.on_connect.clone(),
            self.on_close.clone(),
        )
        .map_err(to_value_error)
    }
}
