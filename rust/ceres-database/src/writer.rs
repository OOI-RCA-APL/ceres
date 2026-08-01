//! Native record writes.
//!
//! A flush of buffered records writes here as one transaction of multi-row upserts, built
//! with sea-query per backend. Statement shape mirrors the query layer's writer, an
//! `INSERT ... ON CONFLICT (id) DO UPDATE` setting every non-key column from `excluded`.

use std::sync::Arc;
use std::time::Duration;

use ceres_entities::{
    Alert, Entities, Group, GroupMembership, GroupPermission, LogEntry, Message, MessageDirection,
    Particle, Records, Setting, User, UserPermission, Variable, Workspace, WorkspaceEdit,
};
use sea_query::{Alias, InsertStatement, OnConflict, Query, SimpleExpr};
use sqlx::postgres::PgPoolOptions;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};

use crate::backend::{Engine, PostgresEngine, SqliteEngine, Writing};
use crate::records::RecordTable;
use crate::store::{Error, Parameter};
use crate::turso::TursoBackend;

/// How a backend expects record values bound.
#[derive(Clone, Copy, PartialEq)]
pub(crate) enum Dialect {
    /// Timestamps, UUIDs, and JSON payloads stored as text.
    Sqlite,
    /// Native driver types throughout.
    Postgres,
}

/// A natively-connected writer for record entities.
///
/// Connections open lazily on first use. The SQLite pool holds a single connection, the
/// backend serializes writers anyway and one connection avoids lock churn against the
/// query layer's own pool on the same file.
pub struct RecordWriter {
    engine: Arc<dyn Engine>,
}

impl RecordWriter {
    /// Open a writer over a SQLite database file.
    ///
    /// The connection matches the query layer's, the same busy timeout and foreign key
    /// enforcement, and never creates a missing file, the file's lifecycle belongs to the
    /// Python layer.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life. The `init` statements are the store's to run, that being
    /// the engine a database opens for itself.
    pub fn sqlite(
        path: &str,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Result<Self, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .busy_timeout(Duration::from_secs(30))
            .foreign_keys(true);
        let pool = crate::store::lifecycle(
            SqlitePoolOptions::new().max_connections(1),
            Vec::new(),
            on_connect,
            on_close,
        )
        .connect_lazy_with(options);
        Ok(Self {
            engine: Arc::new(SqliteEngine(pool)),
        })
    }

