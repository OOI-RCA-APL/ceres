//! Native database access for Ceres entities.
//!
//! This crate owns the connection pools, query building, and row decoding that let entity
//! reads bypass Python entirely. Rows deserialize straight into the `ceres-entities`
//! structs, so a query result is held natively from the driver onward.
//!
//! Every backend sits behind one trait in [`backend`], so the store and the writer are
//! written once against a database rather than three times against three of them.

mod assign;
mod backend;
mod credentials;
mod dynamic;
mod entities;
mod filter;
mod load;
mod records;
mod selector;
mod store;
mod turso;
mod writer;

pub use assign::insert_compiled;
pub use backend::Writing;
pub use ceres_entities::OperationKind;
pub use credentials::{
    Argon2Params, Credentials, Hashing, SPECIAL_USE_DOMAINS, is_password_hash, normalize_email,
    valid_password, verify_argon2, verify_bcrypt,
};
pub use dynamic::{Cell, Row, Table};
pub use entities::EntityTable;
pub use filter::{Arity, EntityFilter, FilterKey, RecordFilter, Refusal, Role, SqlDialect, Window};
pub use load::{
    Conflict, LoadFormat, batches, build, build_entity, entity_batches, read, read_entities,
};
pub use records::RecordTable;
pub use sea_query::Value as BindValue;
pub use store::{Error, GateUser, Parameter, RecordStore};
pub use writer::RecordWriter;
