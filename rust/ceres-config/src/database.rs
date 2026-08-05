//! The database configuration section.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::values::{MaybeSequence, Secret};

/// The path SQLite reads as a request for a private in-memory database.
///
/// Nothing here opens one. A private in-memory database lives inside the single connection
/// that opened it, so nothing else in the process can join it, and the native store owns
/// its own connections. Rejecting the path is what keeps that from reading as a database
/// file literally named `:memory:`, which is what a bare path would otherwise create.
const MEMORY_PATH: &str = ":memory:";

/// Resolve a configured database path against the directory holding the configuration.
///
/// A relative path in `ceres.yaml` names a file beside that configuration, not one beside
/// whatever directory a command happened to run from. Those are usually the same place,
/// which is why the difference only surfaces with `--config` naming a project elsewhere,
/// and that is exactly when getting it wrong creates an empty database in the wrong
/// directory instead of reporting that it could not find the real one.
///
/// An absolute path is returned unchanged, because joining onto one discards the prefix.
pub fn resolve_path(path: &Path, directory: &Path) -> PathBuf {
    directory.join(path)
}

/// Reject the in-memory path, which no backend opens.
fn validate_path(path: Option<&Path>, problems: &mut Problems) {
    if path == Some(Path::new(MEMORY_PATH)) {
        problems.push(Problem::new(
            "path",
            "must name a file. Omit it for a temporary on-disk database.",
        ));
    }
}

/// SQL statements executed at well-known points in the database lifecycle.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "DatabaseConfigHooks")]
pub struct RawDatabaseConfigHooks {
    /// Statements run once when the database is first created.
    pub init: Option<Vec<String>>,

    /// Statements run on every new connection.
    pub connect: Option<Vec<String>>,

    /// Statements run before a connection is closed.
    pub close: Option<Vec<String>>,
}

/// Validated SQL statements executed at well-known points in the database lifecycle.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct DatabaseConfigHooks {
    pub init: Option<Vec<String>>,
    pub connect: Option<Vec<String>>,
    pub close: Option<Vec<String>>,
}

impl TryFrom<RawDatabaseConfigHooks> for DatabaseConfigHooks {
    type Error = Problems;

    fn try_from(raw: RawDatabaseConfigHooks) -> Result<Self, Problems> {
        Ok(Self {
            init: raw.init,
            connect: raw.connect,
            close: raw.close,
        })
    }
}

/// Configuration for the bcrypt password hashing algorithm.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "BCryptHashingConfig")]
pub struct RawBcryptHashingConfig {
    /// Cost factor controlling how expensive each hash is to compute.
    pub rounds: Option<i64>,
}

/// Validated configuration for the bcrypt password hashing algorithm.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BcryptHashingConfig {
    pub rounds: i64,
}

impl Default for BcryptHashingConfig {
    fn default() -> Self {
        Self { rounds: 12 }
    }
}

impl TryFrom<RawBcryptHashingConfig> for BcryptHashingConfig {
    type Error = Problems;

    fn try_from(raw: RawBcryptHashingConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        let config = Self {
            rounds: raw.rounds.unwrap_or(defaults.rounds),
        };

        let mut problems = Problems::default();
        if config.rounds < 4 {
            problems.push(Problem::new("rounds", "must be at least 4."));
        }

        problems.into_result(config)
    }
}

/// Configuration for the Argon2id password hashing algorithm.
///
/// Default parameters mirror `argon2.profiles.RFC_9106_LOW_MEMORY`, callers can tune them to
/// trade memory and CPU cost against latency.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "Argon2HashingConfig")]
pub struct RawArgon2HashingConfig {
    /// Number of iterations Argon2 performs.
    pub time_cost: Option<i64>,

    /// Memory budget in KiB.
    pub memory_cost: Option<i64>,

    /// Number of parallel lanes used during hashing.
    pub parallelism: Option<i64>,

    /// Length of the produced hash in bytes.
    pub hash_length: Option<i64>,

    /// Length of the random salt in bytes.
    pub salt_length: Option<i64>,
}

/// Validated configuration for the Argon2id password hashing algorithm.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Argon2HashingConfig {
    pub time_cost: i64,
    pub memory_cost: i64,
    pub parallelism: i64,
    pub hash_length: i64,
    pub salt_length: i64,
}

impl Default for Argon2HashingConfig {
    fn default() -> Self {
        Self {
            time_cost: 3,
            // The default is 64 MiB.
            memory_cost: 65536,
            parallelism: 4,
            // The true allowed range is 4-32768.
            hash_length: 32,
            // The true allowed range is 8-4096.
            salt_length: 16,
        }
    }
}