    /// Open a writer over a PostgreSQL database, with per-connection server settings.
    #[allow(clippy::too_many_arguments)]
    pub fn postgres(
        host: &str,
        port: Option<u16>,
        database: &str,
        user: &str,
        password: Option<&str>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Result<Self, Error> {
        let options = crate::store::postgres_options(
            host, port, database, user, password, settings, parameters,
        )?;
        let pool = crate::store::lifecycle(PgPoolOptions::new(), Vec::new(), on_connect, on_close)
            .connect_lazy_with(options);
        Ok(Self {
            engine: Arc::new(PostgresEngine(pool)),
        })
    }

    /// Open a writer over a Turso database file.
    ///
    /// When `mvcc` is set, each connection enables MVCC journaling to match the store's
    /// connections on the same file, and a flush then opens a transaction that may
    /// overlap other writers.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life. The `init` statements are the store's to run, that being
    /// the engine a database opens for itself.
    pub fn turso(path: &str, mvcc: bool, on_connect: Vec<String>, on_close: Vec<String>) -> Self {
        Self {
            engine: Arc::new(TursoBackend::new(
                path,
                mvcc,
                Vec::new(),
                on_connect,
                on_close,
            )),
        }
    }

    /// Whether a flush can overlap another writer on this database.
    ///
    /// `false` says a flush is serialized whatever it asked for, so it cannot lose a race
    /// at commit and a caller never has to write it again.
    ///
    /// Nothing above this reads it yet. It exists so that asking for a concurrent
    /// transaction is answerable rather than silently ignored, and it is what the tests
    /// assert the setting against.
    pub fn overlaps_writers(&self) -> bool {
        self.engine.overlaps_writers()
    }

    /// Upsert every batch in one transaction.
    ///
    /// A flush is atomic, either every record in every batch lands or none do.
    ///
    /// The transaction asks to overlap other writers, because this is the one write path
    /// that is frequent, independent, and safe to run again. Records are keyed by an ID
    /// their producer minted, so two flushes rarely touch the same row, and a flush that
    /// loses a race at commit is requeued by the buffer above and written next time. A
    /// backend that cannot overlap runs it serialized instead, which is what
    /// [`Self::overlaps_writers`] reports.
    pub async fn upsert(&self, batches: Vec<Records>) -> Result<(), Error> {
        let dialect = match self.engine.dialect() {
            crate::filter::SqlDialect::Postgres => Dialect::Postgres,
            crate::filter::SqlDialect::SqliteText => Dialect::Sqlite,
        };
        let mut statements = batches.iter().filter_map(|batch| {
            upsert_statement(batch, dialect).map(|statement| Ok((statement, batch.len())))
        });

        // The count is what was handed in rather than what landed, `upsert_statement`
        // dropping all but the last of any repeated ID, and it is dropped here anyway. A
        // flush is told to write what it holds rather than asked how much of it was new.
        // The load path is what actually answers with this number, over batches that
        // carry no duplicates.
        self.engine
            .insert_all(Writing::Concurrent, &mut statements)
            .await?;
        Ok(())
    }
}

/// Build the multi-row upsert for one batch, or `None` when the batch is empty.
fn upsert_statement(records: &Records, dialect: Dialect) -> Option<InsertStatement> {
    let rows = match records {
        Records::Messages(messages) => dedupe_last(messages, |message| message.id)
            .map(|message| message_values(message, dialect))
            .collect::<Vec<_>>(),
        Records::Particles(particles) => dedupe_last(particles, |particle| particle.id)
            .map(|particle| particle_values(particle, dialect))
            .collect(),
        Records::Alerts(alerts) => dedupe_last(alerts, |alert| alert.id)
            .map(|alert| alert_values(alert, dialect))
            .collect(),
        Records::LogEntries(entries) => dedupe_last(entries, |entry| entry.id)
            .map(|entry| entry_values(entry, dialect))
            .collect(),
    };

    let table = crate::records::table_of(records);
    let mut statement = insert_into(table, rows)?;

    // Every non-key column updates from the excluded row, mirroring the query layer's
    // upsert so a rewritten record replaces its earlier form.
    let mut conflict = OnConflict::column(Alias::new("id"));
    conflict.update_columns(
        columns(table)
            .iter()
            .filter(|&&column| column != "id")
            .map(|&column| Alias::new(column)),
    );
    statement.on_conflict(conflict);

    Some(statement)
}

/// Bind every record in a batch, in file order, for a bulk load.
///
/// Unlike a flush, a load never collapses duplicate keys. The Python command binds each
/// row it read, so a file naming one key twice reaches the database twice and the
/// conflict mode decides what happens.
pub(crate) fn load_statement(records: &Records, dialect: Dialect) -> Option<InsertStatement> {
    let rows = match records {
        Records::Messages(messages) => messages
            .iter()
            .map(|message| message_values(message, dialect))
            .collect::<Vec<_>>(),
        Records::Particles(particles) => particles
            .iter()
            .map(|particle| particle_values(particle, dialect))
            .collect(),
        Records::Alerts(alerts) => alerts
            .iter()
            .map(|alert| alert_values(alert, dialect))
            .collect(),
        Records::LogEntries(entries) => entries
            .iter()
            .map(|entry| entry_values(entry, dialect))
            .collect(),
    };

    insert_into(crate::records::table_of(records), rows)
}

/// Bind every entity in a batch, in file order, for a bulk load or a create.
pub(crate) fn entity_load_statement(
    entities: &Entities,
    dialect: Dialect,
) -> Option<InsertStatement> {
    let rows = match entities {
        Entities::Users(users) => users
            .iter()
            .map(|user| user_values(user, dialect))
            .collect::<Vec<_>>(),
        Entities::Variables(variables) => variables
            .iter()
            .map(|variable| variable_values(variable, dialect))
            .collect(),
        Entities::Settings(settings) => settings
            .iter()
            .map(|setting| setting_values(setting, dialect))
            .collect(),
        Entities::Workspaces(workspaces) => workspaces
            .iter()
            .map(|workspace| workspace_values(workspace, dialect))
            .collect(),
        Entities::WorkspaceEdits(edits) => edits
            .iter()
            .map(|edit| workspace_edit_values(edit, dialect))
            .collect(),
        Entities::Groups(groups) => groups
            .iter()
            .map(|group| group_values(group, dialect))
            .collect(),
        Entities::GroupMemberships(memberships) => memberships
            .iter()
            .map(|membership| group_membership_values(membership, dialect))
            .collect(),
        Entities::UserPermissions(permissions) => permissions
            .iter()
            .map(|permission| user_permission_values(permission, dialect))
            .collect(),
        Entities::GroupPermissions(permissions) => permissions
            .iter()
            .map(|permission| group_permission_values(permission, dialect))
            .collect(),
    };

    open_insert(
        crate::entities::table_of(entities).schema().name,
        entity_columns(entities),
        rows,
    )
}

/// The columns an entity batch binds, in the order its value builder writes them.
pub(crate) fn entity_columns(entities: &Entities) -> &'static [&'static str] {
    match entities {
        Entities::Users(_) => &["id", "username", "email", "password", "admin", "disabled"],
        Entities::Variables(_) => &["address", "name", "value"],
        Entities::Settings(_) => &["user_id", "name", "value"],
        Entities::Workspaces(_) => &[
            "id",
            "name",
            "scope",
            "owner_id",
            "show_when_logged_out",
            "data",
        ],
        Entities::WorkspaceEdits(_) => &["user_id", "workspace_id", "data"],
        Entities::Groups(_) => &["id", "name", "description"],
        Entities::GroupMemberships(_) => &["user_id", "group_id"],
        Entities::UserPermissions(_) => &["user_id", "target_type", "target", "level"],
        Entities::GroupPermissions(_) => &["group_id", "target_type", "target", "level"],
    }
}

