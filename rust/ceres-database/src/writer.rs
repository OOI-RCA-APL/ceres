//! Native record writes.
//!
//! A flush of buffered records writes here as one transaction of multi-row upserts, built
//! with sea-query per backend. Statement shape mirrors the query layer's writer, an
//! `INSERT ... ON CONFLICT (id) DO UPDATE` setting every non-key column from `excluded`.

use std::time::Duration;

use ceres_entities::Records;
use sea_query::{
    Alias, InsertStatement, OnConflict, PostgresQueryBuilder, Query, SimpleExpr, SqliteQueryBuilder,
};
use sea_query_binder::SqlxBinder;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

use crate::store::{Error, Parameter};
use crate::turso::{TursoBackend, sea_value};

/// The write pool or engine for one backend.
enum Backend {
    Sqlite(SqlitePool),
    Postgres(PgPool),
    Turso(TursoBackend),
}

/// How a backend expects record values bound.
#[derive(Clone, Copy, PartialEq)]
enum Dialect {
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
    backend: Backend,
}

impl RecordWriter {
    /// Open a writer over a SQLite database file.
    ///
    /// The connection matches the query layer's, the same busy timeout and foreign key
    /// enforcement, and never creates a missing file, the file's lifecycle belongs to the
    /// Python layer.
    pub fn sqlite(path: &str) -> Result<Self, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .busy_timeout(Duration::from_secs(30))
            .foreign_keys(true);
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_lazy_with(options);
        Ok(Self {
            backend: Backend::Sqlite(pool),
        })
    }

    /// Open a writer over a PostgreSQL database, with per-connection server settings.
    pub fn postgres(
        host: &str,
        port: Option<u16>,
        database: &str,
        user: &str,
        password: Option<&str>,
        settings: Vec<(String, String)>,
    ) -> Result<Self, Error> {
        let mut options = PgConnectOptions::new()
            .host(host)
            .database(database)
            .username(user);
        if let Some(port) = port {
            options = options.port(port);
        }

        if let Some(password) = password {
            options = options.password(password);
        }

        if !settings.is_empty() {
            options = options.options(settings);
        }

        let pool = PgPoolOptions::new().connect_lazy_with(options);
        Ok(Self {
            backend: Backend::Postgres(pool),
        })
    }

    /// Open a writer over a Turso database file.
    ///
    /// When `mvcc` is set, each connection enables MVCC journaling to match the query
    /// layer's connections on the same file. Transactions open with a plain `BEGIN`, the
    /// concurrent form is for the query layer's explicitly concurrent sections.
    pub fn turso(path: &str, mvcc: bool) -> Self {
        Self {
            backend: Backend::Turso(TursoBackend::new(path, mvcc)),
        }
    }

    /// Upsert every batch in one transaction.
    ///
    /// A flush is atomic, either every record in every batch lands or none do.
    pub async fn upsert(&self, batches: Vec<Records>) -> Result<(), Error> {
        match &self.backend {
            Backend::Sqlite(pool) => {
                let mut transaction = pool.begin().await?;
                for batch in batches {
                    let Some(statement) = upsert_statement(&batch, Dialect::Sqlite) else {
                        continue;
                    };
                    let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                    sqlx::query_with(&sql, values)
                        .execute(&mut *transaction)
                        .await?;
                }

                transaction.commit().await?;
            }
            Backend::Postgres(pool) => {
                let mut transaction = pool.begin().await?;
                for batch in batches {
                    let Some(statement) = upsert_statement(&batch, Dialect::Postgres) else {
                        continue;
                    };
                    let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                    sqlx::query_with(&sql, values)
                        .execute(&mut *transaction)
                        .await?;
                }

                transaction.commit().await?;
            }
            Backend::Turso(backend) => {
                // Turso shares the SQLite dialect, so statements build identically and
                // only the execution layer differs.
                let mut statements = Vec::new();
                for batch in batches {
                    let Some(statement) = upsert_statement(&batch, Dialect::Sqlite) else {
                        continue;
                    };
                    let (sql, values) = statement.build(SqliteQueryBuilder);
                    let parameters = values
                        .into_iter()
                        .map(sea_value)
                        .collect::<Result<Vec<_>, _>>()?;
                    statements.push((sql, parameters));
                }

                backend.execute_transaction(statements).await?;
            }
        }

        Ok(())
    }
}

/// Build the multi-row upsert for one batch, or `None` when the batch is empty.
fn upsert_statement(records: &Records, dialect: Dialect) -> Option<InsertStatement> {
    let (table, columns, rows) = match records {
        Records::Messages(messages) => (
            "messages",
            vec![
                "id",
                "address",
                "timestamp",
                "connection",
                "direction",
                "data",
            ],
            dedupe_last(messages, |message| message.id)
                .map(|message| {
                    vec![
                        id_value(message.id, dialect),
                        message.address.as_str().into(),
                        timestamp_value(&message.timestamp, dialect),
                        message.connection.clone().into(),
                        match message.direction {
                            ceres_entities::MessageDirection::Send => "send".into(),
                            ceres_entities::MessageDirection::Receive => "receive".into(),
                        },
                        message.data.clone().into(),
                    ]
                })
                .collect::<Vec<_>>(),
        ),
        Records::Particles(particles) => (
            "particles",
            vec!["id", "address", "timestamp", "type", "data"],
            dedupe_last(particles, |particle| particle.id)
                .map(|particle| {
                    vec![
                        id_value(particle.id, dialect),
                        particle.address.as_str().into(),
                        timestamp_value(&particle.timestamp, dialect),
                        particle.kind.clone().into(),
                        json_value(&particle.data, dialect),
                    ]
                })
                .collect(),
        ),
        Records::Alerts(alerts) => (
            "alerts",
            vec!["id", "address", "timestamp", "level", "type", "data"],
            dedupe_last(alerts, |alert| alert.id)
                .map(|alert| {
                    vec![
                        id_value(alert.id, dialect),
                        alert.address.as_str().into(),
                        timestamp_value(&alert.timestamp, dialect),
                        alert.level.as_str().into(),
                        alert.kind.clone().into(),
                        json_value(&alert.data, dialect),
                    ]
                })
                .collect(),
        ),
        Records::LogEntries(entries) => (
            "logs",
            vec!["id", "address", "timestamp", "level", "content"],
            dedupe_last(entries, |entry| entry.id)
                .map(|entry| {
                    vec![
                        id_value(entry.id, dialect),
                        entry.address.as_str().into(),
                        timestamp_value(&entry.timestamp, dialect),
                        entry.level.as_str().into(),
                        entry.content.clone().into(),
                    ]
                })
                .collect(),
        ),
    };

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

    // Every non-key column updates from the excluded row, mirroring the query layer's
    // upsert so a rewritten record replaces its earlier form.
    let mut conflict = OnConflict::column(Alias::new("id"));
    conflict.update_columns(
        columns
            .iter()
            .filter(|&&column| column != "id")
            .map(|&column| Alias::new(column)),
    );
    statement.on_conflict(conflict);

    Some(statement)
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
    match dialect {
        // JSON columns store compact text on SQLite, matching the query layer's writer.
        Dialect::Sqlite => serde_json::Value::Object(data.clone()).to_string().into(),
        Dialect::Postgres => serde_json::Value::Object(data.clone()).into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ceres_entities::{Address, LogEntry, Timestamp};
    use chrono::{TimeZone, Utc};

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
