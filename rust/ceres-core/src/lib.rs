//! The `ceres_core` Python extension module.
//!
//! Exposes the native configuration types to Python. Validation and semantics live in the
//! `ceres-config` crate, this module only carries them across the boundary. The classes
//! integrate with Pydantic on the Python side through thin subclasses in `ceres.config`.
//!
//! Each class is declared once through the `python_config!` macro, which generates the whole
//! binding surface. The type stubs in `ceres/__internal__/core.pyi` are generated from these
//! by the `stub_gen` binary. Regenerate them after changing the module's surface.

pub mod binary;
pub mod connection;
pub mod database;
pub mod entities;
pub mod filters;
pub mod interop;
pub mod logging;
pub mod migrations;
pub mod server;
pub mod store;
pub mod writer;

use std::path::PathBuf;

use ceres_config::{ByteSize, TimeDelta};
use ceres_macros::python_config;
use pyo3::prelude::*;

/// Rust allocations go through mimalloc. The engine process runs for months and the
/// native half's server, store, and row decoding churn allocations constantly so the
/// allocator's fragmentation resistance over long uptimes is what this buys. Python's
/// own allocations are untouched, CPython manages those itself.
#[global_allocator]
static ALLOCATOR: mimalloc::MiMalloc = mimalloc::MiMalloc;

python_config! {
    /// Process-level options applied when running the engine as a system service.
    ServiceConfig(ceres_config::ServiceConfig, ceres_config::RawServiceConfig) {
        /// Service name registered with the operating system.
        name: Option<ceres_config::Name>,
        /// User the service runs as.
        user: Option<ceres_config::Name>,
        /// Optional path to redirect standard output to.
        stdout: Option<PathBuf>,
        /// Optional path to redirect standard error to.
        stderr: Option<PathBuf>,
    }

    /// Branding and layout options for the engine's web console.
    ConsoleConfig(ceres_config::ConsoleConfig, ceres_config::RawConsoleConfig) {
        /// Title shown in the console's browser tab and header.
        title: Option<String>,
        /// Path to a favicon image served by the console.
        favicon: Option<PathBuf>,
    }

    /// TLS configuration for the engine's HTTP server.
    ServerSSLConfig(ceres_config::ServerSslConfig, ceres_config::RawServerSslConfig) {
        /// Path to the server private key file.
        key: Option<PathBuf>,
        /// Password for an encrypted private key.
        key_password: Option<String>,
        /// Path to the server certificate file.
        cert: Option<PathBuf>,
        /// `ssl` protocol constant selecting the TLS version.
        version: Option<i64>,
        /// Path to a CA bundle used when validating client certificates.
        ca_certs: Option<PathBuf>,
    }

    /// Authentication settings for the engine's HTTP server.
    ServerAuthenticationConfig(
        ceres_config::ServerAuthenticationConfig,
        ceres_config::RawServerAuthenticationConfig
    ) {
        /// Secret used to sign and verify authentication tokens.
        secret: String,
        /// Lifetime of an issued authentication token.
        duration: TimeDelta,
        /// Whether an administrator may take on another user's identity without their password.
        allow_impersonate: bool,
    }

    /// Cross-origin resource sharing settings for the engine's HTTP server.
    ServerCORSConfig(ceres_config::ServerCorsConfig, ceres_config::RawServerCorsConfig) {
        /// Whether cross-origin resource sharing is enabled.
        enabled: bool,
        /// Origins allowed to make cross-origin requests.
        #[python(any = "str | list[str]")]
        allow_origins: ceres_config::MaybeSequence<String>,
        /// Pattern matching additional allowed origins.
        allow_origin_regex: Option<String>,
        /// Methods allowed for cross-origin requests.
        #[python(any = "str | list[str]")]
        allow_methods: ceres_config::MaybeSequence<String>,
        /// Headers allowed in cross-origin requests.
        #[python(any = "str | list[str]")]
        allow_headers: ceres_config::MaybeSequence<String>,
        /// Whether credentialed cross-origin requests are allowed.
        allow_credentials: bool,
        /// Headers exposed to cross-origin callers.
        #[python(any = "str | list[str]")]
        expose_headers: ceres_config::MaybeSequence<String>,
        /// How long preflight responses may be cached, in seconds.
        max_age: u64,
    }

    /// Response compression settings for the engine's HTTP server.
    ServerCompressionConfig(
        ceres_config::ServerCompressionConfig,
        ceres_config::RawServerCompressionConfig
    ) {
        /// Whether response compression is enabled.
        enabled: bool,
        /// Minimum response size in bytes before compression is applied.
        min_size: ByteSize,
        /// Whether zstd compression is offered.
        zstd: bool,
        /// Zstd compression level.
        zstd_level: i64,
        /// Whether brotli compression is offered.
        brotli: bool,
        /// Brotli compression quality.
        brotli_quality: i64,
        /// Whether gzip compression is offered.
        gzip: bool,
        /// Gzip compression level.
        gzip_level: i64,
    }

    /// Configuration for the engine's HTTP server.
    ServerConfig(ceres_config::ServerConfig, ceres_config::RawServerConfig) {
        /// Address the server binds to.
        host: String,
        /// Port the server listens on, omit to disable the server.
        port: Option<u16>,
        /// TLS settings, omit to serve plain HTTP.
        #[python(nested = ServerSSLConfig)]
        ssl: Option<ceres_config::ServerSslConfig>,
        /// Authentication settings, omit to disable authentication.
        #[python(nested = ServerAuthenticationConfig)]
        authentication: Option<ceres_config::ServerAuthenticationConfig>,
        /// Cross-origin resource sharing settings.
        #[python(nested = ServerCORSConfig)]
        cors: Option<ceres_config::ServerCorsConfig>,
        /// Response compression settings.
        #[python(nested = ServerCompressionConfig)]
        compression: Option<ceres_config::ServerCompressionConfig>,
    }
}

