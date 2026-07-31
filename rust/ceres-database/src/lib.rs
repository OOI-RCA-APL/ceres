//! Native database access for Ceres entities.
//!
//! This crate owns the connection pools, query building, and row decoding that let entity
//! reads bypass Python entirely. Rows deserialize straight into the `ceres-entities`
//! structs, so a query result is held natively from the driver onward.
//!
//! Query semantics deliberately mirror the SQLAlchemy layer they replace, the SQL built
//! here has to select and order exactly like the Python side does for the same filter.

mod assign;
mod entities;
mod filter;
mod load;
mod records;
mod selector;
mod store;
mod turso;
mod writer;

pub use entities::EntityTable;
pub use filter::{EntityFilter, RecordFilter, Refusal, SqlDialect};
pub use load::{Conflict, LoadFormat, build, build_entity, read, read_entities};
pub use records::RecordTable;
pub use sea_query::Value as BindValue;
pub use store::{Error, GateUser, Parameter, RecordStore};
pub use writer::RecordWriter;
