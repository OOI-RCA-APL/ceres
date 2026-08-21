//! Binding sea-query's values to sqlx's arguments.
//!
//! sea-query renders a statement to SQL text and a list of values, and sqlx wants those values
//! as its own driver-specific arguments. This is the join between them, for the two sqlx
//! backends. Turso takes the same values through [`crate::turso::sea_value`] instead, its driver
//! holding a value type of its own rather than sqlx arguments.
//!
//! Each match is exhaustive over the value kinds this workspace's features admit, so a kind
//! sea-query adds later fails the build here rather than binding wrongly at run time.

use sea_query::query::{DeleteStatement, InsertStatement, SelectStatement, UpdateStatement};
use sea_query::{QueryBuilder, Value, Values};
use sqlx::Arguments;

/// One statement's bound values, ready to become a driver's arguments.
pub(crate) struct SqlxValues(pub(crate) Values);

/// Render a statement to SQL text and the values bound into it.
pub(crate) trait SqlxBinder {
    fn build_sqlx<T: QueryBuilder>(&self, builder: T) -> (String, SqlxValues);
}

macro_rules! impl_binder {
    ($statement:ident) => {
        impl SqlxBinder for $statement {
            fn build_sqlx<T: QueryBuilder>(&self, builder: T) -> (String, SqlxValues) {
                let (sql, values) = self.build(builder);
                (sql, SqlxValues(values))
            }
        }
    };
}

impl_binder!(SelectStatement);
impl_binder!(UpdateStatement);
impl_binder!(InsertStatement);
impl_binder!(DeleteStatement);

impl sqlx::IntoArguments<sqlx::postgres::Postgres> for SqlxValues {
    fn into_arguments(self) -> sqlx::postgres::PgArguments {
        let mut arguments = sqlx::postgres::PgArguments::default();
        for value in self.0.into_iter() {
            match value {
                Value::Bool(held) => {
                    let _ = arguments.add(held);
                }
                Value::TinyInt(held) => {
                    let _ = arguments.add(held);
                }
                Value::SmallInt(held) => {
                    let _ = arguments.add(held);
                }
                Value::Int(held) => {
                    let _ = arguments.add(held);
                }
                Value::BigInt(held) => {
                    let _ = arguments.add(held);
                }
                // PostgreSQL has no unsigned integers, so each widens into the signed type that
                // holds it, and the widest is checked rather than wrapping into a negative.
                Value::TinyUnsigned(held) => {
                    let _ = arguments.add(held.map(i16::from));
                }
                Value::SmallUnsigned(held) => {
                    let _ = arguments.add(held.map(i32::from));
                }
                Value::Unsigned(held) => {
                    let _ = arguments.add(held.map(i64::from));
                }
                Value::BigUnsigned(held) => {
                    let _ = arguments.add(held.map(|held| {
                        i64::try_from(held).expect("a bound count fits a signed integer")
                    }));
                }
                Value::Float(held) => {
                    let _ = arguments.add(held);
                }
                Value::Double(held) => {
                    let _ = arguments.add(held);
                }
                Value::String(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::Char(held) => {
                    let _ = arguments.add(held.map(|held| held.to_string()));
                }
                Value::Bytes(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::ChronoDate(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::ChronoTime(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::ChronoDateTime(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::ChronoDateTimeUtc(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::ChronoDateTimeLocal(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::ChronoDateTimeWithTimeZone(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::Uuid(held) => {
                    let _ = arguments.add(held.as_deref());
                }
                Value::Json(held) => {
                    let _ = arguments.add(held.as_deref());
                }
            }
        }

        arguments
    }
}

impl sqlx::IntoArguments<sqlx::sqlite::Sqlite> for SqlxValues {
    fn into_arguments(self) -> sqlx::sqlite::SqliteArguments {
        let mut arguments = sqlx::sqlite::SqliteArguments::default();
        for value in self.0.into_iter() {
            match value {
                Value::Bool(held) => {
                    let _ = arguments.add(held);
                }
                Value::TinyInt(held) => {
                    let _ = arguments.add(held);
                }
                Value::SmallInt(held) => {
                    let _ = arguments.add(held);
                }
                Value::Int(held) => {
                    let _ = arguments.add(held);
                }
                Value::BigInt(held) => {
                    let _ = arguments.add(held);
                }
                Value::TinyUnsigned(held) => {
                    let _ = arguments.add(held);
                }
                Value::SmallUnsigned(held) => {
                    let _ = arguments.add(held);
                }
                Value::Unsigned(held) => {
                    let _ = arguments.add(held);
                }
                Value::BigUnsigned(held) => {
                    let _ = arguments.add(held.map(|held| {
                        i64::try_from(held).expect("a bound count fits a signed integer")
                    }));
                }
                Value::Float(held) => {
                    let _ = arguments.add(held);
                }
                Value::Double(held) => {
                    let _ = arguments.add(held);
                }
                // SQLite's arguments own their text and bytes, where PostgreSQL's borrow them.
                Value::String(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::Char(held) => {
                    let _ = arguments.add(held.map(|held| held.to_string()));
                }
                Value::Bytes(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::ChronoDate(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::ChronoTime(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::ChronoDateTime(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::ChronoDateTimeUtc(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::ChronoDateTimeLocal(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::ChronoDateTimeWithTimeZone(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::Uuid(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
                Value::Json(held) => {
                    let _ = arguments.add(held.map(|held| *held));
                }
            }
        }

        arguments
    }
}
