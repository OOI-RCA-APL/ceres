//! The non-record entities the CLI manages.
//!
//! Users, variables, settings, and workspaces are small tables an operator reads and
//! edits directly, unlike the record tables components fill. Each struct's serialized
//! form is the wire format for it, field order included, so a native dump and a
//! materialized one render the same bytes.
//!
//! The filterable surface derives from these structs the way the records' does. Two
//! markers keep the derive honest where the Python filter and the column list disagree.
//! `skip` drops a column the filter does not expose, a user's password hash among them,
//! and `plain` takes a workspace's scope out of the selector grammar.

use ceres_macros::Filterable;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::address::Address;
use crate::records::CsvRecord;

/// An operator account.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct User {
    pub id: Uuid,
    pub username: String,
    /// The account's email address, whose operations fold case the way the Python
    /// filter's do.
    ///
    /// Its equality key is not served here. The Python model validates and normalizes
    /// an email before comparing it, lowercasing it and resolving its domain, which is
    /// the `email_validator` library's own behavior rather than something to reproduce.
    #[filterable(insensitive)]
    pub email: String,
    /// The Argon2 hash of the account's password.
    ///
    /// The CLI prints it, since an operator running these commands already holds the
    /// database credentials and the value is a hash rather than a recoverable secret.
    /// It is not filterable, and the Python filter does not expose it either.
    #[filterable(skip)]
    pub password: String,
    pub admin: bool,
    pub disabled: bool,
}

/// A named value owned by an addressed node.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Variable {
    pub address: Address,
    pub name: String,
    pub value: Value,
}

/// A named value owned by a user.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Setting {
    pub user_id: Uuid,
    pub name: String,
    /// A setting's value is stored like a variable's but is not filterable, the Python
    /// filter exposing only the owner and the name.
    #[filterable(skip)]
    pub value: Value,
}

/// A console layout owned by a user or shared.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Workspace {
    pub id: Uuid,
    pub name: String,
    /// The subtree the workspace covers, `~` for one placed on the engine itself.
    #[filterable(plain)]
    pub scope: Address,
    pub owner_id: Option<Uuid>,
    pub show_when_logged_out: bool,
    #[filterable(skip)]
    pub data: Map<String, Value>,
}

impl CsvRecord for User {
    const CSV_HEADER: &'static str = "id,username,email,password,admin,disabled";

    fn csv_cells(&self) -> Vec<Option<String>> {
        vec![
            Some(self.id.to_string()),
            Some(self.username.clone()),
            Some(self.email.clone()),
            Some(self.password.clone()),
            Some(boolean_cell(self.admin)),
            Some(boolean_cell(self.disabled)),
        ]
    }
}

impl CsvRecord for Variable {
    const CSV_HEADER: &'static str = "address,name,value";

    fn csv_cells(&self) -> Vec<Option<String>> {
        vec![
            Some(self.address.as_str().to_string()),
            Some(self.name.clone()),
            value_cell(&self.value),
        ]
    }
}

impl CsvRecord for Setting {
    const CSV_HEADER: &'static str = "user_id,name,value";

    fn csv_cells(&self) -> Vec<Option<String>> {
        vec![
            Some(self.user_id.to_string()),
            Some(self.name.clone()),
            value_cell(&self.value),
        ]
    }
}

impl CsvRecord for Workspace {
    const CSV_HEADER: &'static str = "id,name,scope,owner_id,show_when_logged_out,data";

    fn csv_cells(&self) -> Vec<Option<String>> {
        vec![
            Some(self.id.to_string()),
            Some(self.name.clone()),
            Some(self.scope.as_str().to_string()),
            self.owner_id.map(|id| id.to_string()),
            Some(boolean_cell(self.show_when_logged_out)),
            Some(Value::Object(self.data.clone()).to_string()),
        ]
    }
}

/// A boolean cell, rendered as its JSON text the way the row extraction does.
fn boolean_cell(value: bool) -> String {
    if value { "true" } else { "false" }.to_string()
}

/// A JSON value's cell, its own text when it is a string and its JSON text otherwise.
///
/// The row extraction writes a string as itself rather than carrying JSON quotes into
/// the cell, and a null as no cell at all.
fn value_cell(value: &Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::String(text) => Some(text.clone()),
        other => Some(other.to_string()),
    }
}

/// The entities of one query result, all of a single type.
#[derive(Clone, Debug, PartialEq)]
pub enum Entities {
    Users(Vec<User>),
    Variables(Vec<Variable>),
    Settings(Vec<Setting>),
    Workspaces(Vec<Workspace>),
}

impl Entities {
    /// The number of entities held.
    pub fn len(&self) -> usize {
        match self {
            Self::Users(entities) => entities.len(),
            Self::Variables(entities) => entities.len(),
            Self::Settings(entities) => entities.len(),
            Self::Workspaces(entities) => entities.len(),
        }
    }

    /// Whether no entities are held.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Serialize the entities as JSON lines in the wire format, one per line.
    pub fn to_json_lines(&self) -> serde_json::Result<Vec<u8>> {
        match self {
            Self::Users(entities) => crate::records::to_json_lines(entities),
            Self::Variables(entities) => crate::records::to_json_lines(entities),
            Self::Settings(entities) => crate::records::to_json_lines(entities),
            Self::Workspaces(entities) => crate::records::to_json_lines(entities),
        }
    }

