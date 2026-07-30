//! Native database access for Ceres entities.
//!
//! This crate owns the connection pools, query building, and row decoding that let entity
//! reads bypass Python entirely. Rows deserialize straight into the `ceres-entities`
//! structs, so a query result is held natively from the driver onward.
//!
//! Query semantics deliberately mirror the SQLAlchemy layer they replace, the SQL built
//! here has to select and order exactly like the Python side does for the same filter.

mod filter;
mod records;
mod store;
mod turso;
mod writer;

pub use filter::{RecordFilter, SqlDialect};
pub use records::RecordTable;
pub use store::{Error, Parameter, RecordStore};
pub use writer::RecordWriter;
