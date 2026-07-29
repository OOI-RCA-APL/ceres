//! The database configuration section.

use std::path::{Path, PathBuf};

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::values::{MaybeSequence, Secret, TimeDelta};

/// The path sentinel selecting a private in-memory SQLite database.
pub const MEMORY_PATH: &str = ":memory:";

/// Retry policy used when connecting to the database.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "DatabaseRetryConfig")]
pub struct DatabaseRetryConfig {
    /// Total time to keep retrying before giving up.
    pub timeout: TimeDelta,

    /// Delay between retry attempts.
    pub interval: TimeDelta,
}

impl Default for DatabaseRetryConfig {
    fn default() -> Self {
        Self {
            timeout: TimeDelta::from_secs(15),
            interval: TimeDelta::from_secs(3),
        }
    }
}

/// SQL statements executed at well-known points in the database lifecycle.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, Serialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "DatabaseConfigHooks")]
pub struct DatabaseConfigHooks {
    /// Statements run once when the database is first created.
    pub init: Option<Vec<String>>,

    /// Statements run on every new connection.
    pub connect: Option<Vec<String>>,

    /// Statements run before a connection is closed.
    pub close: Option<Vec<String>>,
}

/// Configuration for the bcrypt password hashing algorithm.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize, JsonSchema)]
#[serde(deny_unknown_fields)]
#[schemars(title = "BCryptHashingConfig")]
pub struct BcryptHashingConfig {
    /// Cost factor controlling how expensive each hash is to compute.
    #[serde(default = "default_bcrypt_rounds")]
    pub rounds: i64,
}

fn default_bcrypt_rounds() -> i64 {
    12
}

impl Default for BcryptHashingConfig {
    fn default() -> Self {
        Self {
            rounds: default_bcrypt_rounds(),
        }
    }
}

impl BcryptHashingConfig {
    fn validate(&self) -> Problems {
        let mut problems = Problems::default();
        if self.rounds < 4 {
            problems.push(Problem::new("rounds", "must be at least 4."));
        }

        problems
    }
}

/// Configuration for the Argon2id password hashing algorithm.
///
/// Default parameters mirror `argon2.profiles.RFC_9106_LOW_MEMORY`, callers can tune them to
/// trade memory and CPU cost against latency.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "Argon2HashingConfig")]
pub struct Argon2HashingConfig {
    /// Number of iterations Argon2 performs.
    pub time_cost: i64,

    /// Memory budget in KiB.
    pub memory_cost: i64,

    /// Number of parallel lanes used during hashing.
    pub parallelism: i64,

    /// Length of the produced hash in bytes.
    pub hash_length: i64,

    /// Length of the random salt in bytes.
    pub salt_length: i64,
}

impl Default for Argon2HashingConfig {
    fn default() -> Self {
        Self {
            time_cost: 3,
            memory_cost: 65536,
            parallelism: 4,
            hash_length: 32,
            salt_length: 16,
        }
    }
}

impl Argon2HashingConfig {
    fn validate(&self) -> Problems {
        let mut problems = Problems::default();
        if self.time_cost < 1 {
            problems.push(Problem::new("time_cost", "must be positive."));
        }

        if self.memory_cost < 8 {
            problems.push(Problem::new("memory_cost", "must be at least 8."));
        }

        if self.parallelism < 1 {
            problems.push(Problem::new("parallelism", "must be positive."));
        } else if self.memory_cost / self.parallelism < 8 {
            problems.push(Problem::new(
                "parallelism",
                "must be at least 8 times smaller than memory_cost.",
            ));
        }

        if !(4..=256).contains(&self.hash_length) {
            problems.push(Problem::new("hash_length", "must be between 4 and 256."));
        }

        if !(8..=64).contains(&self.salt_length) {
            problems.push(Problem::new("salt_length", "must be between 8 and 64."));
        }

        problems
    }
}

/// Password hashing configuration, dispatched by the `type` field.
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize, JsonSchema)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum HashingConfig {
    Bcrypt(BcryptHashingConfig),
    Argon2(Argon2HashingConfig),
}

impl Default for HashingConfig {
    fn default() -> Self {
        Self::Argon2(Argon2HashingConfig::default())
    }
}

impl HashingConfig {
    fn validate(&self) -> Problems {
        match self {
            Self::Bcrypt(config) => config.validate(),
            Self::Argon2(config) => config.validate(),
        }
    }
}

/// The settings shared by every database backend.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
struct RawSharedDatabaseConfig {
    hooks: Option<DatabaseConfigHooks>,

    /// Extra keyword arguments forwarded to the SQLAlchemy engine factory.
    ///
    /// Values must be JSON-compatible. Anything richer than that belongs in code rather than
    /// in configuration.
    engine: Option<serde_json::Map<String, serde_json::Value>>,

