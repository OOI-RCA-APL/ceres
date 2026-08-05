//! The native record fetcher.
//!
//! Bridges `ceres-database` into asyncio. A fetcher holds a lazily-connecting pool over the
//! same database the Python layer resolved, and `fetch_sql` returns an awaitable producing
//! a [`RecordBatch`](crate::entities::RecordBatch), so a record listing goes from the
//! driver to JSON without any Python entity objects in between.

use std::sync::Arc;

use ceres_database::{Parameter, RecordStore};
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes as PyBytesType, PyFloat, PyInt, PyString};
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::entities::{EntityTable, RecordBatch, RecordTable};
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
#[pyclass(module = "ceres.__internal__.core", frozen)]
pub struct RecordFetcher {
    pub(crate) store: Arc<RecordStore>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordFetcher {
    /// Open a fetcher over a SQLite database file.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life.
    #[staticmethod]
    #[pyo3(signature = (path, on_connect=Vec::new(), on_close=Vec::new()))]
    fn sqlite(path: &str, on_connect: Vec<String>, on_close: Vec<String>) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let store = RecordStore::sqlite(path, on_connect, on_close).map_err(to_value_error)?;
        Ok(Self {
            store: Arc::new(store),
        })
    }

    /// Open a fetcher over a Turso database file.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life. The `init` statements are the store's to run, that being
    /// the engine a database opens for itself.
    #[staticmethod]
    #[pyo3(signature = (path, mvcc, on_connect=Vec::new(), on_close=Vec::new()))]
    fn turso(path: &str, mvcc: bool, on_connect: Vec<String>, on_close: Vec<String>) -> Self {
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        Self {
            store: Arc::new(RecordStore::turso(
                path,
                mvcc,
                Vec::new(),
                on_connect,
                on_close,
            )),
        }
    }

    /// Open a fetcher over a PostgreSQL database.
    ///
    /// `settings` are per-connection server settings like `search_path`. `on_connect` and
    /// `on_close` are the configuration's own statements for a connection's two ends.
    #[staticmethod]
    #[pyo3(signature = (
        host,
        database,
        user,
        port=None,
        password=None,
        settings=Vec::new(),
        parameters=Vec::new(),
        on_connect=Vec::new(),
        on_close=Vec::new(),
    ))]
    #[allow(clippy::too_many_arguments)]
    fn postgres(
        host: &str,
        database: &str,
        user: &str,
        port: Option<u16>,
        password: Option<&str>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        // The `init` statements are the store's to run, that being the engine a database
        // opens for itself.
        let store = RecordStore::postgres(
            host,
            port,
            database,
            user,
            password,
            settings,
            parameters,
            Vec::new(),
            on_connect,
            on_close,
        )
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
}

/// Every column the native layer reads and writes, by table.
///
/// Each entry pairs a table name with its columns, and each column its name and the
/// family that decides how it decodes. This is the contract between the entity structs
/// and the schema the migrations create, and a column named here that the migrations do
/// not create is a decode failure on a live query rather than anything a build catches,
/// which is what the drift test exists to find first.
///
/// The order is load bearing. A table appears before anything holding a foreign key to
/// it, which is what lets a caller empty the schema by deleting in reverse.
// The `tables_precede_the_tables_that_reference_them` test pins the ordering. Named
// here rather than in the doc, because the doc becomes a Python docstring where a Rust
// test name means nothing.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn stored_columns() -> Vec<(&'static str, Vec<(&'static str, &'static str)>)> {
    use ceres_database::{EntityTable as Entities, RecordTable as Records};

    let records = [
        Records::Messages,
        Records::Particles,
        Records::Alerts,
        Records::Logs,
    ]
    .into_iter()
    .map(|table| (table.name(), described(table.columns())));
    let entities = [
        Entities::Users,
        Entities::Variables,
        Entities::Settings,
        Entities::Workspaces,
        Entities::WorkspaceEdits,
        Entities::Groups,
        Entities::GroupMemberships,
        Entities::UserPermissions,
        Entities::GroupPermissions,
    ]
    .into_iter()
    .map(|table| (table.name(), described(table.columns())));

    records.chain(entities).collect()
}

