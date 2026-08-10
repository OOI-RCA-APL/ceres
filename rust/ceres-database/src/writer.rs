//! Native record writes.
//!
//! A flush of buffered records writes here as one transaction of multi-row upserts, built
//! with sea-query per backend. Statement shape mirrors the query layer's writer, an
//! `INSERT ... ON CONFLICT (id) DO UPDATE` setting every non-key column from `excluded`.

use std::sync::Arc;
use std::time::Duration;

use ceres_entities::{
    Alert, Entities, Filterable, Group, GroupMembership, GroupPermission, LogEntry, Message,
    MessageDirection, Particle, Records, Setting, User, UserPermission, Variable, Workspace,
    WorkspaceEdit,
};
use sea_query::{Alias, InsertStatement, OnConflict, Query, SimpleExpr};
use sqlx::postgres::PgPoolOptions;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};

use crate::assign::json_text;
use crate::backend::{DatabaseBackend, PostgresBackend, SqliteBackend, Writing};
use crate::filter::SqlDialect;
use crate::records::RecordTable;
use crate::store::{Error, Parameter};
use crate::turso::TursoBackend;

/// A natively-connected writer for record entities.
///
/// Connections open lazily on first use. The SQLite pool holds a single connection, the
/// backend serializes writers anyway and one connection avoids lock churn against the
/// query layer's own pool on the same file.
pub struct RecordWriter {
    backend: Arc<dyn DatabaseBackend>,
}

impl RecordWriter {
    /// Open a writer over a SQLite database file.
    ///
    /// The connection matches the query layer's, with the same busy timeout and foreign
    /// key enforcement. It never creates a missing file because the file's lifecycle
    /// belongs to the Python layer.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life. The `init` statements are the writable store's to run
    /// because that is the connection a database opens for itself.
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
            backend: Arc::new(SqliteBackend(pool)),
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
            backend: Arc::new(PostgresBackend(pool)),
        })
    }

    /// Open a writer over a Turso database file.
    ///
    /// When `mvcc` is set, each connection enables MVCC journaling to match the store's
    /// connections on the same file, and a flush then opens a transaction that may
    /// overlap other writers.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two ends
    /// of a connection's life. The `init` statements are the writable store's to run
    /// because that is the connection a database opens for itself.
    pub fn turso(path: &str, mvcc: bool, on_connect: Vec<String>, on_close: Vec<String>) -> Self {
        Self {
            backend: Arc::new(TursoBackend::new(
                path,
                mvcc,
                Vec::new(),
                on_connect,
                on_close,
            )),
        }
    }

    /// Upsert every batch in one transaction.
    ///
    /// A flush is atomic, either every record in every batch lands or none do.
    ///
    /// The transaction asks to overlap other writers because this is the one write path
    /// that is frequent, independent, and safe to run again. Records are keyed by an ID
    /// their producer minted so two flushes rarely touch the same row, and a flush that
    /// loses a race at commit is requeued by the buffer above and written next time. A
    /// backend that cannot overlap runs it serialized instead, which
    /// [`RecordStore::overlaps_writers`](crate::RecordStore::overlaps_writers) reports.
    pub async fn upsert(&self, batches: Vec<Records>) -> Result<(), Error> {
        let dialect = self.backend.dialect();
        let mut statements = batches.iter().filter_map(|batch| {
            upsert_statement(batch, dialect).map(|statement| Ok((statement, batch.len())))
        });

        // The returned count is dropped. It counts what was handed in rather than what
        // landed because `upsert_statement` keeps only the last of any repeated ID,
        // and a flush is not asked how much of its input was new.
        self.backend
            .insert_all(Writing::Concurrent, &mut statements)
            .await?;
        Ok(())
    }
}