    /// Password hashing configuration used for users stored in this database.
    hashing: Option<HashingConfig>,

    /// Optional database-specific connection string query parameters.
    query: Option<std::collections::BTreeMap<String, MaybeSequence<String>>>,
}

/// The validated settings shared by every database backend.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct SharedDatabaseConfig {
    pub hooks: DatabaseConfigHooks,
    pub engine: serde_json::Map<String, serde_json::Value>,
    pub hashing: HashingConfig,
    pub query: Option<std::collections::BTreeMap<String, MaybeSequence<String>>>,
}

impl RawSharedDatabaseConfig {
    fn validate(self, problems: &mut Problems) -> SharedDatabaseConfig {
        let hashing = self.hashing.unwrap_or_default();
        problems.absorb(hashing.validate(), "hashing");

        SharedDatabaseConfig {
            hooks: self.hooks.unwrap_or_default(),
            engine: self.engine.unwrap_or_default(),
            hashing,
            query: self.query,
        }
    }
}

/// Configuration for a SQLite-backed database, the default for local deployments.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "SQLiteDatabaseConfig")]
pub struct RawSqliteDatabaseConfig {
    /// Path to the SQLite file. Omit to use a temporary on-disk file, or set to `:memory:`
    /// for a private in-memory database.
    pub path: Option<PathBuf>,

    #[serde(flatten)]
    shared: RawSharedDatabaseConfig,
}

/// Validated configuration for a SQLite-backed database.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct SqliteDatabaseConfig {
    pub path: Option<PathBuf>,

    #[serde(flatten)]
    pub shared: SharedDatabaseConfig,
}

impl SqliteDatabaseConfig {
    /// Whether `path` is the special `:memory:` sentinel.
    pub fn is_memory(&self) -> bool {
        self.path.as_deref() == Some(Path::new(MEMORY_PATH))
    }
}

impl TryFrom<RawSqliteDatabaseConfig> for SqliteDatabaseConfig {
    type Error = Problems;

    fn try_from(raw: RawSqliteDatabaseConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let shared = raw.shared.validate(&mut problems);

        problems.into_result(Self {
            path: raw.path,
            shared,
        })
    }
}

/// Configuration for a Turso-backed database, a SQLite-compatible file that allows
/// concurrent writers.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "TursoDatabaseConfig")]
pub struct RawTursoDatabaseConfig {
    /// Path to the database file. Omit to use a temporary on-disk file, or set to `:memory:`
    /// for a private in-memory database.
    pub path: Option<PathBuf>,

    /// Put the database in Turso's MVCC journal mode, which is what lets writers overlap.
    ///
    /// This converts the database file and the conversion cannot be undone.
    pub mvcc: Option<bool>,

    #[serde(flatten)]
    shared: RawSharedDatabaseConfig,
}

/// Validated configuration for a Turso-backed database.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct TursoDatabaseConfig {
    pub path: Option<PathBuf>,
    pub mvcc: bool,

    #[serde(flatten)]
    pub shared: SharedDatabaseConfig,
}

impl TursoDatabaseConfig {
    /// Whether `path` is the special `:memory:` sentinel.
    pub fn is_memory(&self) -> bool {
        self.path.as_deref() == Some(Path::new(MEMORY_PATH))
    }
}

impl TryFrom<RawTursoDatabaseConfig> for TursoDatabaseConfig {
    type Error = Problems;

    fn try_from(raw: RawTursoDatabaseConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let shared = raw.shared.validate(&mut problems);

        problems.into_result(Self {
            path: raw.path,
            mvcc: raw.mvcc.unwrap_or(false),
            shared,
        })
    }
}

/// Configuration for a PostgreSQL-backed database.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "PostgresDatabaseConfig")]
pub struct RawPostgresDatabaseConfig {
    /// Host the database server listens on.
    pub host: Option<String>,

    /// Port the database server listens on.
    pub port: Option<u16>,

    /// Name of the database to connect to.
    pub database: Option<String>,

    /// User to authenticate as.
    pub user: Option<String>,

    /// Password to authenticate with.
    pub password: Option<Secret>,

    #[serde(flatten)]
    shared: RawSharedDatabaseConfig,
}

/// Validated configuration for a PostgreSQL-backed database.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct PostgresDatabaseConfig {
    pub host: String,
    pub port: Option<u16>,
    pub database: String,
    pub user: String,
    pub password: Option<Secret>,

    #[serde(flatten)]
    pub shared: SharedDatabaseConfig,
}

impl TryFrom<RawPostgresDatabaseConfig> for PostgresDatabaseConfig {
    type Error = Problems;

