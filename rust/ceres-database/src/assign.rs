//! Assignments for a native record update.
//!
//! An `update` carries its new values as one YAML or JSON object, the same form the
//! Python command accepts. Each key names a column, and its value encodes into the
//! form that column stores, which differs per backend exactly as the writer's does.
//!
//! Anything this module cannot represent is refused with a sentence naming the key and
//! what it wanted, because the reader is holding a command line they can fix. Nothing is
//! coerced into a shape the column did not ask for.

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

/// Encode an assignment object into per-column values.
///
/// The columns encode against the table's whole column list rather than its filter
/// surface, because a column a filter cannot name is still one an update may assign.
/// The schema's fixed columns are the ones that identify a row rather than describe it.
///
/// A refusal carries the sentence to show, naming the key and what it wanted.
pub(crate) fn assignments(
    schema: Schema,
    values: &serde_json::Map<String, Value>,
    dialect: Dialect,
) -> Result<Vec<Assignment>, String> {
    if values.is_empty() {
        return Err("--assign was given nothing to assign.".to_string());
    }

    let mut assignments = Vec::with_capacity(values.len());
    for (key, value) in values {
        if schema.fixed.contains(&key.as_str()) {
            return Err(format!(
                "`{key}` is part of what identifies a row, so it cannot be assigned. \
                 Create the row you want and delete this one instead."
            ));
        }

        let Some(field) = schema.columns.iter().find(|field| field.key == key) else {
            return Err(format!(
                "There is no `{key}` to assign. This table holds {}.",
                listed(&assignable(schema))
            ));
        };

        let value = encode(&field.family, value, dialect)
            .map_err(|wanted| format!("`{key}` {wanted}, and was given {}.", shown(value)))?;
        assignments.push(Assignment {
            column: field.key,
            value,
        });
    }

    Ok(assignments)
}

/// The columns an update may assign, which is every column that is not identity.
fn assignable(schema: Schema) -> Vec<&'static str> {
    schema
        .columns
        .iter()
        .map(|field| field.key)
        .filter(|key| !schema.fixed.contains(key))
        .collect()
}

