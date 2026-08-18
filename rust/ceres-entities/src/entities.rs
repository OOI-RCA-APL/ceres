//! The non-record entities the CLI manages.
//!
//! Users, variables, settings, and workspaces are small tables an operator reads and
//! edits directly, unlike the record tables components fill. Each struct's serialized
//! form is the wire format for it, field order included so a native dump and a
//! materialized one render the same bytes.
//!
//! The filterable surface derives from these structs the way the records' does. Two
//! markers keep the derive honest where the Python filter and the column list disagree.
//! `skip` drops a column the filter does not expose, a user's password hash among them,
//! and `plain` takes a workspace's scope out of the selector grammar.

use ceres_macros::{FilterValues, Filterable};
use enum_dispatch::enum_dispatch;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::address::Address;
use crate::records::RenderRows;

/// What kind of thing a permission grant applies to.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, FilterValues)]
#[serde(rename_all = "lowercase")]
pub enum PermissionTargetType {
    /// One component, named by address.
    Component,
    /// Every component carrying a tag.
    Tag,
    /// Every component, with an empty target string.
    All,
}

/// What a grant lets its holder do with the target.
///
/// The levels are a strict hierarchy, each implying the ones below it, but a permission
/// filters on the level by equality rather than by rank so the family here is a closed
/// set of values rather than an ordered one.
///
/// Python's `ComponentAccessLevel` carries a fourth level, `deny`, which a component
/// declares as its own default and which means the absence of a grant. A row cannot hold
/// it, the permission tables check for these three, so it is not a level here either.
/// Leaving it out makes a create naming it fail at read time rather than as a database
/// constraint violation.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, FilterValues)]
#[serde(rename_all = "lowercase")]
pub enum GrantLevel {
    View,
    Operate,
    Manage,
}

/// An operator account.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct User {
    pub id: Uuid,
    pub username: String,
    /// The account's email address, whose operations fold case the way the Python
    /// filter's do.
    ///
    /// Equality normalizes first because the Python model types the field as a
    /// validated address and so compares a normalized value against a normalized column.
    /// An address outside the subset the normalizer understands delegates rather than
    /// comparing unnormalized.
    #[filterable(email, insensitive)]
    pub email: String,
    /// The Argon2 hash of the account's password.
    ///
    /// The CLI prints it since an operator running these commands already holds the
    /// database credentials and the value is a hash rather than a recoverable secret.
    /// It is not filterable, and the Python filter does not expose it either.
    #[filterable(skip, python = "Password | PasswordHash")]
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

/// A console layout a user has edited but not yet published.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct WorkspaceEdit {
    pub user_id: Uuid,
    pub workspace_id: Uuid,
    /// The draft layout, stored like a workspace's own and filterable the same way,
    /// which is to say not at all.
    #[filterable(skip)]
    pub data: Map<String, Value>,
}

/// A named collection of users, which permissions can be granted to as a whole.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Group {
    pub id: Uuid,
    pub name: String,
    /// Free text describing the group, which the Python filter does not expose.
    #[filterable(skip)]
    pub description: String,
}

/// One user's membership of one group.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct GroupMembership {
    pub user_id: Uuid,
    pub group_id: Uuid,
}

/// A grant made directly to a user.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct UserPermission {
    pub user_id: Uuid,
    pub target_type: PermissionTargetType,
    /// What the grant covers, an address or a tag, and empty when it covers everything.
    ///
    /// It filters by equality alone. A substring of an address or a tag names nothing
    /// so the Python filter gives the field no operation keys and neither does this.
    #[filterable(no_operations)]
    pub target: String,
    pub level: GrantLevel,
}

/// A grant made to a group, which reaches every user in it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct GroupPermission {
    pub group_id: Uuid,
    pub target_type: PermissionTargetType,
    #[filterable(no_operations)]
    pub target: String,
    pub level: GrantLevel,
}

impl PermissionTargetType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Component => "component",
            Self::Tag => "tag",
            Self::All => "all",
        }
    }

    /// Read a target type from its stored text.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "component" => Some(Self::Component),
            "tag" => Some(Self::Tag),
            "all" => Some(Self::All),
            _ => None,
        }
    }
}