    fn try_from(raw: RawPostgresDatabaseConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let mut require = |value: Option<String>, field: &str| -> String {
            match value {
                Some(value) if !value.trim().is_empty() => value,
                Some(_) => {
                    problems.push(Problem::new(field, "must not be blank."));
                    String::new()
                }
                None => {
                    problems.push(Problem::new(field, "field is required."));
                    String::new()
                }
            }
        };

        let host = require(raw.host, "host");
        let database = require(raw.database, "database");
        let user = require(raw.user, "user");
        let shared = raw.shared.validate(&mut problems);

        problems.into_result(Self {
            host,
            port: raw.port,
            database,
            user,
            password: raw.password,
            shared,
        })
    }
}

/// A database configuration, dispatched by the `type` field.
#[derive(Debug, Clone, PartialEq, Deserialize, JsonSchema)]
#[serde(tag = "type", rename_all = "lowercase")]
#[allow(clippy::large_enum_variant)]
pub enum RawDatabaseConfig {
    Sqlite(RawSqliteDatabaseConfig),
    Turso(RawTursoDatabaseConfig),
    Postgres(RawPostgresDatabaseConfig),
}

impl Default for RawDatabaseConfig {
    fn default() -> Self {
        Self::Sqlite(RawSqliteDatabaseConfig::default())
    }
}

/// A validated database configuration, dispatched by the `type` field.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "lowercase")]
#[allow(clippy::large_enum_variant)]
pub enum DatabaseConfig {
    Sqlite(SqliteDatabaseConfig),
    Turso(TursoDatabaseConfig),
    Postgres(PostgresDatabaseConfig),
}

impl Default for DatabaseConfig {
    fn default() -> Self {
        Self::Sqlite(SqliteDatabaseConfig::default())
    }
}

impl TryFrom<RawDatabaseConfig> for DatabaseConfig {
    type Error = Problems;

    fn try_from(raw: RawDatabaseConfig) -> Result<Self, Problems> {
        match raw {
            RawDatabaseConfig::Sqlite(raw) => raw.try_into().map(Self::Sqlite),
            RawDatabaseConfig::Turso(raw) => raw.try_into().map(Self::Turso),
            RawDatabaseConfig::Postgres(raw) => raw.try_into().map(Self::Postgres),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn database_configurations_dispatch_by_type() {
        let raw: RawDatabaseConfig =
            serde_yaml_ng::from_str("type: sqlite\npath: ./local/database.sqlite\n").unwrap();
        let config = DatabaseConfig::try_from(raw).unwrap();

        let DatabaseConfig::Sqlite(sqlite) = config else {
            panic!("expected a SQLite configuration");
        };
        assert_eq!(
            sqlite.path.unwrap(),
            PathBuf::from("./local/database.sqlite")
        );
    }

    #[test]
    fn memory_paths_are_recognized() {
        let config = SqliteDatabaseConfig {
            path: Some(PathBuf::from(MEMORY_PATH)),
            ..SqliteDatabaseConfig::default()
        };
        assert!(config.is_memory());
        assert!(!SqliteDatabaseConfig::default().is_memory());
    }

    #[test]
    fn postgres_requires_its_connection_fields() {
        let raw: RawPostgresDatabaseConfig = serde_yaml_ng::from_str("host: localhost\n").unwrap();
        let problems = PostgresDatabaseConfig::try_from(raw).unwrap_err();
        let locations: Vec<&str> = problems
            .0
            .iter()
            .map(|problem| problem.location.as_str())
            .collect();
        assert_eq!(locations, ["database", "user"]);
    }

    #[test]
    fn passwords_serialize_masked() {
        let raw: RawPostgresDatabaseConfig = serde_yaml_ng::from_str(
            "host: localhost\ndatabase: ceres\nuser: ceres\npassword: hunter2\n",
        )
        .unwrap();
        let config = PostgresDatabaseConfig::try_from(raw).unwrap();

        assert_eq!(config.password.as_ref().unwrap().expose(), "hunter2");
        let serialized = serde_json::to_string(&config).unwrap();
        assert!(!serialized.contains("hunter2"));
        assert!(serialized.contains("**********"));
    }

    #[test]
    fn hashing_configurations_validate_their_parameters() {
        let raw: RawSqliteDatabaseConfig = serde_yaml_ng::from_str(
            "hashing:\n  type: argon2\n  memory_cost: 16\n  parallelism: 4\n",
        )
        .unwrap();
        let problems = SqliteDatabaseConfig::try_from(raw).unwrap_err();
        assert_eq!(problems.0[0].location, "hashing.parallelism");
    }

    #[test]
    fn turso_defaults_to_a_plain_sqlite_file() {
        let raw: RawTursoDatabaseConfig = serde_yaml_ng::from_str("path: ./db\n").unwrap();
        let config = TursoDatabaseConfig::try_from(raw).unwrap();
        assert!(!config.mvcc);
    }
}
