//! Ceres database entities.
//!
//! This crate owns the native representation of the entities Ceres persists and serves.
//! Entities are held as these structs through the whole read path, and only materialize
//! into Python objects when user code needs them. Serialization here defines the API wire
//! format, byte for byte.

// Let the filter derives name this crate by its external name from within.
extern crate self as ceres_entities;

mod address;
mod entities;
mod filterable;
mod records;
mod timestamp;

pub use address::Address;
pub use ceres_config::Level;
pub use entities::{
    ComponentAccessLevel, Entities, Group, GroupMembership, GroupPermission, PermissionTargetType,
    Setting, User, UserPermission, Variable, Workspace, WorkspaceEdit,
};
pub use filterable::{
    FieldFamily, FieldOperation, FilterField, FilterValues, Filterable, OperationKind,
};
pub use records::{
    Alert, CsvRecord, LogEntry, Message, MessageDirection, Particle, Records, latin1, to_json_array,
};
pub use timestamp::Timestamp;