/// Build the multi-row upsert for one batch, or `None` when the batch is empty.
fn upsert_statement(records: &Records, dialect: SqlDialect) -> Option<InsertStatement> {
    let rows = match records {
        Records::Messages(messages) => deduped_rows(messages, |message| message.id, dialect),
        Records::Particles(particles) => deduped_rows(particles, |particle| particle.id, dialect),
        Records::Alerts(alerts) => deduped_rows(alerts, |alert| alert.id, dialect),
        Records::LogEntries(entries) => deduped_rows(entries, |entry| entry.id, dialect),
    };

    let table = crate::records::table_of(records);
    let mut statement = table.insert_into(rows)?;

    // Every non-key column updates from the excluded row, mirroring the query layer's
    // upsert so a rewritten record replaces its earlier form.
    let mut conflict = OnConflict::column(Alias::new("id"));
    conflict.update_columns(
        table
            .column_names()
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
/// row it read so a file naming one key twice reaches the database twice and the
/// conflict mode decides what happens.
pub(crate) fn load_statement(records: &Records, dialect: SqlDialect) -> Option<InsertStatement> {
    let rows = match records {
        Records::Messages(messages) => rows(messages, dialect),
        Records::Particles(particles) => rows(particles, dialect),
        Records::Alerts(alerts) => rows(alerts, dialect),
        Records::LogEntries(entries) => rows(entries, dialect),
    };

    crate::records::table_of(records).insert_into(rows)
}

/// Bind every entity in a batch, in file order, for a bulk load or a create.
pub(crate) fn entity_load_statement(
    entities: &Entities,
    dialect: SqlDialect,
) -> Option<InsertStatement> {
    let rows = match entities {
        Entities::Users(users) => rows(users, dialect),
        Entities::Variables(variables) => rows(variables, dialect),
        Entities::Settings(settings) => rows(settings, dialect),
        Entities::Workspaces(workspaces) => rows(workspaces, dialect),
        Entities::WorkspaceEdits(edits) => rows(edits, dialect),
        Entities::Groups(groups) => rows(groups, dialect),
        Entities::GroupMemberships(memberships) => rows(memberships, dialect),
        Entities::UserPermissions(permissions) => rows(permissions, dialect),
        Entities::GroupPermissions(permissions) => rows(permissions, dialect),
    };

    open_insert(
        crate::entities::table_of(entities).schema().name,
        entity_columns(entities),
        rows,
    )
}

/// The columns an entity batch binds, in the order its value builder writes them.
///
/// This is the derive's wire-key order so the list cannot drift from the serialized
/// form the value builders align with.
pub(crate) fn entity_columns(entities: &Entities) -> &'static [&'static str] {
    match entities {
        Entities::Users(_) => User::WIRE_KEYS,
        Entities::Variables(_) => Variable::WIRE_KEYS,
        Entities::Settings(_) => Setting::WIRE_KEYS,
        Entities::Workspaces(_) => Workspace::WIRE_KEYS,
        Entities::WorkspaceEdits(_) => WorkspaceEdit::WIRE_KEYS,
        Entities::Groups(_) => Group::WIRE_KEYS,
        Entities::GroupMemberships(_) => GroupMembership::WIRE_KEYS,
        Entities::UserPermissions(_) => UserPermission::WIRE_KEYS,
        Entities::GroupPermissions(_) => GroupPermission::WIRE_KEYS,
    }
}

/// The row one entity or record binds, in its table's column order.
///
/// Implemented here rather than beside the types because binding is sea-query's
/// business and `ceres-entities` knows nothing of it, which is exactly the local trait
/// the orphan rule asks for. The entity impls align with [`Filterable::WIRE_KEYS`],
/// which [`entity_columns`] serves, while the record tables bind the stored subset
/// [`RecordTable::column_names`] names, a particle's transient span having no column.
trait RowValues {
    /// The stored column values, in the table's column order.
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr>;
}

/// Bind every item of a batch, in order.
fn rows<T: RowValues>(items: &[T], dialect: SqlDialect) -> Vec<Vec<SimpleExpr>> {
    items.iter().map(|item| item.row_values(dialect)).collect()
}

/// Bind a batch keeping only the last row per key, the multi-row upsert rule.
fn deduped_rows<T: RowValues, K: std::hash::Hash + Eq>(
    records: &[T],
    key: impl Fn(&T) -> K,
    dialect: SqlDialect,
) -> Vec<Vec<SimpleExpr>> {
    dedupe_last(records, key)
        .map(|record| record.row_values(dialect))
        .collect()
}

impl RowValues for User {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.username.clone().into(),
            self.email.clone().into(),
            self.password.clone().into(),
            self.admin.into(),
            self.disabled.into(),
        ]
    }
}

impl RowValues for Variable {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            self.address.as_str().into(),
            self.name.clone().into(),
            bare_json_value(&self.value, dialect),
        ]
    }
}

impl RowValues for Setting {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.user_id, dialect),
            self.name.clone().into(),
            bare_json_value(&self.value, dialect),
        ]
    }
}

impl RowValues for Workspace {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.name.clone().into(),
            self.scope.as_str().into(),
            match self.owner_id {
                Some(owner) => id_value(owner, dialect),
                None => SimpleExpr::Keyword(sea_query::Keyword::Null),
            },
            self.show_when_logged_out.into(),
            json_value(&self.data, dialect),
        ]
    }
}

impl RowValues for WorkspaceEdit {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.user_id, dialect),
            id_value(self.workspace_id, dialect),
            json_value(&self.data, dialect),
        ]
    }
}

impl RowValues for Group {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.name.clone().into(),
            self.description.clone().into(),
        ]
    }
}

impl RowValues for GroupMembership {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.user_id, dialect),
            id_value(self.group_id, dialect),
        ]
    }
}

