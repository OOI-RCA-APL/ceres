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
mod state;
mod types;
mod values;

pub use database::{
    Argon2HashingConfig, BcryptHashingConfig, DatabaseConfig, DatabaseConfigHooks, HashingConfig,
    PostgresDatabaseConfig, RawArgon2HashingConfig, RawBcryptHashingConfig, RawDatabaseConfig,
    RawDatabaseConfigHooks, RawHashingConfig, RawPostgresDatabaseConfig, RawSharedDatabaseConfig,
    RawSqliteDatabaseConfig, RawTursoDatabaseConfig, SharedDatabaseConfig, SqliteDatabaseConfig,
    TursoDatabaseConfig, resolve_path,
};
pub use error::{Problem, Problems};
pub use logging::{Level, LogToggle, LoggingConfig, RawLoggingConfig};
pub use meta::ConfigMeta;
pub use server::{
    DEFAULT_CERTIFICATE_DAYS, DEFAULT_TLS_CA_CERT, DEFAULT_TLS_CA_KEY, DEFAULT_TLS_CERT,
    DEFAULT_TLS_KEY, MAX_CERTIFICATE_DAYS, RawServerAuthenticationConfig,
    RawServerCertificateAuthorityConfig, RawServerCertificateAutoConfig,
    RawServerCertificateConfig, RawServerCompressionConfig, RawServerConfig, RawServerCorsConfig,
    RawServerHttpConfig, RawServerHttpsConfig, ServerAuthenticationConfig,
    ServerCertificateAuthorityConfig, ServerCertificateAutoConfig, ServerCertificateConfig,
    ServerCompressionConfig, ServerConfig, ServerCorsConfig, ServerHttpConfig, ServerHttpsConfig,
    TlsVersion,
};
pub use state::{STATE_DIRECTORY, create_parent_directory, create_state_directory};
pub use types::{
    ConsoleConfig, NAME_PATTERN, Name, RawConsoleConfig, RawServiceConfig, ServiceConfig,
};
pub use values::{ByteSize, MaybeSequence, Secret, TimeDelta};
