//! Assignments for a native record update.
//!
//! An `update` carries its new values as one YAML or JSON object, the same form the
//! Python command accepts. Each key names a column, and its value encodes into the
//! form that column stores, which differs per backend exactly as the writer's does.
//!
//! Anything this module cannot represent returns `None`, which makes the whole command
//! delegate. That keeps the native path from inventing a value the Python model would
//! have rejected or coerced differently.

use ceres_entities::{Address, FieldFamily, latin1};
use sea_query::SimpleExpr;
use serde_json::Value;

use crate::records::RecordTable;
use crate::store::Parameter;
use crate::writer::Dialect;

/// One `SET` clause, a column and the value to store in it.
pub(crate) struct Assignment {
    pub(crate) column: &'static str,
    pub(crate) value: SimpleExpr,
}

/// Encode an assignment object into per-column values, `None` when any key or value
/// falls outside what the native path can represent faithfully.
///
/// The ID is never assignable, matching the entity update models, which exclude it.
pub(crate) fn assignments(
    table: RecordTable,
    values: &serde_json::Map<String, Value>,
    dialect: Dialect,
) -> Option<Vec<Assignment>> {
    if values.is_empty() {
        return None;
    }

    let mut assignments = Vec::with_capacity(values.len());
    for (key, value) in values {
        if key == "id" {
            return None;
        }

        let field = table.fields().iter().find(|field| field.key == key)?;
        assignments.push(Assignment {
            column: field.key,
            value: encode(&field.family, value, dialect)?,
        });
    }

    Some(assignments)
}

/// Encode one value into the form its column stores.
fn encode(family: &FieldFamily, value: &Value, dialect: Dialect) -> Option<SimpleExpr> {
    // A null clears a nullable column. The database rejects it on a column that is not
    // nullable, which rolls the transaction back and delegates.
    if value.is_null() {
        return Some(SimpleExpr::Keyword(sea_query::Keyword::Null));
    }

    Some(match family {
        FieldFamily::Uuid => {
            let parsed: uuid::Uuid = value.as_str()?.parse().ok()?;
            match dialect {
                Dialect::Sqlite => parsed.hyphenated().to_string().into(),
                Dialect::Postgres => parsed.into(),
            }
        }
        FieldFamily::Address => Address::parse(value.as_str()?)
            .ok()?
            .as_str()
            .to_string()
            .into(),
        FieldFamily::Timestamp => {
            let parsed = crate::filter::parse_timestamp(value.as_str()?).ok()?;
            match dialect {
                Dialect::Sqlite => Parameter::timestamp_text(&parsed).into(),
                Dialect::Postgres => parsed.into(),
            }
        }
        FieldFamily::Text => value.as_str()?.to_string().into(),
        FieldFamily::Values(allowed) => {
            let text = value.as_str()?;
            if !allowed.contains(&text) {
                return None;
            }

            text.to_string().into()
        }
        FieldFamily::Level => {
            let text = value.as_str()?;
            ceres_entities::Level::parse(text).ok()?;
            text.to_string().into()
        }
        // Message payloads cross the wire as the latin-1 text of their bytes, the same
        // form a dump renders.
        FieldFamily::Bytes => latin1::encode(value.as_str()?).into(),
        FieldFamily::Json => {
            if !value.is_object() {
                return None;
            }

            match dialect {
                Dialect::Sqlite => value.to_string().into(),
                Dialect::Postgres => value.clone().into(),
            }
        }
        FieldFamily::Boolean => value.as_bool()?.into(),
        // A value column takes whatever JSON it was given, stored as its text on the
        // SQLite family the way the query layer writes it.
        FieldFamily::JsonValue => match dialect {
            Dialect::Sqlite => value.to_string().into(),
            Dialect::Postgres => value.clone().into(),
        },
        FieldFamily::PlainAddress => Address::parse(value.as_str()?)
            .ok()?
            .as_str()
            .to_string()
            .into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn object(json: &str) -> serde_json::Map<String, Value> {
        serde_json::from_str(json).unwrap()
    }

    #[test]
    fn unknown_and_unassignable_keys_refuse() {
        assert!(assignments(RecordTable::Messages, &object("{}"), Dialect::Sqlite).is_none());
        assert!(
            assignments(
                RecordTable::Messages,
                &object("{\"nope\": 1}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        // The ID is not assignable, matching the entity update models.
        assert!(
            assignments(
                RecordTable::Messages,
                &object("{\"id\": \"0198c0de-0000-7000-8000-000000000001\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
    }

    #[test]
    fn values_outside_a_closed_set_refuse() {
        assert!(
            assignments(
                RecordTable::Messages,
                &object("{\"direction\": \"sideways\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        assert!(
            assignments(
                RecordTable::Messages,
                &object("{\"direction\": \"send\"}"),
                Dialect::Sqlite
            )
            .is_some()
        );
        assert!(
            assignments(
                RecordTable::Alerts,
                &object("{\"level\": \"nope\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
    }

    #[test]
    fn malformed_scalars_refuse() {
        assert!(
            assignments(
                RecordTable::Messages,
                &object("{\"timestamp\": \"not a time\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        assert!(
            assignments(
                RecordTable::Messages,
                &object("{\"address\": \"not an address\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        // A JSON payload column takes an object, never a scalar.
        assert!(
            assignments(
                RecordTable::Particles,
                &object("{\"data\": 3}"),
                Dialect::Sqlite
            )
            .is_none()
        );
    }

    #[test]
    fn every_assignable_column_encodes() {
        let assigned = assignments(
            RecordTable::Messages,
            &object(
                "{\"address\": \"@sensor.temp\", \
                  \"timestamp\": \"2026-07-29T12:30:45.123456Z\", \
                  \"connection\": null, \
                  \"direction\": \"receive\", \
                  \"data\": \"ab\"}",
            ),
            Dialect::Sqlite,
        )
        .unwrap();
        // The `SET` clause order carries no meaning, so compare the columns as a set.
        let mut columns: Vec<&str> = assigned.iter().map(|one| one.column).collect();
        columns.sort_unstable();
        assert_eq!(
            columns,
            vec!["address", "connection", "data", "direction", "timestamp"]
        );
    }
}
