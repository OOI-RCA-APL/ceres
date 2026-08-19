//! Entity queries and row decoding for the non-record tables.
//!
//! Users, variables, settings, and workspaces are small tables an operator reads and
//! edits so the win here is startup rather than throughput. They share the record
//! path's compiler through their schemas, and differ from it in three ways the record
//! tables never exercise. Two of them carry composite primary keys, their orderings
//! are their own rather than a timestamp's, and three of their filter keys match a
//! shape of a column rather than its value.

use ceres_entities::{
    Address, Entities, GrantLevel, Group, GroupMembership, GroupPermission, PermissionTargetType,
    Setting, User, UserPermission, Variable, Workspace, WorkspaceEdit,
};

use crate::records::{Computed, FieldRead, FromRow, Schema, Shape, decoded};
use crate::store::Error;

/// One of the tables the entity commands manage.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityTable {
    Users,
    Variables,
    Settings,
    Workspaces,
    WorkspaceEdits,
    Groups,
    GroupMemberships,
    UserPermissions,
    GroupPermissions,
}

impl EntityTable {
    /// Select an entity table by name.
    pub fn parse(table: &str) -> Result<Self, Error> {
        match table {
            "users" => Ok(Self::Users),
            "variables" => Ok(Self::Variables),
            "settings" => Ok(Self::Settings),
            "workspaces" => Ok(Self::Workspaces),
            "workspace_edits" => Ok(Self::WorkspaceEdits),
            "groups" => Ok(Self::Groups),
            "group_memberships" => Ok(Self::GroupMemberships),
            "user_permissions" => Ok(Self::UserPermissions),
            "group_permissions" => Ok(Self::GroupPermissions),
            other => Err(Error::UnknownTable(other.to_string())),
        }
    }