/// Join names into a readable list.
fn listed(names: &[&str]) -> String {
    match names {
        [] => "no assignable columns".to_string(),
        [only] => format!("`{only}`"),
        [rest @ .., last] => format!(
            "{} and `{last}`",
            rest.iter()
                .map(|name| format!("`{name}`"))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

/// How a value reads back in a message, short enough to sit in a sentence.
fn shown(value: &Value) -> String {
    let rendered = value.to_string();
    if rendered.chars().count() <= 40 {
        return rendered;
    }

    format!("{}...", rendered.chars().take(40).collect::<String>())
}

/// Encode one value into the form its column stores.
///
/// A refusal is the phrase describing what the column wanted, which the caller puts in a
/// sentence alongside the key and the value that was actually given.
fn encode(family: &FieldFamily, value: &Value, dialect: Dialect) -> Result<SimpleExpr, String> {
    // A null clears a nullable column. The database rejects it on a column that is not
    // nullable, which rolls the transaction back and reports.
    if value.is_null() {
        return Ok(SimpleExpr::Keyword(sea_query::Keyword::Null));
    }

    /// Read a value as text, or say what was wanted instead.
    fn text<'a>(value: &'a Value, wanted: &str) -> Result<&'a str, String> {
        value
            .as_str()
            .ok_or_else(|| format!("takes {wanted} as text"))
    }

    Ok(match family {
        FieldFamily::Uuid => {
            let parsed: uuid::Uuid = text(value, "a UUID")?
                .parse()
                .map_err(|_| "takes a UUID".to_string())?;
            match dialect {
                Dialect::Sqlite => parsed.hyphenated().to_string().into(),
                Dialect::Postgres => parsed.into(),
            }
        }
        FieldFamily::Address => Address::parse(text(value, "an address")?)
            .map_err(|_| "takes an address, which starts with `@`".to_string())?
            .as_str()
            .to_string()
            .into(),
        FieldFamily::Timestamp => {
            let parsed = crate::filter::parse_timestamp(text(value, "a timestamp")?)
                .map_err(|_| "takes an ISO 8601 timestamp".to_string())?;
            match dialect {
                Dialect::Sqlite => Parameter::timestamp_text(&parsed).into(),
                Dialect::Postgres => parsed.into(),
            }
        }
        FieldFamily::Text => text(value, "text")?.to_string().into(),
        // An address stores normalized, and normalizing one that already is changes
        // nothing, so this holds whether or not the credential rules ran first.
        FieldFamily::Email => normalize_email(text(value, "an email address")?)
            .ok_or_else(|| "takes an email address".to_string())?
            .into(),
        FieldFamily::Values(allowed) => {
            let held = text(value, "one of a fixed set of words")?;
            if !allowed.contains(&held) {
                return Err(format!("takes one of {}", listed(allowed)));
            }

            held.to_string().into()
        }
        FieldFamily::Level => {
            let held = text(value, "a log level")?;
            ceres_entities::Level::parse(held).map_err(|_| "takes a log level".to_string())?;
            held.to_string().into()
        }
        // Message payloads cross the wire as the latin-1 text of their bytes, the same
        // form a dump renders.
        FieldFamily::Bytes => latin1::encode(text(value, "a payload")?).into(),
        FieldFamily::Json => {
            if !value.is_object() {
                return Err("takes an object".to_string());
            }

            match dialect {
                Dialect::Sqlite => value.to_string().into(),
                Dialect::Postgres => value.clone().into(),
            }
        }
        FieldFamily::Boolean => value
            .as_bool()
            .ok_or_else(|| "takes true or false".to_string())?
            .into(),
        // A value column takes whatever JSON it was given, stored as its text on the
        // SQLite family the way the query layer writes it.
        FieldFamily::JsonValue => match dialect {
            Dialect::Sqlite => value.to_string().into(),
            Dialect::Postgres => value.clone().into(),
        },
        FieldFamily::PlainAddress => Address::parse(text(value, "an address")?)
            .map_err(|_| "takes an address, which starts with `@`".to_string())?
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
            .is_err()
        );
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"nope\": 1}"),
                Dialect::Sqlite
            )
            .is_err()
        );
        // The ID is not assignable, matching the entity update models.
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"id\": \"0198c0de-0000-7000-8000-000000000001\"}"),
                Dialect::Sqlite
            )
            .is_err()
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
            .is_err()
        );
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"direction\": \"send\"}"),
                Dialect::Sqlite
            )
            .is_ok()
        );
        assert!(
            assignments(
                RecordTable::Alerts.schema(),
                &object("{\"level\": \"nope\"}"),
                Dialect::Sqlite
            )
            .is_err()
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
            .is_err()
        );
        assert!(
            assignments(
                RecordTable::Messages.schema(),
                &object("{\"address\": \"not an address\"}"),
                Dialect::Sqlite
            )
            .is_err()
        );
        // A JSON payload column takes an object, never a scalar.
        assert!(
            assignments(
                RecordTable::Particles.schema(),
                &object("{\"data\": 3}"),
                Dialect::Sqlite
            )
            .is_err()
        );
    }

    #[test]
    fn an_entity_assigns_the_columns_its_update_model_declares() {
        let assign = |table: EntityTable, json: &str| {
            assignments(table.schema(), &object(json), Dialect::Sqlite)
        };

        // A setting's value is outside the filter surface and still assignable, which
        // is why the encoder reads the column list rather than the filter fields.
        assert!(assign(EntityTable::Settings, "{\"value\": 5}").is_ok());
        assert!(assign(EntityTable::Workspaces, "{\"data\": {\"k\": 1}}").is_ok());

        // A variable's name is half its key and assignable, its address is not.
        assert!(assign(EntityTable::Variables, "{\"name\": \"x\"}").is_ok());
        assert!(assign(EntityTable::Variables, "{\"address\": \"@a\"}").is_err());
        assert!(assign(EntityTable::Settings, "{\"name\": \"x\"}").is_ok());
        assert!(
            assign(
                EntityTable::Settings,
                "{\"user_id\": \"0198c0de-0000-7000-8000-000000000001\"}"
            )
            .is_err()
        );

        // A workspace's scope is an address outside the selector grammar, and its
        // owner clears to null.
        assert!(assign(EntityTable::Workspaces, "{\"scope\": \"@a.b\"}").is_ok());
        assert!(assign(EntityTable::Workspaces, "{\"scope\": \"not one\"}").is_err());
        assert!(assign(EntityTable::Workspaces, "{\"owner_id\": null}").is_ok());
        assert!(assign(EntityTable::Workspaces, "{\"show_when_logged_out\": true}").is_ok());
        assert!(
            assign(
                EntityTable::Workspaces,
                "{\"show_when_logged_out\": \"yes\"}"
            )
            .is_err()
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
