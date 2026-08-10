//! Rows read without knowing the table.
//!
//! The typed decoders in `records` and `entities` know what shape a table holds and
//! build the struct for it. This decodes by column instead, reading whatever a statement
//! returned, which a query layer needs when it compiles its own statement and a
//! migration needs when it runs SQL that belongs to no table at all.
//!
//! A cell carries the value in the form the column stores it so a caller sees the same
//! value on every backend even though SQLite keeps a UUID as text and PostgreSQL keeps it
//! as a UUID. The column's declared type decides, rather than the value's runtime shape
//! because a stored value alone cannot say whether text is a timestamp or a name.

use ceres_entities::{FieldFamily, FilterField};
use chrono::NaiveDateTime;
use serde_json::Value;
use sqlx::{Column, Row as _, TypeInfo, ValueRef};
use uuid::Uuid;

use crate::entities::EntityTable;
use crate::records::RecordTable;
use crate::store::Error;

/// One of the tables the managers serve, whichever half of the split it falls in.
///
/// The record tables and the entity tables are separate everywhere they are queried
/// because their filters compile from different schemas. They are the same thing to a
/// caller that only wants to know what a column holds, which this is for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Table {
    Record(RecordTable),
    Entity(EntityTable),
}

impl Table {
    /// Select a table by name, across both halves.
    ///
    /// The two name sets are disjoint so a name identifies one table and the caller
    /// does not have to know which half it came from.
    pub fn parse(name: &str) -> Option<Self> {
        if let Ok(table) = RecordTable::parse(name) {
            return Some(Self::Record(table));
        }

        EntityTable::parse(name).ok().map(Self::Entity)
    }

    /// Every column the table stores, with the family that decides how it decodes.
    pub fn columns(&self) -> &'static [FilterField] {
        match self {
            Self::Record(table) => table.columns(),
            Self::Entity(table) => table.columns(),
        }
    }

    /// The table's whole schema, which a write encodes and narrows against.
    pub(crate) fn schema(&self) -> crate::records::Schema {
        match self {
            Self::Record(table) => table.schema(),
            Self::Entity(table) => table.schema(),
        }
    }

    /// The family a named column belongs to, `None` for one the table does not declare.
    fn family(&self, column: &str) -> Option<FieldFamily> {
        self.columns()
            .iter()
            .find(|field| field.key == column)
            .map(|field| field.family)
    }
}

/// One column's value, in the form the column declared rather than the driver's.
#[derive(Clone, Debug, PartialEq)]
pub enum Cell {
    Null,
    Bool(bool),
    Integer(i64),
    Float(f64),
    Text(String),
    Bytes(Vec<u8>),
    /// A UTC instant, which both families store without an offset.
    Timestamp(NaiveDateTime),
    Uuid(Uuid),
    Json(Value),
}

/// One row, its columns in the order the statement selected them.
pub type Row = Vec<(String, Cell)>;

/// Decode a SQLite row, the named table's columns deciding what its values hold.
///
/// SQLite keeps a UUID and a timestamp both as text, and the driver reports the storage
/// class rather than the declared type so text alone cannot say which of the three a
/// column is. The table says instead. A statement that names no table, as a
/// migration runs, reads every value as the class it is stored in.
pub fn sqlite_row(row: &sqlx::sqlite::SqliteRow, table: Option<Table>) -> Result<Row, Error> {
    let mut cells = Row::with_capacity(row.columns().len());
    for column in row.columns() {
        let index = column.ordinal();
        let raw = row.try_get_raw(index)?;
        if raw.is_null() {
            cells.push((column.name().to_string(), Cell::Null));
            continue;
        }

        let family = table.and_then(|table| table.family(column.name()));
        let cell = match family {
            Some(FieldFamily::Uuid) => uuid_cell(&row.try_get::<String, _>(index)?)?,
            Some(FieldFamily::Timestamp) => timestamp_cell(&row.try_get::<String, _>(index)?)?,
            Some(FieldFamily::Json | FieldFamily::JsonValue) => json_cell(row, index)?,
            Some(FieldFamily::Bytes) => Cell::Bytes(row.try_get(index)?),
            Some(FieldFamily::Boolean) => Cell::Bool(row.try_get::<i64, _>(index)? != 0),
            Some(
                FieldFamily::Text
                | FieldFamily::Email
                | FieldFamily::Address
                | FieldFamily::PlainAddress
                | FieldFamily::Level
                | FieldFamily::Values(_),
            ) => Cell::Text(row.try_get(index)?),
            None => untyped(row, index)?,
        };
        cells.push((column.name().to_string(), cell));
    }

    Ok(cells)
}

