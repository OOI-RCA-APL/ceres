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

use crate::credentials::normalize_email;
use crate::records::Schema;
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
/// The columns encode against the table's whole column list rather than its filter
/// surface, because a column a filter cannot name is still one an update may assign.
/// The schema's fixed columns are the ones the entity update models leave out.
pub(crate) fn assignments(
    schema: Schema,
    values: &serde_json::Map<String, Value>,
    dialect: Dialect,
) -> Option<Vec<Assignment>> {
    if values.is_empty() {
        return None;
    }

    let mut assignments = Vec::with_capacity(values.len());
    for (key, value) in values {
        if schema.fixed.contains(&key.as_str()) {
            return None;
        }

        let field = schema.columns.iter().find(|field| field.key == key)?;
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
        // An address stores normalized, and normalizing one that already is changes
        // nothing, so this holds whether or not the credential rules ran first.
        FieldFamily::Email => normalize_email(value.as_str()?)?.into(),
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
    use crate::entities::EntityTable;
    use crate::records::RecordTable;

    fn object(json: &str) -> serde_json::Map<String, Value> {
        serde_json::from_str(json).unwrap()
    }

    #[test]
    fn unknown_and_unassignable_keys_refuse() {
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"nope\": 1}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        // The ID is not assignable, matching the entity update models.
        assert!(
            assignments(
                RecordTable::Messages.schema(),
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
                RecordTable::Messages.schema(),
                &object("{\"direction\": \"sideways\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"direction\": \"send\"}"),
                Dialect::Sqlite
            )
            .is_some()
        );
        assert!(
            assignments(
                RecordTable::Alerts.schema(),
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
                RecordTable::Messages.schema(),
                &object("{\"timestamp\": \"not a time\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"address\": \"not an address\"}"),
                Dialect::Sqlite
            )
            .is_none()
        );
        // A JSON payload column takes an object, never a scalar.
        assert!(
            assignments(
                RecordTable::Particles.schema(),
                &object("{\"data\": 3}"),
                Dialect::Sqlite
            )
            .is_none()
        );
    }

    #[test]
    fn an_entity_assigns_the_columns_its_update_model_declares() {
        let assign = |table: EntityTable, json: &str| {
            assignments(table.schema(), &object(json), Dialect::Sqlite)
        };

        // A setting's value is outside the filter surface and still assignable, which
        // is why the encoder reads the column list rather than the filter fields.
        assert!(assign(EntityTable::Settings, "{\"value\": 5}").is_some());
        assert!(assign(EntityTable::Workspaces, "{\"data\": {\"k\": 1}}").is_some());

        // A variable's name is half its key and assignable, its address is not.
        assert!(assign(EntityTable::Variables, "{\"name\": \"x\"}").is_some());
        assert!(assign(EntityTable::Variables, "{\"address\": \"@a\"}").is_none());
        assert!(assign(EntityTable::Settings, "{\"name\": \"x\"}").is_some());
        assert!(
            assign(
                EntityTable::Settings,
                "{\"user_id\": \"0198c0de-0000-7000-8000-000000000001\"}"
            )
            .is_none()
        );

        // A workspace's scope is an address outside the selector grammar, and its
        // owner clears to null.
        assert!(assign(EntityTable::Workspaces, "{\"scope\": \"@a.b\"}").is_some());
        assert!(assign(EntityTable::Workspaces, "{\"scope\": \"not one\"}").is_none());
        assert!(assign(EntityTable::Workspaces, "{\"owner_id\": null}").is_some());
        assert!(assign(EntityTable::Workspaces, "{\"show_when_logged_out\": true}").is_some());
        assert!(
            assign(
                EntityTable::Workspaces,
                "{\"show_when_logged_out\": \"yes\"}"
            )
            .is_none()
        );
    }

    #[test]
    fn every_assignable_column_encodes() {
        let assigned = assignments(
            RecordTable::Messages.schema(),
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
