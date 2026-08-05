//! Ceres database entities.
//!
//! This crate owns the native representation of the entities Ceres persists and serves.
//! Entities are held as these structs through the whole read path, and only materialize
//! into Python objects when user code needs them. Serialization here defines the API wire
//! format, byte for byte.

// Let the filter derives name this crate by its external name from within.
extern crate self as ceres_entities;

mod address;
mod filterable;
// `records` declares the `RenderRows` trait, and `enum_dispatch` writes each batch
// enum's implementation of it wherever the later of the two expands, spelling the
// payload types the way the enum did. Declaring `records` first expands the trait
// first, so the `Entities` implementation lands in `entities`, where those names
// resolve.
mod entities;
mod records;
mod timestamp;

pub use address::Address;
pub use ceres_config::Level;
pub use entities::{
    Entities, GrantLevel, Group, GroupMembership, GroupPermission, PermissionTargetType, Setting,
    User, UserPermission, Variable, Workspace, WorkspaceEdit,
};
pub use filterable::{
    FieldFamily, FieldOperation, FilterField, FilterValues, Filterable, OperationKind,
};
pub use records::{
    Alert, LogEntry, Message, MessageDirection, Particle, Records, RenderRows, latin1,
};
pub use timestamp::Timestamp;