/// One table's columns as name and family, the family named the way it reads.
fn described(columns: &'static [ceres_entities::FilterField]) -> Vec<(&'static str, &'static str)> {
    use ceres_entities::FieldFamily;

    columns
        .iter()
        .map(|column| {
            let family = match column.family {
                FieldFamily::Uuid => "uuid",
                FieldFamily::Address | FieldFamily::PlainAddress => "address",
                FieldFamily::Timestamp => "timestamp",
                FieldFamily::Text => "text",
                FieldFamily::Email => "email",
                FieldFamily::Values(_) => "values",
                FieldFamily::Level => "level",
                FieldFamily::Bytes => "bytes",
                FieldFamily::Json | FieldFamily::JsonValue => "json",
                FieldFamily::Boolean => "boolean",
            };
            (column.key, family)
        })
        .collect()
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

/// Normalize an email address the way a native user write stores it, `None` for one
/// outside the subset the native path understands.
///
/// Exposed so the parity suite can hold the native subset against `email_validator`
/// itself, which is the direction that matters. An address this accepts and that library
/// rejects would be a row written natively that Python would have refused.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn normalize_email(value: &str) -> Option<String> {
    ceres_database::normalize_email(value)
}

/// The reserved domain names the native email subset refuses.
///
/// Exposed so the parity suite can hold it against the validator library's own list. A
/// name added there and not here would be an address written natively that Python
/// refuses.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn special_use_domains() -> Vec<&'static str> {
    ceres_database::SPECIAL_USE_DOMAINS.to_vec()
}

/// Hash a password with the given Argon2id parameters, `None` when they are out of range.
///
/// A value that already reads as a stored hash passes through, which is the user
/// manager's own rule.
///
/// This is the one Argon2 implementation the system has. The Python side calls it rather
/// than carrying a second one, so a hash written by a native command and a hash written
/// through the entity manager cannot drift apart.
///
/// The interpreter lock is released for the duration. Argon2 is deliberately expensive,
/// tens of milliseconds against the default memory cost, and holding the lock through it
/// would stall every other Python thread, the event loop included.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
#[pyo3(signature = (password, time_cost, memory_cost, parallelism, hash_length, salt_length))]
pub fn hash_argon2(
    py: Python<'_>,
    password: &str,
    time_cost: u32,
    memory_cost: u32,
    parallelism: u32,
    hash_length: usize,
    salt_length: usize,
) -> Option<String> {
    let credentials = ceres_database::Credentials::new(ceres_database::Hashing::Argon2(
        ceres_database::Argon2Params {
            time_cost,
            memory_cost,
            parallelism,
            hash_length,
            salt_length,
        },
    ));
    py.detach(|| credentials.password(password))
}

/// Hash a password with bcrypt at the given cost, `None` when the cost is out of range.
///
/// The other half of the one hashing implementation, for a database configured to use
/// bcrypt rather than the default. Releases the interpreter lock like the Argon2 pair.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn hash_bcrypt(py: Python<'_>, password: &str, rounds: u32) -> Option<String> {
    let credentials = ceres_database::Credentials::new(ceres_database::Hashing::Bcrypt(rounds));
    py.detach(|| credentials.password(password))
}

/// Whether a password matches a stored bcrypt hash, `None` for any other algorithm.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn verify_bcrypt(py: Python<'_>, password: &str, hash: &str) -> Option<bool> {
    py.detach(|| ceres_database::verify_bcrypt(password, hash))
}

/// Whether a password matches a stored Argon2 hash, `None` for any other algorithm.
///
/// The parameters come out of the encoded hash, so a stored one still verifies after the
/// configuration's parameters change. Releases the interpreter lock like `hash_argon2`,
/// and for the same reason, verifying costs what hashing costs.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn verify_argon2(py: Python<'_>, password: &str, hash: &str) -> Option<bool> {
    py.detach(|| ceres_database::verify_argon2(password, hash))
}

