//! Column values for a native write, an update's or an insert's.
//!
//! A write carries its values as one YAML or JSON object, the same form the Python command
//! accepts. Each key names a column, and its value encodes into the form that column
//! stores, which differs per backend exactly as the writer's does.
//!
//! The two writes differ in one place. An update refuses the columns that identify a row
//! because changing an identity is a different row rather than the same one moved. An
//! insert requires them because that is where the identity comes from. Everything past
//! that guard is the same encoding.
//!
//! Anything this module cannot represent is refused with a message naming the key and
//! the form it expected because the reader is fixing a command line. Nothing is
//! coerced into a shape the column did not ask for.

use ceres_entities::{Address, FieldFamily, latin1};
use sea_query::SimpleExpr;
use serde_json::Value;

use crate::credentials::normalize_email;
use crate::dynamic::Table;
use crate::filter::SqlDialect;
use crate::records::Schema;
use crate::store::Parameter;

/// One `SET` clause, a column and the value to store in it.
pub(crate) struct SetClause {
    pub(crate) column: &'static str,
    pub(crate) value: SimpleExpr,
}

impl Schema {
    /// Encode a set object into per-column values.
    ///
    /// The columns encode against the table's whole column list rather than its filter
    /// surface because a column a filter cannot name is still one an update may set.
    /// The schema's fixed columns are the ones that identify a row rather than describe
    /// it.
    ///
    /// A refusal carries a user-facing message naming the key and the form it expected.
    pub(crate) fn set_clauses(
        self,
        values: &serde_json::Map<String, Value>,
        dialect: SqlDialect,
    ) -> Result<Vec<SetClause>, String> {
        if values.is_empty() {
            return Err("--set was given nothing to set.".to_string());
        }

        for key in values.keys() {
            if self.fixed.contains(&key.as_str()) {
                return Err(format!(
                    "`{key}` is part of what identifies a row, so it cannot be set. \
                     Create the row you want and delete this one instead."
                ));
            }
        }

        self.encoded(values, dialect)
    }

    /// Encode an insert's column values.
    ///
    /// An insert sets the row's identity rather than changing it so the columns an
    /// update refuses are the ones this one requires, and the identity guard does not
    /// apply here.
    pub(crate) fn insert_values(
        self,
        values: &serde_json::Map<String, Value>,
        dialect: SqlDialect,
    ) -> Result<Vec<SetClause>, String> {
        if values.is_empty() {
            return Err("An insert was given no columns to write.".to_string());
        }

        self.encoded(values, dialect)
    }

    /// Encode each named column's value into the form that column stores.
    fn encoded(
        self,
        values: &serde_json::Map<String, Value>,
        dialect: SqlDialect,
    ) -> Result<Vec<SetClause>, String> {
        let mut set_clauses = Vec::with_capacity(values.len());
        for (key, value) in values {
            let Some(field) = self.columns.iter().find(|field| field.key == key) else {
                return Err(format!(
                    "There is no `{key}` to set. This table holds {}.",
                    listed(&self.settable())
                ));
            };

            let value = encode(&field.family, value, dialect)
                .map_err(|wanted| format!("`{key}` {wanted}, and was given {}.", shown(value)))?;
            set_clauses.push(SetClause {
                column: field.key,
                value,
            });
        }

        Ok(set_clauses)
    }

    /// The columns an update may set, which is every column that is not identity.
    fn settable(self) -> Vec<&'static str> {
        self.columns
            .iter()
            .map(|field| field.key)
            .filter(|key| !self.fixed.contains(key))
            .collect()
    }
}