    /// Every column the table stores, with the family that decides how it decodes.
    pub fn columns(&self) -> &'static [ceres_entities::FilterField] {
        self.schema().columns
    }

    pub fn name(&self) -> &'static str {
        match self {
            Self::Users => "users",
            Self::Variables => "variables",
            Self::Settings => "settings",
            Self::Workspaces => "workspaces",
            Self::WorkspaceEdits => "workspace_edits",
            Self::Groups => "groups",
            Self::GroupMemberships => "group_memberships",
            Self::UserPermissions => "user_permissions",
            Self::GroupPermissions => "group_permissions",
        }
    }

    /// What the compiler needs to know about this table.
    ///
    /// The default orderings match the Python filters', the key columns are each row's
    /// primary key, and the computed predicates come from the filter fields that have
    /// no column behind them.
    pub(crate) fn schema(&self) -> Schema {
        use ceres_entities::Filterable;

        match self {
            Self::Users => Schema {
                name: self.name(),
                entity: User::NAME,
                python_module: "ceres.user",
                fields: User::FIELDS,
                columns: User::COLUMNS,
                doc: User::DOC,
                delegated: &[],
                key: &["id"],
                fixed: &["id"],
                order: &["username"],
                computed: &[],
            },
            Self::Variables => Schema {
                name: self.name(),
                entity: Variable::NAME,
                python_module: "ceres.variable",
                fields: Variable::FIELDS,
                columns: Variable::COLUMNS,
                doc: Variable::DOC,
                delegated: &[],
                key: &["address", "name"],
                // A variable's name is settable though it is half the key, its
                // address is not, which `VariableUpdate` declares.
                fixed: &["address"],
                order: &["address", "name"],
                computed: &[Computed {
                    key: "internal",
                    column: "name",
                    shape: Shape::Internal,
                    doc: "Filter variables based on whether they are internal or not. \
                          Internal variables are those that start with and end with two \
                          underscores, for example `__enabled__`. If `None`, both \
                          internal and non-internal variables will be matched.",
                }],
            },
            Self::Settings => Schema {
                name: self.name(),
                entity: Setting::NAME,
                python_module: "ceres.setting",
                fields: Setting::FIELDS,
                columns: Setting::COLUMNS,
                doc: Setting::DOC,
                delegated: &[],
                key: &["user_id", "name"],
                fixed: &["user_id"],
                order: &["name"],
                computed: &[],
            },
            Self::Workspaces => Schema {
                name: self.name(),
                entity: Workspace::NAME,
                python_module: "ceres.workspace",
                fields: Workspace::FIELDS,
                columns: Workspace::COLUMNS,
                doc: Workspace::DOC,
                delegated: &[],
                key: &["id"],
                fixed: &["id"],
                order: &["name"],
                computed: &[
                    Computed {
                        key: "placed_on_engine",
                        column: "scope",
                        shape: Shape::Literal("~"),
                        doc: "Filter by whether the workspace is placed on the engine \
                              root rather than a component.",
                    },
                    Computed {
                        key: "owned",
                        column: "owner_id",
                        shape: Shape::Present,
                        doc: "Filter by whether the workspace is private to an owner \
                              at all.",
                    },
                ],
            },
            Self::WorkspaceEdits => Schema {
                name: self.name(),
                entity: WorkspaceEdit::NAME,
                python_module: "ceres.workspace",
                fields: WorkspaceEdit::FIELDS,
                columns: WorkspaceEdit::COLUMNS,
                doc: WorkspaceEdit::DOC,
                delegated: &[],
                key: &["workspace_id", "user_id"],
                // The draft data is the only thing an edit can change, which
                // `WorkspaceEditUpdate` declares.
                fixed: &["workspace_id", "user_id"],
                order: &["user_id", "workspace_id"],
                computed: &[],
            },
            Self::Groups => Schema {
                name: self.name(),
                entity: Group::NAME,
                python_module: "ceres.group",
                fields: Group::FIELDS,
                columns: Group::COLUMNS,
                doc: Group::DOC,
                delegated: &[],
                key: &["id"],
                fixed: &["id"],
                order: &["name"],
                computed: &[],
            },
            Self::GroupMemberships => Schema {
                name: self.name(),
                entity: GroupMembership::NAME,
                python_module: "ceres.group",
                fields: GroupMembership::FIELDS,
                columns: GroupMembership::COLUMNS,
                doc: GroupMembership::DOC,
                delegated: &[],
                key: &["user_id", "group_id"],
                // A membership is created or deleted and never edited so both of its
                // columns are fixed and `GroupMembershipUpdate` carries no fields.
                fixed: &["user_id", "group_id"],
                order: &["user_id", "group_id"],
                computed: &[],
            },
            Self::UserPermissions => Schema {
                name: self.name(),
                entity: UserPermission::NAME,
                python_module: "ceres.permission",
                fields: UserPermission::FIELDS,
                columns: UserPermission::COLUMNS,
                doc: UserPermission::DOC,
                delegated: &[],
                key: &["user_id", "target_type", "target"],
                // The level is what a grant can be raised or lowered to. Changing who or
                // what it covers would be a different grant.
                fixed: &["user_id", "target_type", "target"],
                order: &["user_id", "target_type", "target"],
                computed: &[],
            },
            Self::GroupPermissions => Schema {
                name: self.name(),
                entity: GroupPermission::NAME,
                python_module: "ceres.permission",
                fields: GroupPermission::FIELDS,
                columns: GroupPermission::COLUMNS,
                doc: GroupPermission::DOC,
                delegated: &[],
                key: &["group_id", "target_type", "target"],
                fixed: &["group_id", "target_type", "target"],
                order: &["group_id", "target_type", "target"],
                computed: &[],
            },
        }
    }

    pub(crate) fn empty(&self) -> Entities {
        match self {
            Self::Users => Entities::Users(Vec::new()),
            Self::Variables => Entities::Variables(Vec::new()),
            Self::Settings => Entities::Settings(Vec::new()),
            Self::Workspaces => Entities::Workspaces(Vec::new()),
            Self::WorkspaceEdits => Entities::WorkspaceEdits(Vec::new()),
            Self::Groups => Entities::Groups(Vec::new()),
            Self::GroupMemberships => Entities::GroupMemberships(Vec::new()),
            Self::UserPermissions => Entities::UserPermissions(Vec::new()),
            Self::GroupPermissions => Entities::GroupPermissions(Vec::new()),
        }
    }
}

/// The table a batch of entities belongs to.
pub(crate) fn table_of(entities: &Entities) -> EntityTable {
    match entities {
        Entities::Users(_) => EntityTable::Users,
        Entities::Variables(_) => EntityTable::Variables,
        Entities::Settings(_) => EntityTable::Settings,
        Entities::Workspaces(_) => EntityTable::Workspaces,
        Entities::WorkspaceEdits(_) => EntityTable::WorkspaceEdits,
        Entities::Groups(_) => EntityTable::Groups,
        Entities::GroupMemberships(_) => EntityTable::GroupMemberships,
        Entities::UserPermissions(_) => EntityTable::UserPermissions,
        Entities::GroupPermissions(_) => EntityTable::GroupPermissions,
    }
}