fn user_values(user: &User, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(user.id, dialect),
        user.username.clone().into(),
        user.email.clone().into(),
        user.password.clone().into(),
        user.admin.into(),
        user.disabled.into(),
    ]
}

fn variable_values(variable: &Variable, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        variable.address.as_str().into(),
        variable.name.clone().into(),
        bare_json_value(&variable.value, dialect),
    ]
}

fn setting_values(setting: &Setting, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(setting.user_id, dialect),
        setting.name.clone().into(),
        bare_json_value(&setting.value, dialect),
    ]
}

fn workspace_values(workspace: &Workspace, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(workspace.id, dialect),
        workspace.name.clone().into(),
        workspace.scope.as_str().into(),
        match workspace.owner_id {
            Some(owner) => id_value(owner, dialect),
            None => SimpleExpr::Keyword(sea_query::Keyword::Null),
        },
        workspace.show_when_logged_out.into(),
        json_value(&workspace.data, dialect),
    ]
}

fn workspace_edit_values(edit: &WorkspaceEdit, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(edit.user_id, dialect),
        id_value(edit.workspace_id, dialect),
        json_value(&edit.data, dialect),
    ]
}

fn group_values(group: &Group, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(group.id, dialect),
        group.name.clone().into(),
        group.description.clone().into(),
    ]
}

fn group_membership_values(membership: &GroupMembership, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(membership.user_id, dialect),
        id_value(membership.group_id, dialect),
    ]
}

fn user_permission_values(permission: &UserPermission, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(permission.user_id, dialect),
        permission.target_type.as_str().into(),
        permission.target.clone().into(),
        permission.level.as_str().into(),
    ]
}

fn group_permission_values(permission: &GroupPermission, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(permission.group_id, dialect),
        permission.target_type.as_str().into(),
        permission.target.clone().into(),
        permission.level.as_str().into(),
    ]
}

/// Bind a bare JSON value, stored as its text on the SQLite family.
fn bare_json_value(value: &serde_json::Value, dialect: Dialect) -> SimpleExpr {
    json_text(&value.to_string(), dialect)
}

/// Open an insert over a table's columns, `None` when there is nothing to bind.
fn insert_into(table: RecordTable, rows: Vec<Vec<SimpleExpr>>) -> Option<InsertStatement> {
    open_insert(table.name(), columns(table), rows)
}

/// Open an insert over named columns, `None` when there is nothing to bind.
fn open_insert(
    table: &str,
    columns: &[&str],
    rows: Vec<Vec<SimpleExpr>>,
) -> Option<InsertStatement> {
    if rows.is_empty() {
        return None;
    }

    let mut statement = Query::insert();
    statement
        .into_table(Alias::new(table))
        .columns(columns.iter().map(|&column| Alias::new(column)));
    for row in rows {
        statement.values_panic(row);
    }

    Some(statement)
}

/// A table's stored columns, in the order rows bind them.
pub(crate) fn columns(table: RecordTable) -> &'static [&'static str] {
    match table {
        RecordTable::Messages => &[
            "id",
            "address",
            "timestamp",
            "connection",
            "direction",
            "data",
        ],
        RecordTable::Particles => &["id", "address", "timestamp", "type", "data"],
        RecordTable::Alerts => &["id", "address", "timestamp", "level", "type", "data"],
        RecordTable::Logs => &["id", "address", "timestamp", "level", "content"],
    }
}

fn message_values(message: &Message, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(message.id, dialect),
        message.address.as_str().into(),
        timestamp_value(&message.timestamp, dialect),
        message.connection.clone().into(),
        match message.direction {
            MessageDirection::Send => "send".into(),
            MessageDirection::Receive => "receive".into(),
        },
        message.data.clone().into(),
    ]
}