/// Decode a PostgreSQL row, whose column types the server reports exactly.
pub fn postgres_row(row: &sqlx::postgres::PgRow) -> Result<Row, Error> {
    let mut cells = Row::with_capacity(row.columns().len());
    for column in row.columns() {
        let index = column.ordinal();
        let raw = row.try_get_raw(index)?;
        if raw.is_null() {
            cells.push((column.name().to_string(), Cell::Null));
            continue;
        }

        let cell = match column.type_info().name().to_ascii_uppercase().as_str() {
            "BOOL" => Cell::Bool(row.try_get(index)?),
            // Each width decodes as itself and widens here. Asking for an `i64` from an
            // `INT4` is a decode error rather than a widening so a narrower column, which
            // is what `SELECT 1` and most of the catalog produce, would otherwise fail.
            "INT2" => Cell::Integer(row.try_get::<i16, _>(index)?.into()),
            "INT4" => Cell::Integer(row.try_get::<i32, _>(index)?.into()),
            "INT8" => Cell::Integer(row.try_get(index)?),
            "FLOAT4" => Cell::Float(row.try_get::<f32, _>(index)?.into()),
            "FLOAT8" | "NUMERIC" => Cell::Float(row.try_get(index)?),
            "BYTEA" => Cell::Bytes(row.try_get(index)?),
            "UUID" => Cell::Uuid(row.try_get(index)?),
            "TIMESTAMPTZ" => Cell::Timestamp(
                row.try_get::<chrono::DateTime<chrono::Utc>, _>(index)?
                    .naive_utc(),
            ),
            "TIMESTAMP" => Cell::Timestamp(row.try_get(index)?),
            "JSON" | "JSONB" => Cell::Json(row.try_get(index)?),
            _ => Cell::Text(row.try_get(index)?),
        };
        cells.push((column.name().to_string(), cell));
    }

    Ok(cells)
}

/// Decode a Turso row, which holds the SQLite storage classes without declared types.
///
/// The engine reports no schema type for a column so a value crosses as what it is. The
/// caller knows which of its columns hold UUIDs and timestamps, and reads the text form
/// the SQLite family stores either as.
pub fn turso_row(row: &turso::Row, names: &[String], table: Option<Table>) -> Result<Row, Error> {
    let mut cells = Row::with_capacity(names.len());
    for (index, name) in names.iter().enumerate() {
        let held = row.get_value(index)?;
        let family = table.and_then(|table| table.family(name));
        let cell = match (&held, family) {
            (turso::Value::Null, _) => Cell::Null,
            (turso::Value::Text(text), Some(FieldFamily::Uuid)) => uuid_cell(text)?,
            (turso::Value::Text(text), Some(FieldFamily::Timestamp)) => timestamp_cell(text)?,
            (turso::Value::Text(text), Some(FieldFamily::Json | FieldFamily::JsonValue)) => {
                serde_json::from_str(text)
                    .map(Cell::Json)
                    .map_err(|error| Error::Decode(format!("{text:?} is not JSON. {error}")))?
            }
            // The storage class is NUMERIC on a JSON column so a stored number comes
            // back as one rather than as the text it was written as.
            (turso::Value::Integer(held), Some(FieldFamily::Json | FieldFamily::JsonValue)) => {
                Cell::Json((*held).into())
            }
            (turso::Value::Integer(held), Some(FieldFamily::Boolean)) => Cell::Bool(*held != 0),
            (turso::Value::Integer(held), _) => Cell::Integer(*held),
            (turso::Value::Real(held), _) => Cell::Float(*held),
            (turso::Value::Text(text), _) => Cell::Text(text.clone()),
            (turso::Value::Blob(bytes), _) => Cell::Bytes(bytes.clone()),
        };
        cells.push((name.clone(), cell));
    }

    Ok(cells)
}