impl FromRow for User {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(User {
            id: row.uuid("id")?,
            username: row.text("username")?,
            email: row.text("email")?,
            password: row.text("password")?,
            admin: row.boolean("admin")?,
            disabled: row.boolean("disabled")?,
        })
    }
}

impl FromRow for Variable {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(Variable {
            address: Address::trusted(row.text("address")?),
            name: row.text("name")?,
            value: row.json("value")?,
        })
    }
}

impl FromRow for Setting {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(Setting {
            user_id: row.uuid("user_id")?,
            name: row.text("name")?,
            value: row.json("value")?,
        })
    }
}

impl FromRow for Workspace {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(Workspace {
            id: row.uuid("id")?,
            name: row.text("name")?,
            // Addresses were validated when written so the value is trusted on the
            // way out the way a record's address is.
            scope: Address::trusted(row.text("scope")?),
            owner_id: row.optional_uuid("owner_id")?,
            show_when_logged_out: row.boolean("show_when_logged_out")?,
            data: row.object("data", "a workspace's data")?,
        })
    }
}

impl FromRow for WorkspaceEdit {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(WorkspaceEdit {
            user_id: row.uuid("user_id")?,
            workspace_id: row.uuid("workspace_id")?,
            data: row.object("data", "a workspace edit's data")?,
        })
    }
}

impl FromRow for Group {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(Group {
            id: row.uuid("id")?,
            name: row.text("name")?,
            description: row.text("description")?,
        })
    }
}

impl FromRow for GroupMembership {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(GroupMembership {
            user_id: row.uuid("user_id")?,
            group_id: row.uuid("group_id")?,
        })
    }
}

impl FromRow for UserPermission {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(UserPermission {
            user_id: row.uuid("user_id")?,
            target_type: target_type(row.text("target_type")?)?,
            target: row.text("target")?,
            level: access_level(row.text("level")?)?,
        })
    }
}

impl FromRow for GroupPermission {
    fn from_row<R: FieldRead>(row: &R) -> Result<Self, Error> {
        Ok(GroupPermission {
            group_id: row.uuid("group_id")?,
            target_type: target_type(row.text("target_type")?)?,
            target: row.text("target")?,
            level: access_level(row.text("level")?)?,
        })
    }
}

/// Decode a fetched result set for an entity table into natively-held entities.
pub(crate) fn decode<R: FieldRead>(table: EntityTable, rows: Vec<R>) -> Result<Entities, Error> {
    match table {
        EntityTable::Users => decoded(&rows).map(Entities::Users),
        EntityTable::Variables => decoded(&rows).map(Entities::Variables),
        EntityTable::Settings => decoded(&rows).map(Entities::Settings),
        EntityTable::Workspaces => decoded(&rows).map(Entities::Workspaces),
        EntityTable::WorkspaceEdits => decoded(&rows).map(Entities::WorkspaceEdits),
        EntityTable::Groups => decoded(&rows).map(Entities::Groups),
        EntityTable::GroupMemberships => decoded(&rows).map(Entities::GroupMemberships),
        EntityTable::UserPermissions => decoded(&rows).map(Entities::UserPermissions),
        EntityTable::GroupPermissions => decoded(&rows).map(Entities::GroupPermissions),
    }
}

/// Decode a permission's target type from the text the column stores.
fn target_type(value: String) -> Result<PermissionTargetType, Error> {
    PermissionTargetType::parse(&value)
        .ok_or_else(|| Error::Decode(format!("{value:?} is not a permission target type")))
}

/// Decode a permission's access level from the text the column stores.
fn access_level(value: String) -> Result<GrantLevel, Error> {
    GrantLevel::parse(&value)
        .ok_or_else(|| Error::Decode(format!("{value:?} is not an access level")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tables_parse_by_name() {
        assert_eq!(
            EntityTable::parse("variables").unwrap(),
            EntityTable::Variables
        );
        assert!(EntityTable::parse("messages").is_err());
    }

    #[test]
    fn composite_keys_name_every_key_column() {
        assert_eq!(EntityTable::Variables.schema().key, &["address", "name"]);
        assert_eq!(EntityTable::Settings.schema().key, &["user_id", "name"]);
        assert_eq!(EntityTable::Workspaces.schema().key, &["id"]);
    }
}
