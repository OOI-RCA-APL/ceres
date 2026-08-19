//! Describe every table's schema for the Python model generator.
//!
//! The generated Python models mirror the entity definitions, and only this crate can
//! see the derived tables, so `ceres-models` reads this description and renders the
//! modules under `ceres/__internal__/models/`.

use ceres_entities::{FieldFamily, FilterField};
use serde_json::{Value, json};

use crate::dynamic::Table;
use crate::load::ColumnDefault;
use crate::records::{Schema, Shape};
use crate::{EntityTable, RecordTable};

/// Every table the CLI and the Python layer share, entities and records both.
fn all() -> Vec<Table> {
    let records = [
        RecordTable::Alerts,
        RecordTable::Logs,
        RecordTable::Messages,
        RecordTable::Particles,
    ];
    let entities = [
        EntityTable::Users,
        EntityTable::Variables,
        EntityTable::Settings,
        EntityTable::Workspaces,
        EntityTable::WorkspaceEdits,
        EntityTable::Groups,
        EntityTable::GroupMemberships,
        EntityTable::UserPermissions,
        EntityTable::GroupPermissions,
    ];
    records
        .into_iter()
        .map(Table::Record)
        .chain(entities.into_iter().map(Table::Entity))
        .collect()
}

/// A family's name and payload in the dump.
fn family(family: &FieldFamily) -> Value {
    match family {
        FieldFamily::Uuid => json!({"name": "uuid"}),
        FieldFamily::Address => json!({"name": "address"}),
        FieldFamily::Timestamp => json!({"name": "timestamp"}),
        FieldFamily::Text => json!({"name": "text"}),
        FieldFamily::Email => json!({"name": "email"}),
        FieldFamily::Values(values) => json!({"name": "values", "values": values}),
        FieldFamily::Level => json!({"name": "level"}),
        FieldFamily::Bytes => json!({"name": "bytes"}),
        FieldFamily::Json => json!({"name": "json"}),
        FieldFamily::Boolean => json!({"name": "boolean"}),
        FieldFamily::JsonValue => json!({"name": "json_value"}),
        FieldFamily::PlainAddress => json!({"name": "plain_address"}),
    }
}

/// One field of the dump, a column or a filter key.
fn field(field: &FilterField) -> Value {
    json!({
        "key": field.key,
        "family": family(&field.family),
        "operations": field
            .operations
            .iter()
            .map(|operation| json!({
                "key": operation.key,
                "kind": format!("{:?}", operation.kind).to_lowercase(),
                "insensitive": operation.insensitive,
            }))
            .collect::<Vec<_>>(),
        "doc": field.doc,
        "python": field.python,
        "hidden": field.hidden,
    })
}

/// One table's whole schema.
fn table(name: &str, kind: &str, schema: &Schema, defaults: Value) -> Value {
    json!({
        "name": name,
        "kind": kind,
        "entity": schema.entity,
        "python_module": schema.python_module,
        "doc": schema.doc,
        "fields": schema.fields.iter().map(field).collect::<Vec<_>>(),
        "columns": schema.columns.iter().map(field).collect::<Vec<_>>(),
        "key": schema.key,
        "fixed": schema.fixed,
        "order": schema.order,
        "delegated": schema.delegated,
        "computed": schema
            .computed
            .iter()
            .map(|computed| json!({
                "key": computed.key,
                "column": computed.column,
                "shape": match computed.shape {
                    Shape::Internal => json!({"name": "internal"}),
                    Shape::Literal(value) => json!({"name": "literal", "value": value}),
                    Shape::Present => json!({"name": "present"}),
                },
                "doc": computed.doc,
            }))
            .collect::<Vec<_>>(),
        "defaults": defaults,
    })
}

/// The default of every column that has one, symbolically for generated values.
fn defaults(schema: &Schema, default: impl Fn(&str) -> Option<ColumnDefault>) -> Value {
    let mut described = serde_json::Map::new();
    for column in schema.columns {
        let Some(default) = default(column.key) else {
            continue;
        };
        let value = match default {
            ColumnDefault::GeneratedUuid => json!({"generated": "uuid"}),
            ColumnDefault::Literal(value) => json!({"value": value}),
        };
        described.insert(column.key.to_string(), value);
    }

    Value::Object(described)
}

/// The whole dump, every table's schema keyed by name.
pub fn tables() -> Value {
    let mut described = Vec::new();
    for entry in all() {
        match entry {
            Table::Record(record) => {
                let schema = record.schema();
                let defaults = defaults(&schema, |key| record.column_default(key));
                described.push(table(schema.name, "record", &schema, defaults));
            }
            Table::Entity(entity) => {
                let schema = entity.schema();
                let defaults = defaults(&schema, |key| entity.column_default(key));
                described.push(table(schema.name, "entity", &schema, defaults));
            }
        }
    }

    json!({"tables": described})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_dump_carries_the_model_essentials() {
        let dump = tables();
        let tables = dump["tables"].as_array().expect("a table list");
        assert_eq!(tables.len(), 13);

        let users = tables
            .iter()
            .find(|table| table["name"] == "users")
            .expect("a users table");
        assert_eq!(users["kind"], "entity");
        assert!(users["doc"].as_str().expect("a doc").contains("account"));
        assert_eq!(users["defaults"]["admin"]["value"], json!(false));
        assert_eq!(users["defaults"]["id"]["generated"], "uuid");

        let password = users["columns"]
            .as_array()
            .expect("columns")
            .iter()
            .find(|column| column["key"] == "password")
            .expect("a password column");
        assert_eq!(password["python"], "Password | PasswordHash");
    }
}