impl GrantLevel {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::View => "view",
            Self::Operate => "operate",
            Self::Manage => "manage",
        }
    }

    /// Read a grant level from its stored text.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "view" => Some(Self::View),
            "operate" => Some(Self::Operate),
            "manage" => Some(Self::Manage),
            _ => None,
        }
    }
}

/// The entities of one query result, all of a single type.
#[enum_dispatch(RenderRows)]
#[derive(Clone, Debug, PartialEq)]
pub enum Entities {
    Users(Vec<User>),
    Variables(Vec<Variable>),
    Settings(Vec<Setting>),
    Workspaces(Vec<Workspace>),
    WorkspaceEdits(Vec<WorkspaceEdit>),
    Groups(Vec<Group>),
    GroupMemberships(Vec<GroupMembership>),
    UserPermissions(Vec<UserPermission>),
    GroupPermissions(Vec<GroupPermission>),
}

impl Entities {
    /// The number of entities held.
    pub fn len(&self) -> usize {
        RenderRows::len(self)
    }

    /// Whether no entities are held.
    pub fn is_empty(&self) -> bool {
        RenderRows::is_empty(self)
    }

    /// Serialize the first entity in the wire format, `null` when none matched.
    pub fn to_json_first(&self) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_first(self)
    }

    /// Serialize the entities as one JSON array in the API's wire format.
    pub fn to_json_array(&self) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_array(self)
    }

    /// Serialize the entities as JSON lines in the wire format, one per line.
    pub fn to_json_lines(&self) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_lines(self)
    }

    /// Render the entities as CSV lines, under a header row unless suppressed.
    pub fn to_csv_lines(&self, header: bool) -> serde_json::Result<String> {
        RenderRows::to_csv_lines(self, header)
    }

    /// Serialize a field projection of the entities as JSON lines, aliased objects.
    pub fn to_json_lines_projected(
        &self,
        fields: &[(String, String)],
    ) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_lines_projected(self, fields)
    }

    /// Render a field projection of the entities as CSV lines, an alias header row
    /// unless suppressed.
    pub fn to_csv_lines_projected(
        &self,
        fields: &[(String, String)],
        header: bool,
    ) -> serde_json::Result<String> {
        RenderRows::to_csv_lines_projected(self, fields, header)
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
    fn columns_carry_their_docs_and_python_overrides() {
        // The generated Python models take their docstrings and refined types from
        // here, so an empty doc or a dropped override breaks model generation quietly.
        let password = User::COLUMNS
            .iter()
            .find(|field| field.key == "password")
            .expect("the password column exists");
        assert_eq!(password.python, Some("Password | PasswordHash"));
        assert!(password.doc.starts_with("The Argon2 hash"));

        let admin = User::COLUMNS
            .iter()
            .find(|field| field.key == "admin")
            .expect("the admin column exists");
        assert_eq!(admin.python, None);
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
        // A null owner renders as an empty cell, a boolean as its JSON text, and the
        // payload as its own JSON.
        assert_eq!(
            crate::records::to_csv_lines(&[workspace], true).unwrap(),
            "id,name,scope,owner_id,show_when_logged_out,data\n\
             0198c0de-0000-7000-8000-000000000001,console,~,,false,{}\n"
        );
    }

    #[test]
    fn a_variable_value_renders_as_the_row_extraction_writes_it() {
        let variable = |value: Value| Variable {
            address: Address::parse("@a").unwrap(),
            name: "x".to_string(),
            value,
        };

        // An atom crosses a cell as itself, a structure as its JSON text, quoted for
        // the punctuation it carries.
        let row = |value: Value| crate::records::to_csv_lines(&[variable(value)], false).unwrap();

        assert_eq!(row(Value::Bool(true)), "@a,x,true\n");
        assert_eq!(row(5.into()), "@a,x,5\n");
        assert_eq!(row("text".into()), "@a,x,text\n");
        assert_eq!(row(serde_json::json!({"k": 1})), "@a,x,\"{\"\"k\"\":1}\"\n");
        // A null value has no cell, which renders as an empty one.
        assert_eq!(row(Value::Null), "@a,x,\n");
    }
}
