//! Ceres project configuration.
//!
//! This crate owns the engine-level configuration schema, the sections of `ceres.yaml` that
//! configure the engine itself rather than user components. Each section is a validated type
//! whose semantics live here and nowhere else. The `ceres-core` extension module exposes the
//! same types to Python, so both halves of the system share one implementation.
//!
//! The component tree always passes through untouched, because its schema is defined by
//! user code.

mod database;
mod error;
mod logging;
mod meta;
mod server;
mod types;
mod values;

pub use database::{
    Argon2HashingConfig, BcryptHashingConfig, DatabaseConfig, DatabaseConfigHooks, HashingConfig,
    PostgresDatabaseConfig, RawArgon2HashingConfig, RawBcryptHashingConfig, RawDatabaseConfig,
    RawDatabaseConfigHooks, RawHashingConfig, RawPostgresDatabaseConfig, RawSharedDatabaseConfig,
    RawSqliteDatabaseConfig, RawTursoDatabaseConfig, SharedDatabaseConfig, SqliteDatabaseConfig,
    TursoDatabaseConfig,
};
pub use error::{Problem, Problems};
pub use logging::{Level, LogToggle, LoggingConfig, RawLoggingConfig};
pub use meta::ConfigMeta;
pub use server::{
    RawServerAuthenticationConfig, RawServerCompressionConfig, RawServerConfig,
    RawServerCorsConfig, RawServerSslConfig, ServerAuthenticationConfig, ServerCompressionConfig,
    ServerConfig, ServerCorsConfig, ServerSslConfig, TLS_SERVER_PROTOCOL,
};
pub use types::{
    ConsoleConfig, NAME_PATTERN, Name, RawConsoleConfig, RawServiceConfig, ServiceConfig,
};
pub use values::{ByteSize, MaybeSequence, Secret, TimeDelta};