/// Whether a password matches a stored hash of either algorithm.
///
/// The algorithm is read off the hash itself rather than taken from a configuration,
/// which is what lets a database keep verifying rows written before its hashing was
/// changed. A value that reads as neither algorithm's hash matches nothing.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn verify_password(py: Python<'_>, password: &str, hash: &str) -> bool {
    py.detach(|| {
        ceres_database::verify_argon2(password, hash)
            .or_else(|| ceres_database::verify_bcrypt(password, hash))
            .unwrap_or(false)
    })
}

/// A natively-connected writer for record entities.
///
/// Entities extract into native records synchronously, then a whole flush upserts in one
/// transaction on the writer's own pool. Built from resolved connection parameters like
/// the fetcher, and matching the query layer's connection semantics.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
pub struct RecordWriter {
    writer: Arc<ceres_database::RecordWriter>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordWriter {
    /// Open a writer over a SQLite database file.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life.
    #[staticmethod]
    #[pyo3(signature = (path, on_connect=Vec::new(), on_close=Vec::new()))]
    fn sqlite(path: &str, on_connect: Vec<String>, on_close: Vec<String>) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let writer = ceres_database::RecordWriter::sqlite(path, on_connect, on_close)
            .map_err(to_value_error)?;
        Ok(Self {
            writer: Arc::new(writer),
        })
    }

    /// Open a writer over a Turso database file.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life.
    #[staticmethod]
    #[pyo3(signature = (path, mvcc, on_connect=Vec::new(), on_close=Vec::new()))]
    fn turso(path: &str, mvcc: bool, on_connect: Vec<String>, on_close: Vec<String>) -> Self {
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        Self {
            writer: Arc::new(ceres_database::RecordWriter::turso(
                path, mvcc, on_connect, on_close,
            )),
        }
    }

    /// Open a writer over a PostgreSQL database, with per-connection server settings.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life.
    #[staticmethod]
    #[pyo3(signature = (
        host,
        database,
        user,
        port=None,
        password=None,
        settings=Vec::new(),
        parameters=Vec::new(),
        on_connect=Vec::new(),
        on_close=Vec::new(),
    ))]
    #[allow(clippy::too_many_arguments)]
    fn postgres(
        host: &str,
        database: &str,
        user: &str,
        port: Option<u16>,
        password: Option<&str>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> PyResult<Self> {
        // Pool construction spawns maintenance tasks, which needs the runtime's context.
        let _guard = pyo3_async_runtimes::tokio::get_runtime().enter();
        let writer = ceres_database::RecordWriter::postgres(
            host, port, database, user, password, settings, parameters, on_connect, on_close,
        )
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

#[cfg(test)]
mod tests {
    use super::stored_columns;

    #[test]
    fn tables_precede_the_tables_that_reference_them() {
        // `Database.clear()` empties the schema by deleting in reverse of this order, so a
        // referenced table has to come first or the delete fails on its foreign keys.
        // Reordering the lists in `stored_columns` breaks that silently, hence this.
        let order: Vec<&str> = stored_columns().into_iter().map(|(name, _)| name).collect();
        let position = |name: &str| {
            order
                .iter()
                .position(|held| *held == name)
                .unwrap_or_else(|| panic!("{name} is stored"))
        };

        for (referenced, holder) in [
            ("users", "settings"),
            ("users", "workspaces"),
            ("users", "workspace_edits"),
            ("workspaces", "workspace_edits"),
            ("users", "group_memberships"),
            ("groups", "group_memberships"),
            ("users", "user_permissions"),
            ("groups", "group_permissions"),
        ] {
            assert!(
                position(referenced) < position(holder),
                "{holder} references {referenced}, so {referenced} must be listed first"
            );
        }
    }
}