/// Compile one row's insert to SQL and its bound parameters.
///
/// `upsert` decides what a collision on the table's primary key does. Without it the
/// collision is the caller's to see, which turns a duplicate into the error that
/// names the column it collided on. With it every column outside the key takes the new
/// row's value, which makes a repeated write idempotent rather than a failure.
pub fn insert_compiled(
    table: Table,
    values: &serde_json::Map<String, serde_json::Value>,
    upsert: bool,
    dialect: SqlDialect,
) -> Result<(String, Vec<sea_query::Value>), String> {
    let schema = table.schema();
    let set_clauses = schema.insert_values(values, dialect)?;

    let mut statement = sea_query::Query::insert();
    statement.into_table(sea_query::Alias::new(schema.name));
    statement.columns(
        set_clauses
            .iter()
            .map(|clause| sea_query::Alias::new(clause.column)),
    );
    statement
        .values(
            set_clauses
                .iter()
                .map(|clause| clause.value.clone())
                .collect::<Vec<_>>(),
        )
        .map_err(|error| format!("The insert could not be built. {error}"))?;

    if upsert {
        let mut clause = sea_query::OnConflict::columns(
            schema.key.iter().map(|&key| sea_query::Alias::new(key)),
        );
        clause.update_columns(
            set_clauses
                .iter()
                .map(|clause| clause.column)
                .filter(|column| !schema.key.contains(column))
                .map(sea_query::Alias::new),
        );
        statement.on_conflict(clause);
    }

    let (sql, values) = match dialect {
        SqlDialect::SqliteText => statement.build(sea_query::SqliteQueryBuilder),
        SqlDialect::Postgres => statement.build(sea_query::PostgresQueryBuilder),
    };
    Ok((sql, values.0))
}

/// A JSON document's text as the value its column stores.
///
/// Both backends store the text so both bind text. PostgreSQL's `json` keeps what it
/// was given, key order included, and only casts to it here rather than binding a
/// document object, which would arrive as `jsonb` and be normalized on the way in. That
/// normalization reorders keys, and a filter comparing the stored text would then miss
/// the row it wrote.
pub(crate) fn json_text(text: &str, dialect: SqlDialect) -> SimpleExpr {
    match dialect {
        SqlDialect::SqliteText => text.into(),
        SqlDialect::Postgres => SimpleExpr::from(text).cast_as(sea_query::Alias::new("json")),
    }
}