    /// Render the entities as CSV lines, under a header row unless suppressed.
    pub fn to_csv_lines(&self, header: bool) -> String {
        match self {
            Self::Users(entities) => crate::records::to_csv_lines(entities, header),
            Self::Variables(entities) => crate::records::to_csv_lines(entities, header),
            Self::Settings(entities) => crate::records::to_csv_lines(entities, header),
            Self::Workspaces(entities) => crate::records::to_csv_lines(entities, header),
        }
    }

    /// Serialize a field projection of the entities as JSON lines, aliased objects.
    pub fn to_json_lines_projected(
        &self,
        fields: &[(String, String)],
    ) -> serde_json::Result<Vec<u8>> {
        match self {
            Self::Users(entities) => crate::records::to_json_lines_projected(entities, fields),
            Self::Variables(entities) => crate::records::to_json_lines_projected(entities, fields),
            Self::Settings(entities) => crate::records::to_json_lines_projected(entities, fields),
            Self::Workspaces(entities) => crate::records::to_json_lines_projected(entities, fields),
        }
    }

    /// Render a field projection of the entities as CSV lines, an alias header row
    /// unless suppressed.
    pub fn to_csv_lines_projected(
        &self,
        fields: &[(String, String)],
        header: bool,
    ) -> serde_json::Result<String> {
        match self {
            Self::Users(rows) => crate::records::to_csv_lines_projected(rows, fields, header),
            Self::Variables(rows) => crate::records::to_csv_lines_projected(rows, fields, header),
            Self::Settings(rows) => crate::records::to_csv_lines_projected(rows, fields, header),
            Self::Workspaces(rows) => crate::records::to_csv_lines_projected(rows, fields, header),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use crate::Filterable;

    fn keys<T: Filterable>() -> Vec<&'static str> {
        T::FIELDS.iter().map(|field| field.key).collect()
    }

    #[test]
    fn skipped_columns_stay_off_the_filter_surface() {
        // A user's password hash prints but does not filter, and neither does a
        // setting's value or a workspace's data.
        assert_eq!(
            keys::<User>(),
            vec!["id", "username", "email", "admin", "disabled"]
        );
        assert_eq!(keys::<Setting>(), vec!["user_id", "name"]);
        assert_eq!(
            keys::<Workspace>(),
            vec!["id", "name", "scope", "owner_id", "show_when_logged_out"]
        );
    }

    #[test]
    fn families_follow_the_python_filter_surface() {
        use crate::FieldFamily;

        let family = |fields: &'static [crate::FilterField], key: &str| {
            fields
                .iter()
                .find(|field| field.key == key)
                .map(|field| field.family)
        };

        // Booleans take one value rather than a set.
        assert_eq!(family(User::FIELDS, "admin"), Some(FieldFamily::Boolean));
        // A variable's value compares on its serialized text and carries no operations.
        assert_eq!(
            family(Variable::FIELDS, "value"),
            Some(FieldFamily::JsonValue)
        );
        assert!(
            Variable::FIELDS
                .iter()
                .find(|field| field.key == "value")
                .is_some_and(|field| field.operations.is_empty())
        );
        // A variable's address takes selectors, a workspace's scope does not.
        assert_eq!(
            family(Variable::FIELDS, "address"),
            Some(FieldFamily::Address)
        );
        assert_eq!(
            family(Workspace::FIELDS, "scope"),
            Some(FieldFamily::PlainAddress)
        );
        // Names bring the text operations, prefixed by their key.
        let operations: Vec<&str> = Variable::FIELDS
            .iter()
            .find(|field| field.key == "name")
            .map(|field| field.operations.iter().map(|one| one.key).collect())
            .unwrap();
        assert_eq!(
            operations,
            vec!["name_contains", "name_prefix", "name_suffix"]
        );
    }

    #[test]
    fn entities_serialize_like_the_api() {
        let workspace = Workspace {
            id: "0198c0de-0000-7000-8000-000000000001".parse().unwrap(),
            name: "console".to_string(),
            scope: Address::parse("~").unwrap(),
            owner_id: None,
            show_when_logged_out: false,
            data: Map::new(),
        };
        assert_eq!(
            serde_json::to_string(&workspace).unwrap(),
            "{\"id\":\"0198c0de-0000-7000-8000-000000000001\",\"name\":\"console\",\
             \"scope\":\"~\",\"owner_id\":null,\"show_when_logged_out\":false,\"data\":{}}"
        );
        assert_eq!(
            workspace.csv_cells(),
            vec![
                Some("0198c0de-0000-7000-8000-000000000001".to_string()),
                Some("console".to_string()),
                Some("~".to_string()),
                None,
                Some("false".to_string()),
                Some("{}".to_string()),
            ]
        );
    }

    #[test]
    fn a_variable_value_renders_as_the_row_extraction_writes_it() {
        let variable = |value: Value| Variable {
            address: Address::parse("@a").unwrap(),
            name: "x".to_string(),
            value,
        };

        // An atom crosses a cell as itself, a structure as its JSON text.
        let cell = |value: Value| variable(value).csv_cells()[2].clone();

        assert_eq!(cell(Value::Bool(true)).as_deref(), Some("true"));
        assert_eq!(cell(5.into()).as_deref(), Some("5"));
        assert_eq!(cell("text".into()).as_deref(), Some("text"));
        assert_eq!(
            cell(serde_json::json!({"k": 1})).as_deref(),
            Some("{\"k\":1}")
        );
        // A null value has no cell, which renders as an empty one.
        assert_eq!(cell(Value::Null), None);
    }
}
