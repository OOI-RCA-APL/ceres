//! Ceres database entities.
//!
//! This crate owns the native representation of the entities Ceres persists and serves.
//! Entities are held as these structs through the whole read path, and only materialize
//! into Python objects when user code needs them. Serialization here defines the API wire
//! format, byte for byte.

mod address;
mod records;
mod timestamp;

pub use address::Address;
pub use ceres_config::Level;
pub use records::{
    Alert, LogEntry, Message, MessageDirection, Particle, Records, latin1, to_json_array,
};
pub use timestamp::Timestamp;