impl TryFrom<RawArgon2HashingConfig> for Argon2HashingConfig {
    type Error = Problems;

    fn try_from(raw: RawArgon2HashingConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        let config = Self {
            time_cost: raw.time_cost.unwrap_or(defaults.time_cost),
            memory_cost: raw.memory_cost.unwrap_or(defaults.memory_cost),
            parallelism: raw.parallelism.unwrap_or(defaults.parallelism),
            hash_length: raw.hash_length.unwrap_or(defaults.hash_length),
            salt_length: raw.salt_length.unwrap_or(defaults.salt_length),
        };

        let mut problems = Problems::default();
        if config.time_cost < 1 {
            problems.push(Problem::new("time_cost", "must be positive."));
        }

        if config.memory_cost < 8 {
            problems.push(Problem::new("memory_cost", "must be at least 8."));
        }

        if config.parallelism < 1 {
            problems.push(Problem::new("parallelism", "must be positive."));
        } else if config.memory_cost / config.parallelism < 8 {
            problems.push(Problem::new(
                "parallelism",
                "must be at least 8 times smaller than memory_cost.",
            ));
        }

        if !(4..=256).contains(&config.hash_length) {
            problems.push(Problem::new("hash_length", "must be between 4 and 256."));
        }

        if !(8..=64).contains(&config.salt_length) {
            problems.push(Problem::new("salt_length", "must be between 8 and 64."));
        }

        problems.into_result(config)
    }
}

/// A password hashing configuration, dispatched by the `type` field.
#[derive(Debug, Clone, PartialEq, Deserialize, JsonSchema)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum RawHashingConfig {
    Bcrypt(RawBcryptHashingConfig),
    Argon2(RawArgon2HashingConfig),
}

impl Default for RawHashingConfig {
    fn default() -> Self {
        Self::Argon2(RawArgon2HashingConfig::default())
    }
}

/// A validated password hashing configuration, dispatched by the `type` field.
#[derive(Debug, Clone, PartialEq, Serialize)]
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

impl TryFrom<RawHashingConfig> for HashingConfig {
    type Error = Problems;

    fn try_from(raw: RawHashingConfig) -> Result<Self, Problems> {
        match raw {
            RawHashingConfig::Bcrypt(raw) => raw.try_into().map(Self::Bcrypt),
            RawHashingConfig::Argon2(raw) => raw.try_into().map(Self::Argon2),
        }
    }
}

/// The settings shared by every database backend.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
pub struct RawSharedDatabaseConfig {
    pub hooks: Option<RawDatabaseConfigHooks>,

    /// Extra keyword arguments forwarded to the SQLAlchemy engine factory.
    ///
    /// Values must be JSON-compatible. Anything richer than that belongs in code rather than
    /// in configuration.
    pub engine: Option<serde_json::Map<String, serde_json::Value>>,

    /// Password hashing configuration used for users stored in this database.
    pub hashing: Option<RawHashingConfig>,

    /// Optional database-specific connection string query parameters.
    pub query: Option<BTreeMap<String, MaybeSequence<String>>>,
}

/// The validated settings shared by every database backend.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct SharedDatabaseConfig {
    pub hooks: DatabaseConfigHooks,
    pub engine: serde_json::Map<String, serde_json::Value>,
    pub hashing: HashingConfig,
    pub query: Option<BTreeMap<String, MaybeSequence<String>>>,
}

impl RawSharedDatabaseConfig {
    fn validate(self, problems: &mut Problems) -> SharedDatabaseConfig {
        let hashing = match self.hashing.unwrap_or_default().try_into() {
            Ok(hashing) => hashing,
            Err(hashing_problems) => {
                problems.absorb(hashing_problems, "hashing");
                HashingConfig::default()
            }
        };

        SharedDatabaseConfig {
            hooks: self
                .hooks
                .map(|hooks| hooks.try_into().expect("hook validation cannot fail"))
                .unwrap_or_default(),
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
    /// Path to the SQLite file. Omit to use a temporary on-disk file.
    pub path: Option<PathBuf>,

    #[serde(flatten)]
    pub shared: RawSharedDatabaseConfig,
}

/// Validated configuration for a SQLite-backed database.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct SqliteDatabaseConfig {
    pub path: Option<PathBuf>,

    #[serde(flatten)]
    pub shared: SharedDatabaseConfig,
}

impl TryFrom<RawSqliteDatabaseConfig> for SqliteDatabaseConfig {
    type Error = Problems;

