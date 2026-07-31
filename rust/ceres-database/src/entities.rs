//! Entity queries and row decoding for the non-record tables.
//!
//! Users, variables, settings, and workspaces are small tables an operator reads and
//! edits, so the win here is startup rather than throughput. They share the record
//! path's compiler through their schemas, and differ from it in three ways the record
//! tables never exercise. Two of them carry composite primary keys, their orderings
//! are their own rather than a timestamp's, and three of their filter keys match a
//! shape of a column rather than its value.

use ceres_entities::{Address, Entities, Setting, User, Variable, Workspace};
use sea_query::{Alias, Asterisk, Order, Query, SelectStatement};
use serde_json::Value;
use sqlx::Row;
use sqlx::postgres::PgRow;
use sqlx::sqlite::SqliteRow;
use uuid::Uuid;

use crate::records::{Computed, Schema, Shape};
use crate::store::Error;

/// One of the tables the entity commands manage.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EntityTable {
    Users,
    Variables,
    Settings,
    Workspaces,
}

impl EntityTable {
    /// Select an entity table by name.
    pub fn parse(table: &str) -> Result<Self, Error> {
        match table {
            "users" => Ok(Self::Users),
            "variables" => Ok(Self::Variables),
            "settings" => Ok(Self::Settings),
            "workspaces" => Ok(Self::Workspaces),
            other => Err(Error::UnknownTable(other.to_string())),
        }
    }

    pub(crate) fn name(&self) -> &'static str {
        match self {
            Self::Users => "users",
            Self::Variables => "variables",
            Self::Settings => "settings",
            Self::Workspaces => "workspaces",
        }
    }

    /// What the compiler needs to know about this table.
    ///
    /// The default orderings and key columns come from the Python filters' own
    /// `_get_default_order` and each row's primary key, and the computed predicates
    /// from the filter fields that have no column behind them.
    pub(crate) fn schema(&self) -> Schema {
        use ceres_entities::Filterable;

        match self {
            Self::Users => Schema {
                name: self.name(),
                fields: User::FIELDS,
                columns: User::COLUMNS,
                // An email compares after the Python model has normalized it, which is
                // the `email_validator` library's own normalization, so equality on one
                // stays where that library is.
                delegated: &["email"],
                key: &["id"],
                fixed: &["id"],
                order: &["username"],
                computed: &[],
            },
            Self::Variables => Schema {
                name: self.name(),
                fields: Variable::FIELDS,
                columns: Variable::COLUMNS,
                delegated: &[],
                key: &["address", "name"],
                // A variable's name is assignable though it is half the key, its
                // address is not, which is what `VariableUpdate` declares.
                fixed: &["address"],
                order: &["address", "name"],
                computed: &[Computed {
                    key: "internal",
                    column: "name",
                    shape: Shape::Internal,
                }],
            },
            Self::Settings => Schema {
                name: self.name(),
                fields: Setting::FIELDS,
                columns: Setting::COLUMNS,
                delegated: &[],
                key: &["user_id", "name"],
                fixed: &["user_id"],
                order: &["name"],
                computed: &[],
            },
            Self::Workspaces => Schema {
                name: self.name(),
                fields: Workspace::FIELDS,
                columns: Workspace::COLUMNS,
                delegated: &[],
                key: &["id"],
                fixed: &["id"],
                order: &["name"],
                computed: &[
                    Computed {
                        key: "placed_on_engine",
                        column: "scope",
                        shape: Shape::Literal("~"),
                    },
                    Computed {
                        key: "owned",
                        column: "owner_id",
                        shape: Shape::Present,
                    },
                ],
            },
        }
    }

    /// Build the listing statement, ordered like the entity's own default.
    pub(crate) fn listing(&self, limit: Option<u64>, offset: Option<u64>) -> SelectStatement {
        let mut statement = Query::select();
        statement.column(Asterisk).from(Alias::new(self.name()));
        for column in self.schema().order {
            statement.order_by(Alias::new(*column), Order::Asc);
        }

        if let Some(limit) = limit {
            statement.limit(limit);
        }

        if let Some(offset) = offset {
            statement.offset(offset);
        }

        statement
    }

    pub(crate) fn empty(&self) -> Entities {
        match self {
            Self::Users => Entities::Users(Vec::new()),
            Self::Variables => Entities::Variables(Vec::new()),
            Self::Settings => Entities::Settings(Vec::new()),
            Self::Workspaces => Entities::Workspaces(Vec::new()),
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
    }
}

/// Decode rows for an entity table into natively-held entities.
pub(crate) trait DecodeEntities: Row + Sized {
    fn decode(table: EntityTable, rows: Vec<Self>) -> Result<Entities, Error>;
}