fn particle_values(particle: &Particle, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(particle.id, dialect),
        particle.address.as_str().into(),
        timestamp_value(&particle.timestamp, dialect),
        particle.kind.clone().into(),
        json_value(&particle.data, dialect),
    ]
}

fn alert_values(alert: &Alert, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(alert.id, dialect),
        alert.address.as_str().into(),
        timestamp_value(&alert.timestamp, dialect),
        alert.level.as_str().into(),
        alert.kind.clone().into(),
        json_value(&alert.data, dialect),
    ]
}

fn entry_values(entry: &LogEntry, dialect: Dialect) -> Vec<SimpleExpr> {
    vec![
        id_value(entry.id, dialect),
        entry.address.as_str().into(),
        timestamp_value(&entry.timestamp, dialect),
        entry.level.as_str().into(),
        entry.content.clone().into(),
    ]
}

/// Iterate a batch keeping only the last record per key.
///
/// A multi-row upsert cannot touch the same row twice, while the sequential writes it
/// replaces let the last occurrence win, so duplicates collapse to that.
fn dedupe_last<T, K: std::hash::Hash + Eq>(
    records: &[T],
    key: impl Fn(&T) -> K,
) -> impl Iterator<Item = &T> {
    let mut last = std::collections::HashMap::new();
    for (index, record) in records.iter().enumerate() {
        last.insert(key(record), index);
    }

    let mut indexes: Vec<usize> = last.into_values().collect();
    indexes.sort_unstable();
    indexes.into_iter().map(|index| &records[index])
}

fn id_value(id: uuid::Uuid, dialect: Dialect) -> SimpleExpr {
    match dialect {
        Dialect::Sqlite => id.to_string().into(),
        Dialect::Postgres => id.into(),
    }
}

fn timestamp_value(timestamp: &ceres_entities::Timestamp, dialect: Dialect) -> SimpleExpr {
    match dialect {
        Dialect::Sqlite => Parameter::timestamp_text(&timestamp.0.naive_utc()).into(),
        Dialect::Postgres => timestamp.0.naive_utc().into(),
    }
}

fn json_value(data: &serde_json::Map<String, serde_json::Value>, dialect: Dialect) -> SimpleExpr {
    json_text(
        &serde_json::Value::Object(data.clone()).to_string(),
        dialect,
    )
}

/// A JSON document's text as the value its column stores.
///
/// Both backends store the text, matching the query layer's writer. PostgreSQL casts to
/// `json` rather than binding a document object, which would arrive as `jsonb` and be
/// normalized, sorting its keys. The stored text is what a `contains` filter searches, so
/// a document written as `jsonb` would be searched in an order nobody wrote it in.
fn json_text(text: &str, dialect: Dialect) -> SimpleExpr {
    match dialect {
        Dialect::Sqlite => text.into(),
        Dialect::Postgres => SimpleExpr::from(text).cast_as(sea_query::Alias::new("json")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ceres_entities::{Address, LogEntry, Timestamp};
    use chrono::{TimeZone, Utc};
    use sea_query::SqliteQueryBuilder;

    fn entry(id: u128, content: &str) -> LogEntry {
        LogEntry {
            id: uuid::Uuid::from_u128(id),
            address: Address::parse("@a").unwrap(),
            timestamp: Timestamp(Utc.with_ymd_and_hms(2026, 7, 29, 0, 0, 0).unwrap()),
            level: ceres_entities::Level::Info,
            content: content.to_string(),
        }
    }

    #[test]
    fn upserts_update_every_non_key_column() {
        let records = Records::LogEntries(vec![entry(1, "first")]);
        let statement = upsert_statement(&records, Dialect::Sqlite).unwrap();
        let sql = statement.to_string(SqliteQueryBuilder);
        assert!(sql.starts_with("INSERT INTO \"logs\""));
        assert!(sql.contains("ON CONFLICT (\"id\") DO UPDATE SET"));
        assert!(sql.contains("\"content\" = \"excluded\".\"content\""));
        assert!(!sql.contains("\"id\" = \"excluded\""));
    }

    #[test]
    fn duplicate_ids_collapse_to_the_last_occurrence() {
        let records = Records::LogEntries(vec![entry(1, "first"), entry(1, "second")]);
        let statement = upsert_statement(&records, Dialect::Sqlite).unwrap();
        let sql = statement.to_string(SqliteQueryBuilder);
        assert!(sql.contains("second"));
        assert!(!sql.contains("first"));
    }

    #[test]
    fn empty_batches_build_no_statement() {
        assert!(upsert_statement(&Records::Messages(Vec::new()), Dialect::Sqlite).is_none());
    }
}