    fn try_from(raw: RawSqliteDatabaseConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let shared = raw.shared.validate(&mut problems);
        validate_path(raw.path.as_deref(), &mut problems);

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
    /// Path to the database file. Omit to use a temporary on-disk file.
    pub path: Option<PathBuf>,

    /// Put the database in Turso's MVCC journal mode, which is what lets writers overlap.
    ///
    /// This converts the database file and the conversion cannot be undone.
    pub mvcc: Option<bool>,

    #[serde(flatten)]
    pub shared: RawSharedDatabaseConfig,
}

/// Validated configuration for a Turso-backed database.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct TursoDatabaseConfig {
    pub path: Option<PathBuf>,
    pub mvcc: bool,

    #[serde(flatten)]
    pub shared: SharedDatabaseConfig,
}

impl TryFrom<RawTursoDatabaseConfig> for TursoDatabaseConfig {
    type Error = Problems;

    fn try_from(raw: RawTursoDatabaseConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let shared = raw.shared.validate(&mut problems);
        validate_path(raw.path.as_deref(), &mut problems);

        problems.into_result(Self {
            path: raw.path,
            mvcc: raw.mvcc.unwrap_or(false),
            shared,
        })
    }
}

/// A Turso configuration is a SQLite configuration, the settings SQLite understands carry
/// over unchanged.
impl From<&TursoDatabaseConfig> for SqliteDatabaseConfig {
    fn from(config: &TursoDatabaseConfig) -> Self {
        Self {
            path: config.path.clone(),
            shared: config.shared.clone(),
        }
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
    pub shared: RawSharedDatabaseConfig,
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
        let blank = |value: &str| value.trim().is_empty();
        let host = problems.require(raw.host, "host", blank, "must not be blank.");
        let database = problems.require(raw.database, "database", blank, "must not be blank.");
        let user = problems.require(raw.user, "user", blank, "must not be blank.");
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

impl DatabaseConfig {
    /// The settings every backend carries, whichever one this is.
    pub fn shared(&self) -> &SharedDatabaseConfig {
        match self {
            Self::Sqlite(config) => &config.shared,
            Self::Turso(config) => &config.shared,
            Self::Postgres(config) => &config.shared,
        }
    }
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
    fn a_relative_database_path_lands_beside_its_configuration() {
        let resolved = resolve_path(
            Path::new("./local/database.sqlite"),
            Path::new("/projects/reef"),
        );

        assert_eq!(
            resolved,
            PathBuf::from("/projects/reef/./local/database.sqlite")
        );
        // What matters is the directory it lands in, whatever the join leaves in the
        // middle, because that is what decides which file gets opened.
        assert!(resolved.starts_with("/projects/reef"));
    }

    #[test]
    fn an_absolute_database_path_ignores_the_configuration_directory() {
        assert_eq!(
            resolve_path(
                Path::new("/var/lib/ceres.sqlite"),
                Path::new("/projects/reef")
            ),
            PathBuf::from("/var/lib/ceres.sqlite")
        );
    }

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
    fn the_in_memory_path_is_refused_rather_than_taken_literally() {
        // Left alone it would name a file called ":memory:", which reads as a working
        // database right up until someone looks for the data somewhere else.
        for text in [
            "type: sqlite\npath: ':memory:'\n",
            "type: turso\npath: ':memory:'\n",
        ] {
            let raw: RawDatabaseConfig = serde_yaml_ng::from_str(text).unwrap();
            let problems = DatabaseConfig::try_from(raw).expect_err("the path is refused");
            assert!(
                format!("{problems}").contains("must name a file"),
                "{problems}"
            );
        }

        // A temporary on-disk database is what an omitted path already gives.
        let raw: RawDatabaseConfig = serde_yaml_ng::from_str("type: sqlite\n").unwrap();
        DatabaseConfig::try_from(raw).expect("an omitted path is fine");
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
    fn hashing_configurations_fill_their_defaults() {
        let raw: RawHashingConfig = serde_yaml_ng::from_str("type: bcrypt\n").unwrap();
        let config = HashingConfig::try_from(raw).unwrap();
        assert_eq!(
            config,
            HashingConfig::Bcrypt(BcryptHashingConfig::default())
        );
    }

    #[test]
    fn database_configurations_serialize_with_their_type() {
        let config = DatabaseConfig::default();
        let serialized = serde_json::to_value(&config).unwrap();
        assert_eq!(serialized["type"], "sqlite");
        assert_eq!(serialized["hashing"]["type"], "argon2");
    }

    #[test]
    fn turso_defaults_to_a_plain_sqlite_file() {
        let raw: RawTursoDatabaseConfig = serde_yaml_ng::from_str("path: ./db\n").unwrap();
        let config = TursoDatabaseConfig::try_from(raw).unwrap();
        assert!(!config.mvcc);
    }
}