// The module lands inside the `ceres` package as `ceres.__internal__.core` so its
// initializer has to be named for the last component. The crate keeps the name
// `ceres_core`, which `ceres-stubs` links against.
#[pymodule(name = "core", gil_used = false)]
fn ceres_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<ServiceConfig>()?;
    module.add_class::<ConsoleConfig>()?;
    module.add_class::<ServerSSLConfig>()?;
    module.add_class::<ServerAuthenticationConfig>()?;
    module.add_class::<ServerCORSConfig>()?;
    module.add_class::<ServerCompressionConfig>()?;
    module.add_class::<ServerConfig>()?;
    module.add_class::<logging::LoggingConfig>()?;
    module.add_class::<database::DatabaseConfigHooks>()?;
    module.add_class::<database::BCryptHashingConfig>()?;
    module.add_class::<database::Argon2HashingConfig>()?;
    module.add_class::<database::SQLiteDatabaseConfig>()?;
    module.add_class::<database::TursoDatabaseConfig>()?;
    module.add_class::<database::PostgresDatabaseConfig>()?;
    module.add_class::<binary::PackingProgram>()?;
    module.add_class::<connection::Connection>()?;
    module.add_class::<entities::RecordBatch>()?;
    module.add_class::<entities::RecordTable>()?;
    module.add_class::<entities::EntityTable>()?;
    module.add_class::<filters::NativeFilter>()?;
    module.add_class::<writer::RecordWriter>()?;
    module.add_class::<store::Store>()?;
    module.add_class::<store::RowChunks>()?;
    module.add_class::<migrations::Migration>()?;
    module.add_class::<server::NativeServer>()?;
    module.add_function(pyo3::wrap_pyfunction!(server::openapi_schema, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(filters::insert_compiled, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::stored_columns, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::record_filter_keys, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::entity_filter_keys, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::normalize_email, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::hash_argon2, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::verify_argon2, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::verify_password, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::hash_bcrypt, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::verify_bcrypt, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(writer::special_use_domains, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(migrations::migrations, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(migrations::migration_ddl, module)?)?;
    module.add_function(pyo3::wrap_pyfunction!(
        migrations::destructive_migration_warning,
        module
    )?)?;
    Ok(())
}

/// Gather the stub inventory, reading the packaging from the distribution this ships in.
///
/// `define_stub_info_gatherer!` looks for a `pyproject.toml` beside `Cargo.toml`, which is
/// where a standalone extension package keeps its own. This module ships inside the `ceres`
/// distribution instead so the packaging that names it lives at the repository root and
/// there is no manifest beside the crate to find.
pub fn stub_info() -> pyo3_stub_gen::Result<pyo3_stub_gen::StubInfo> {
    let manifest: &std::path::Path = env!("CARGO_MANIFEST_DIR").as_ref();
    pyo3_stub_gen::StubInfo::from_pyproject_toml(manifest.join("../../pyproject.toml"))
}