/// A UUID cell from its stored text, which the SQLite family keeps hyphenated.
fn uuid_cell(text: &str) -> Result<Cell, Error> {
    text.parse()
        .map(Cell::Uuid)
        .map_err(|_| Error::Decode(format!("{text:?} is not a UUID")))
}

/// A timestamp cell from its stored text, in the form the query layer writes.
fn timestamp_cell(text: &str) -> Result<Cell, Error> {
    NaiveDateTime::parse_from_str(text, "%Y-%m-%d %H:%M:%S%.f")
        .map(Cell::Timestamp)
        .map_err(|_| Error::Decode(format!("{text:?} is not a timestamp")))
}

/// A JSON cell from a SQLite column, which holds its text unless the value was a number.
///
/// The `JSON` declaration carries none of SQLite's affinity keywords and so takes NUMERIC
/// affinity, which converts anything that looks like a number back into one. Both forms
/// decode to the value that was written.
fn json_cell(row: &sqlx::sqlite::SqliteRow, index: usize) -> Result<Cell, Error> {
    if let Ok(text) = row.try_get::<String, _>(index) {
        return serde_json::from_str(&text)
            .map(Cell::Json)
            .map_err(|error| Error::Decode(format!("{text:?} is not JSON. {error}")));
    }

    if let Ok(number) = row.try_get::<i64, _>(index) {
        return Ok(Cell::Json(number.into()));
    }

    let number: f64 = row.try_get(index)?;
    serde_json::Number::from_f64(number)
        .map(|number| Cell::Json(Value::Number(number)))
        .ok_or_else(|| Error::Decode(format!("{number} is not a JSON number")))
}

/// A cell from a column whose declared type names nothing in particular.
///
/// A migration and an ad hoc statement both select expressions rather than columns, so
/// the value's own storage class decides. The order is the one SQLite orders its classes
/// in so an integer never reads as the text of itself.
fn untyped(row: &sqlx::sqlite::SqliteRow, index: usize) -> Result<Cell, Error> {
    if let Ok(value) = row.try_get::<i64, _>(index) {
        return Ok(Cell::Integer(value));
    }

    if let Ok(value) = row.try_get::<f64, _>(index) {
        return Ok(Cell::Float(value));
    }

    if let Ok(value) = row.try_get::<String, _>(index) {
        return Ok(Cell::Text(value));
    }

    Ok(Cell::Bytes(row.try_get(index)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tables_resolve_across_both_halves() {
        assert_eq!(
            Table::parse("messages"),
            Some(Table::Record(RecordTable::Messages))
        );
        assert_eq!(
            Table::parse("group_permissions"),
            Some(Table::Entity(EntityTable::GroupPermissions))
        );
        assert_eq!(Table::parse("migrations"), None);
    }

    #[test]
    fn a_column_carries_the_family_that_decodes_it() {
        let table = Table::parse("messages").expect("the messages table");
        assert_eq!(table.family("id"), Some(FieldFamily::Uuid));
        assert_eq!(table.family("timestamp"), Some(FieldFamily::Timestamp));
        assert_eq!(table.family("data"), Some(FieldFamily::Bytes));
        // A column the table does not declare has no family so its value reads as
        // whatever it is stored as.
        assert_eq!(table.family("total"), None);
    }

    #[test]
    fn a_skipped_column_still_decodes() {
        // A user's password hash is not filterable, but a row still carries it so the
        // column list has to hold what the filter surface does not.
        let table = Table::parse("users").expect("the users table");
        assert_eq!(table.family("password"), Some(FieldFamily::Text));
        assert_eq!(table.family("admin"), Some(FieldFamily::Boolean));
    }
}
