//! Ceres project configuration.
//!
//! This crate owns the engine-level configuration schema, the sections of `ceres.yaml` that
//! configure the engine itself rather than user components. Each section is a validated type
//! whose semantics live here and nowhere else. The `ceres-core` extension module exposes the
//! same types to Python, so both halves of the system share one implementation.
//!
//! Sections not yet ported (`server`, `database`, `logging`) parse leniently into raw values
//! and validate where they are consumed. The component tree always passes through untouched,
//! because its schema is defined by user code.

mod error;
mod meta;
mod types;

pub use error::{Problem, Problems};
pub use meta::{ConfigMeta, ServerConfig};
pub use types::{
    ConsoleConfig, NAME_PATTERN, Name, RawConsoleConfig, RawServiceConfig, ServiceConfig,
};