impl DecodeEntities for SqliteRow {
    fn decode(table: EntityTable, rows: Vec<Self>) -> Result<Entities, Error> {
        match table {
            EntityTable::Users => rows
                .iter()
                .map(|row| {
                    Ok(User {
                        id: sqlite_id(row, "id")?,
                        username: row.try_get("username")?,
                        email: row.try_get("email")?,
                        password: row.try_get("password")?,
                        admin: row.try_get("admin")?,
                        disabled: row.try_get("disabled")?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Users),
            EntityTable::Variables => rows
                .iter()
                .map(|row| {
                    Ok(Variable {
                        address: Address::trusted(row.try_get("address")?),
                        name: row.try_get("name")?,
                        value: sqlite_value(row)?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Variables),
            EntityTable::Settings => rows
                .iter()
                .map(|row| {
                    Ok(Setting {
                        user_id: sqlite_id(row, "user_id")?,
                        name: row.try_get("name")?,
                        value: sqlite_value(row)?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Settings),
            EntityTable::Workspaces => rows
                .iter()
                .map(|row| {
                    Ok(Workspace {
                        id: sqlite_id(row, "id")?,
                        name: row.try_get("name")?,
                        scope: Address::trusted(row.try_get("scope")?),
                        owner_id: sqlite_optional_id(row, "owner_id")?,
                        show_when_logged_out: row.try_get("show_when_logged_out")?,
                        data: crate::records::json_text(row.try_get("data")?)?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Workspaces),
        }
    }
}

impl DecodeEntities for PgRow {
    fn decode(table: EntityTable, rows: Vec<Self>) -> Result<Entities, Error> {
        match table {
            EntityTable::Users => rows
                .iter()
                .map(|row| {
                    Ok(User {
                        id: row.try_get("id")?,
                        username: row.try_get("username")?,
                        email: row.try_get("email")?,
                        password: row.try_get("password")?,
                        admin: row.try_get("admin")?,
                        disabled: row.try_get("disabled")?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Users),
            EntityTable::Variables => rows
                .iter()
                .map(|row| {
                    Ok(Variable {
                        address: Address::trusted(row.try_get("address")?),
                        name: row.try_get("name")?,
                        value: row.try_get("value")?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Variables),
            EntityTable::Settings => rows
                .iter()
                .map(|row| {
                    Ok(Setting {
                        user_id: row.try_get("user_id")?,
                        name: row.try_get("name")?,
                        value: row.try_get("value")?,
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Settings),
            EntityTable::Workspaces => rows
                .iter()
                .map(|row| {
                    Ok(Workspace {
                        id: row.try_get("id")?,
                        name: row.try_get("name")?,
                        scope: Address::trusted(row.try_get("scope")?),
                        owner_id: row.try_get("owner_id")?,
                        show_when_logged_out: row.try_get("show_when_logged_out")?,
                        data: match row.try_get("data")? {
                            Value::Object(map) => map,
                            other => {
                                return Err(Error::Decode(format!("{other} is not a JSON object")));
                            }
                        },
                    })
                })
                .collect::<Result<_, Error>>()
                .map(Entities::Workspaces),
        }
    }
}

/// Decode a SQLite ID column, stored as hyphenated UUID text.
fn sqlite_id(row: &SqliteRow, column: &str) -> Result<Uuid, Error> {
    let text: String = row.try_get(column)?;
    text.parse()
        .map_err(|_| Error::Decode(format!("{text:?} is not a UUID")))
}

/// Decode a nullable SQLite ID column.
fn sqlite_optional_id(row: &SqliteRow, column: &str) -> Result<Option<Uuid>, Error> {
    let Some(text) = row.try_get::<Option<String>, _>(column)? else {
        return Ok(None);
    };

    text.parse()
        .map(Some)
        .map_err(|_| Error::Decode(format!("{text:?} is not a UUID")))
}

/// Decode a SQLite value column, which holds arbitrary JSON.
///
/// The column is declared `JSON`, which carries none of SQLite's affinity keywords and
/// therefore takes NUMERIC affinity. The driver writes the JSON text, and the backend
/// converts whatever looks like a number back into one, so a variable holding `5` is
/// stored as an integer while one holding `true` stays text. Both decode here.
fn sqlite_value(row: &SqliteRow) -> Result<Value, Error> {
    let text = match row.try_get::<String, _>("value") {
        Ok(text) => text,
        Err(_) => match row.try_get::<Option<i64>, _>("value") {
            Ok(Some(number)) => return Ok(number.into()),
            // A null column is a null value, which a variable may hold.
            Ok(None) => return Ok(Value::Null),
            Err(_) => {
                let number: f64 = row.try_get("value")?;
                return serde_json::Number::from_f64(number)
                    .map(Value::Number)
                    .ok_or_else(|| Error::Decode(format!("{number} is not a JSON number")));
            }
        },
    };

    serde_json::from_str(&text).map_err(|error| Error::Decode(error.to_string()))
}

#[cfg(test)]
mod tests {
    use sea_query::SqliteQueryBuilder;

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
    fn listings_order_by_the_entity_default() {
        assert_eq!(
            EntityTable::Variables
                .listing(None, None)
                .to_string(SqliteQueryBuilder),
            "SELECT * FROM \"variables\" ORDER BY \"address\" ASC, \"name\" ASC"
        );
        assert_eq!(
            EntityTable::Users
                .listing(Some(5), None)
                .to_string(SqliteQueryBuilder),
            "SELECT * FROM \"users\" ORDER BY \"username\" ASC LIMIT 5"
        );
    }

    #[test]
    fn composite_keys_name_every_key_column() {
        assert_eq!(EntityTable::Variables.schema().key, &["address", "name"]);
        assert_eq!(EntityTable::Settings.schema().key, &["user_id", "name"]);
        assert_eq!(EntityTable::Workspaces.schema().key, &["id"]);
    }
}