impl RowValues for UserPermission {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.user_id, dialect),
            self.target_type.as_str().into(),
            self.target.clone().into(),
            self.level.as_str().into(),
        ]
    }
}

impl RowValues for GroupPermission {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.group_id, dialect),
            self.target_type.as_str().into(),
            self.target.clone().into(),
            self.level.as_str().into(),
        ]
    }
}

/// Bind a bare JSON value, stored as its text on the SQLite family.
fn bare_json_value(value: &serde_json::Value, dialect: SqlDialect) -> SimpleExpr {
    json_text(&value.to_string(), dialect)
}

impl RecordTable {
    /// Open an insert over the table's columns, `None` when there is nothing to bind.
    fn insert_into(self, rows: Vec<Vec<SimpleExpr>>) -> Option<InsertStatement> {
        open_insert(self.name(), self.column_names(), rows)
    }

    /// The table's stored columns, in the order rows bind them.
    pub(crate) fn column_names(self) -> &'static [&'static str] {
        match self {
            Self::Messages => &[
                "id",
                "address",
                "timestamp",
                "connection",
                "direction",
                "data",
            ],
            Self::Particles => &["id", "address", "timestamp", "type", "data"],
            Self::Alerts => &["id", "address", "timestamp", "level", "type", "data"],
            Self::Logs => &["id", "address", "timestamp", "level", "content"],
        }
    }
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

impl RowValues for Message {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.address.as_str().into(),
            timestamp_value(&self.timestamp, dialect),
            self.connection.clone().into(),
            match self.direction {
                MessageDirection::Send => "send".into(),
                MessageDirection::Receive => "receive".into(),
            },
            self.data.clone().into(),
        ]
    }
}

impl RowValues for Particle {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.address.as_str().into(),
            timestamp_value(&self.timestamp, dialect),
            self.kind.clone().into(),
            json_value(&self.data, dialect),
        ]
    }
}

impl RowValues for Alert {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.address.as_str().into(),
            timestamp_value(&self.timestamp, dialect),
            self.level.as_str().into(),
            self.kind.clone().into(),
            json_value(&self.data, dialect),
        ]
    }
}

impl RowValues for LogEntry {
    fn row_values(&self, dialect: SqlDialect) -> Vec<SimpleExpr> {
        vec![
            id_value(self.id, dialect),
            self.address.as_str().into(),
            timestamp_value(&self.timestamp, dialect),
            self.level.as_str().into(),
            self.content.clone().into(),
        ]
    }
}

/// Iterate a batch keeping only the last record per key.
///
/// A multi-row upsert cannot touch the same row twice, while the sequential writes it
/// replaces let the last occurrence win so duplicates collapse to that.
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

/// A UUID's bound value wrapped for a statement, stored text on the SQLite family.
fn id_value(id: uuid::Uuid, dialect: SqlDialect) -> SimpleExpr {
    crate::filter::id_value(id, dialect).into()
}

fn timestamp_value(timestamp: &ceres_entities::Timestamp, dialect: SqlDialect) -> SimpleExpr {
    match dialect {
        SqlDialect::SqliteText => Parameter::timestamp_text(&timestamp.0.naive_utc()).into(),
        SqlDialect::Postgres => timestamp.0.naive_utc().into(),
    }
}

fn json_value(
    data: &serde_json::Map<String, serde_json::Value>,
    dialect: SqlDialect,
) -> SimpleExpr {
    json_text(
        &serde_json::Value::Object(data.clone()).to_string(),
        dialect,
    )
}

#[cfg(test)]
mod tests {
    use ceres_entities::{Address, LogEntry, Timestamp};
    use chrono::{TimeZone, Utc};
    use sea_query::SqliteQueryBuilder;

    use super::*;

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
        let statement = upsert_statement(&records, SqlDialect::SqliteText).unwrap();
        let sql = statement.to_string(SqliteQueryBuilder);
        assert!(sql.starts_with("INSERT INTO \"logs\""));
        assert!(sql.contains("ON CONFLICT (\"id\") DO UPDATE SET"));
        assert!(sql.contains("\"content\" = \"excluded\".\"content\""));
        assert!(!sql.contains("\"id\" = \"excluded\""));
    }

    #[test]
    fn duplicate_ids_collapse_to_the_last_occurrence() {
        let records = Records::LogEntries(vec![entry(1, "first"), entry(1, "second")]);
        let statement = upsert_statement(&records, SqlDialect::SqliteText).unwrap();
        let sql = statement.to_string(SqliteQueryBuilder);
        assert!(sql.contains("second"));
        assert!(!sql.contains("first"));
    }

    #[test]
    fn empty_batches_build_no_statement() {
        assert!(upsert_statement(&Records::Messages(Vec::new()), SqlDialect::SqliteText).is_none());
    }
}