/// Join names into a readable list.
fn listed(names: &[&str]) -> String {
    match names {
        [] => "no settable columns".to_string(),
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
fn encode(family: &FieldFamily, value: &Value, dialect: SqlDialect) -> Result<SimpleExpr, String> {
    // A null clears a nullable column. The database rejects it on a column that is not
    // nullable, which rolls the transaction back and reports.
    //
    // A column holding a whole JSON document is the exception. There a null is a value the
    // document can take rather than the absence of one so it stores as the JSON `null` and
    // reads back as one. Clearing such a column would be a different thing, and no column
    // that stores a document is nullable anyway.
    if value.is_null() && !matches!(family, FieldFamily::JsonValue) {
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
                SqlDialect::SqliteText => parsed.hyphenated().to_string().into(),
                SqlDialect::Postgres => parsed.into(),
            }
        }
        FieldFamily::Address | FieldFamily::PlainAddress => {
            Address::parse(text(value, "an address")?)
                .map_err(|_| "takes an address, which starts with `@`".to_string())?
                .as_str()
                .to_string()
                .into()
        }
        FieldFamily::Timestamp => {
            let parsed = crate::filter::parse_timestamp(text(value, "a timestamp")?)
                .map_err(|_| "takes an ISO 8601 timestamp".to_string())?;
            match dialect {
                SqlDialect::SqliteText => Parameter::timestamp_text(&parsed).into(),
                SqlDialect::Postgres => parsed.into(),
            }
        }
        FieldFamily::Text => text(value, "text")?.to_string().into(),
        // An address stores normalized, and normalizing one that already is changes
        // nothing so this holds whether or not the credential rules ran first.
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

            json_text(&value.to_string(), dialect)
        }
        FieldFamily::Boolean => value
            .as_bool()
            .ok_or_else(|| "takes true or false".to_string())?
            .into(),
        // A value column takes whatever JSON it was given, stored as its text the way the
        // query layer writes it.
        FieldFamily::JsonValue => json_text(&value.to_string(), dialect),
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
    fn unknown_and_unsettable_keys_refuse() {
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(&object("{}"), SqlDialect::SqliteText)
                .is_err()
        );
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(&object("{\"nope\": 1}"), SqlDialect::SqliteText)
                .is_err()
        );
        // The ID is not settable, matching the entity update models.
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(
                    &object("{\"id\": \"0198c0de-0000-7000-8000-000000000001\"}"),
                    SqlDialect::SqliteText
                )
                .is_err()
        );
    }

    #[test]
    fn values_outside_a_closed_set_refuse() {
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(
                    &object("{\"direction\": \"sideways\"}"),
                    SqlDialect::SqliteText
                )
                .is_err()
        );
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(&object("{\"direction\": \"send\"}"), SqlDialect::SqliteText)
                .is_ok()
        );
        assert!(
            RecordTable::Alerts
                .schema()
                .set_clauses(&object("{\"level\": \"nope\"}"), SqlDialect::SqliteText)
                .is_err()
        );
    }

    #[test]
    fn malformed_scalars_refuse() {
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(
                    &object("{\"timestamp\": \"not a time\"}"),
                    SqlDialect::SqliteText
                )
                .is_err()
        );
        assert!(
            RecordTable::Messages
                .schema()
                .set_clauses(
                    &object("{\"address\": \"not an address\"}"),
                    SqlDialect::SqliteText
                )
                .is_err()
        );
        // A JSON payload column takes an object, never a scalar.
        assert!(
            RecordTable::Particles
                .schema()
                .set_clauses(&object("{\"data\": 3}"), SqlDialect::SqliteText)
                .is_err()
        );
    }

    #[test]
    fn an_entity_sets_the_columns_its_update_model_declares() {
        let set = |table: EntityTable, json: &str| {
            table
                .schema()
                .set_clauses(&object(json), SqlDialect::SqliteText)
        };

        // A setting's value is outside the filter surface and still settable, which
        // is why the encoder reads the column list rather than the filter fields.
        assert!(set(EntityTable::Settings, "{\"value\": 5}").is_ok());
        assert!(set(EntityTable::Workspaces, "{\"data\": {\"k\": 1}}").is_ok());

        // A variable's name is half its key and settable, its address is not.
        assert!(set(EntityTable::Variables, "{\"name\": \"x\"}").is_ok());
        assert!(set(EntityTable::Variables, "{\"address\": \"@a\"}").is_err());
        assert!(set(EntityTable::Settings, "{\"name\": \"x\"}").is_ok());
        assert!(
            set(
                EntityTable::Settings,
                "{\"user_id\": \"0198c0de-0000-7000-8000-000000000001\"}"
            )
            .is_err()
        );

        // A workspace's scope is an address outside the selector grammar, and its
        // owner clears to null.
        assert!(set(EntityTable::Workspaces, "{\"scope\": \"@a.b\"}").is_ok());
        assert!(set(EntityTable::Workspaces, "{\"scope\": \"not one\"}").is_err());
        assert!(set(EntityTable::Workspaces, "{\"owner_id\": null}").is_ok());
        assert!(set(EntityTable::Workspaces, "{\"show_when_logged_out\": true}").is_ok());
        assert!(
            set(
                EntityTable::Workspaces,
                "{\"show_when_logged_out\": \"yes\"}"
            )
            .is_err()
        );
    }

    #[test]
    fn every_settable_column_encodes() {
        let settable = RecordTable::Messages
            .schema()
            .set_clauses(
                &object(
                    "{\"address\": \"@sensor.temp\", \
                  \"timestamp\": \"2026-07-29T12:30:45.123456Z\", \
                  \"connection\": null, \
                  \"direction\": \"receive\", \
                  \"data\": \"ab\"}",
                ),
                SqlDialect::SqliteText,
            )
            .unwrap();
        // The `SET` clause order carries no meaning so compare the columns as a set.
        let mut columns: Vec<&str> = settable.iter().map(|one| one.column).collect();
        columns.sort_unstable();
        assert_eq!(
            columns,
            vec!["address", "connection", "data", "direction", "timestamp"]
        );
    }
}
