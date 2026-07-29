//! The database configuration classes.
//!
//! Each backend is declared through `python_config!` like every other section. What is unusual
//! here is the shape of the section: the backends share a set of fields carried in a flattened
//! `shared` struct, `TursoDatabaseConfig` natively extends `SQLiteDatabaseConfig`, and each
//! class serializes through the tagged `DatabaseConfig` union so its `type` selector appears
//! in dictionary form. The hashing configuration crosses the boundary as a union of two bound
//! classes, dispatched by the same kind of `type` selector.

use std::path::PathBuf;

use ceres_macros::python_config;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use pyo3_stub_gen::derive::gen_stub_pymethods;

use crate::interop::{PyFieldType, ToPyValue};

python_config! {
    /// SQL statements executed at well-known points in the database lifecycle.
    DatabaseConfigHooks(ceres_config::DatabaseConfigHooks, ceres_config::RawDatabaseConfigHooks) {
        /// Statements run once when the database is first created.
        init: Option<Vec<String>>,
        /// Statements run on every new connection.
        connect: Option<Vec<String>>,
        /// Statements run before a connection is closed.
        close: Option<Vec<String>>,
    }

    /// Configuration for the bcrypt password hashing algorithm.
    #[python(serialize_as = ceres_config::HashingConfig::Bcrypt)]
    BCryptHashingConfig(
        ceres_config::BcryptHashingConfig,
        ceres_config::RawBcryptHashingConfig
    ) {
        /// Cost factor controlling how expensive each hash is to compute.
        rounds: i64,
    }

    /// Configuration for the Argon2id password hashing algorithm.
    ///
    /// Default parameters mirror `argon2.profiles.RFC_9106_LOW_MEMORY`, callers can tune
    /// them to trade memory and CPU cost against latency.
    #[python(serialize_as = ceres_config::HashingConfig::Argon2)]
    Argon2HashingConfig(
        ceres_config::Argon2HashingConfig,
        ceres_config::RawArgon2HashingConfig
    ) {
        /// Number of iterations Argon2 performs.
        time_cost: i64,
        /// Memory budget in KiB.
        memory_cost: i64,
        /// Number of parallel lanes used during hashing.
        parallelism: i64,
        /// Length of the produced hash in bytes.
        hash_length: i64,
        /// Length of the random salt in bytes.
        salt_length: i64,
    }

    /// Configuration for a SQLite-backed database, the default for local deployments.
    #[python(shared = ceres_config::RawSharedDatabaseConfig)]
    #[python(serialize_as = ceres_config::DatabaseConfig::Sqlite)]
    SQLiteDatabaseConfig(
        ceres_config::SqliteDatabaseConfig,
        ceres_config::RawSqliteDatabaseConfig
    ) {
        /// Path to the SQLite file. Omit to use a temporary on-disk file, or set to
        /// `:memory:` (see `in_memory`) for a private in-memory database.
        path: Option<PathBuf>,
        /// SQL statements executed at well-known points in the database lifecycle.
        #[python(shared, nested = DatabaseConfigHooks)]
        hooks: ceres_config::DatabaseConfigHooks,
        /// Extra keyword arguments forwarded to the SQLAlchemy engine factory.
        #[python(shared, any = "dict[str, typing.Any]")]
        engine: serde_json::Map<String, serde_json::Value>,
        /// Password hashing configuration used for users stored in this database.
        #[python(shared)]
        hashing: ceres_config::HashingConfig,
        /// Optional database-specific connection string query parameters.
        #[python(shared, any = "dict[str, str | list[str]] | None")]
        query: Option<std::collections::BTreeMap<String, ceres_config::MaybeSequence<String>>>,
    }

    /// Configuration for a Turso-backed database, a SQLite-compatible file that allows
    /// concurrent writers.
    #[python(shared = ceres_config::RawSharedDatabaseConfig)]
    #[python(serialize_as = ceres_config::DatabaseConfig::Turso)]
    TursoDatabaseConfig(
        ceres_config::TursoDatabaseConfig,
        ceres_config::RawTursoDatabaseConfig
    ): SQLiteDatabaseConfig {
        /// Path to the database file. Omit to use a temporary on-disk file, or set to
        /// `:memory:` (see `in_memory`) for a private in-memory database.
        path: Option<PathBuf>,
        /// Put the database in Turso's MVCC journal mode, which is what lets writers
        /// overlap. This converts the database file and the conversion cannot be undone.
        mvcc: bool,
        /// SQL statements executed at well-known points in the database lifecycle.
        #[python(shared, nested = DatabaseConfigHooks)]
        hooks: ceres_config::DatabaseConfigHooks,
        /// Extra keyword arguments forwarded to the SQLAlchemy engine factory.
        #[python(shared, any = "dict[str, typing.Any]")]
        engine: serde_json::Map<String, serde_json::Value>,
        /// Password hashing configuration used for users stored in this database.
        #[python(shared)]
        hashing: ceres_config::HashingConfig,
        /// Optional database-specific connection string query parameters.
        #[python(shared, any = "dict[str, str | list[str]] | None")]
        query: Option<std::collections::BTreeMap<String, ceres_config::MaybeSequence<String>>>,
    }

    /// Configuration for a PostgreSQL-backed database.
    #[python(shared = ceres_config::RawSharedDatabaseConfig)]
    #[python(serialize_as = ceres_config::DatabaseConfig::Postgres)]
    PostgresDatabaseConfig(
        ceres_config::PostgresDatabaseConfig,
        ceres_config::RawPostgresDatabaseConfig
    ) {
        /// Host the database server listens on.
        host: String,
        /// Port the database server listens on.
        port: Option<u16>,
        /// Name of the database to connect to.
        database: String,
        /// User to authenticate as.
        user: String,
        /// Password to authenticate with.
        password: Option<ceres_config::Secret>,
        /// SQL statements executed at well-known points in the database lifecycle.
        #[python(shared, nested = DatabaseConfigHooks)]
        hooks: ceres_config::DatabaseConfigHooks,
        /// Extra keyword arguments forwarded to the SQLAlchemy engine factory.
        #[python(shared, any = "dict[str, typing.Any]")]
        engine: serde_json::Map<String, serde_json::Value>,
        /// Password hashing configuration used for users stored in this database.
        #[python(shared)]
        hashing: ceres_config::HashingConfig,
        /// Optional database-specific connection string query parameters.
        #[python(shared, any = "dict[str, str | list[str]] | None")]
        query: Option<std::collections::BTreeMap<String, ceres_config::MaybeSequence<String>>>,
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl BCryptHashingConfig {
    /// The algorithm selector for this configuration.
    #[getter]
    fn r#type(&self) -> &'static str {
        "bcrypt"
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl Argon2HashingConfig {
    /// The algorithm selector for this configuration.
    #[getter]
    fn r#type(&self) -> &'static str {
        "argon2"
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl SQLiteDatabaseConfig {
    /// The backend selector for this configuration.
    #[getter]
    fn r#type(&self) -> &'static str {
        "sqlite"
    }

    /// Whether `path` is the special `:memory:` sentinel used by `in_memory`.
    #[getter]
    fn is_memory(&self) -> bool {
        self.inner.is_memory()
    }

    /// Build a config for a private in-memory database scoped to this process.
    ///
    /// The returned database exists only in memory for the lifetime of its engine, useful
    /// for tests and other short-lived, detached databases that should never touch disk.
    #[classmethod]
    #[gen_stub(override_return_type(type_repr = "Self"))]
    fn in_memory(cls: &Bound<'_, PyType>) -> PyResult<Py<PyAny>> {
        let kwargs = PyDict::new(cls.py());
        kwargs.set_item("path", ceres_config::MEMORY_PATH)?;
        Ok(cls.call((), Some(&kwargs))?.unbind())
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl TursoDatabaseConfig {
    /// The backend selector for this configuration.
    #[getter]
    fn r#type(&self) -> &'static str {
        "turso"
    }

    /// Whether `path` is the special `:memory:` sentinel used by `in_memory`.
    #[getter]
    fn is_memory(&self) -> bool {
        self.inner.is_memory()
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl PostgresDatabaseConfig {
    /// The backend selector for this configuration.
    #[getter]
    fn r#type(&self) -> &'static str {
        "postgres"
    }
}

/// A hashing configuration constructor argument, accepting a bound instance or a mapping
/// carrying a `type` selector.
pub struct HashingConfigInput(ceres_config::RawHashingConfig);

impl FromPyObject<'_, '_> for HashingConfigInput {
    type Error = PyErr;

    fn extract(value: pyo3::Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(config) = value.cast::<BCryptHashingConfig>() {
            return Ok(Self(ceres_config::RawHashingConfig::Bcrypt(
                crate::interop::reraw(&config.borrow().inner)?,
            )));
        }

        if let Ok(config) = value.cast::<Argon2HashingConfig>() {
            return Ok(Self(ceres_config::RawHashingConfig::Argon2(
                crate::interop::reraw(&config.borrow().inner)?,
            )));
        }

        let mapping = value.cast::<PyDict>().map_err(|_| {
            PyValueError::new_err(
                "hashing must be a BCryptHashingConfig, an Argon2HashingConfig, or a mapping",
            )
        })?;
        Ok(Self(crate::interop::from_python(mapping.as_any())?))
    }
}

impl pyo3_stub_gen::PyStubType for HashingConfigInput {
    fn type_output() -> pyo3_stub_gen::TypeInfo {
        pyo3_stub_gen::TypeInfo::builtin(
            "BCryptHashingConfig | Argon2HashingConfig | dict[str, typing.Any]",
        )
    }
}

impl PyFieldType for ceres_config::HashingConfig {
    type Input = HashingConfigInput;
    type Py = HashingConfigPy;
    type Raw = ceres_config::RawHashingConfig;

    fn from_input(input: HashingConfigInput) -> PyResult<ceres_config::RawHashingConfig> {
        Ok(input.0)
    }
}

/// The Python-facing form of a hashing configuration, one of the two bound classes.
#[derive(IntoPyObject)]
pub enum HashingConfigPy {
    Bcrypt(BCryptHashingConfig),
    Argon2(Argon2HashingConfig),
}

impl pyo3_stub_gen::PyStubType for HashingConfigPy {
    fn type_output() -> pyo3_stub_gen::TypeInfo {
        pyo3_stub_gen::TypeInfo::builtin("BCryptHashingConfig | Argon2HashingConfig")
    }
}

impl ToPyValue<HashingConfigPy> for ceres_config::HashingConfig {
    fn to_py_value(&self) -> HashingConfigPy {
        match self {
            Self::Bcrypt(config) => HashingConfigPy::Bcrypt(BCryptHashingConfig {
                inner: config.clone(),
            }),
            Self::Argon2(config) => HashingConfigPy::Argon2(Argon2HashingConfig {
                inner: config.clone(),
            }),
        }
    }
}
