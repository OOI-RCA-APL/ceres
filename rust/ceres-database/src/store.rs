//! Connection pools and query execution.

use ceres_entities::Records;
use sea_query::{PostgresQueryBuilder, SqliteQueryBuilder};
use sea_query_binder::SqlxBinder;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

use crate::records::{DecodeRecords, RecordTable};

/// A statement parameter, as the Python layer's bind processors produce them.
///
/// Most values arrive as primitives, but the PostgreSQL driver takes timestamps and UUIDs
/// natively, so its processors pass those through as objects.
#[derive(Clone, Debug, PartialEq)]
pub enum Parameter {
    Null,
    Bool(bool),
    Integer(i64),
    Float(f64),
    Text(String),
    Bytes(Vec<u8>),
    Timestamp(chrono::NaiveDateTime),
    Uuid(uuid::Uuid),
}

impl Parameter {
    /// The stored text form of a timestamp, matching how the Python layer writes them.
    ///
    /// The fraction appears only when the timestamp has sub-second precision, because that
    /// is how the driver's text binding behaves and comparisons against stored text have
    /// to collate identically.
    pub(crate) fn timestamp_text(timestamp: &chrono::NaiveDateTime) -> String {
        use chrono::Timelike;

        if timestamp.nanosecond() == 0 {
            timestamp.format("%Y-%m-%d %H:%M:%S").to_string()
        } else {
            timestamp.format("%Y-%m-%d %H:%M:%S%.6f").to_string()
        }
    }
}

/// A database access failure.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0} is not a record table")]
    UnknownTable(String),
    #[error(transparent)]
    Database(#[from] sqlx::Error),
    #[error("{0}")]
    Decode(String),
}

/// The connection pool for one backend.
enum Backend {
    Sqlite(SqlitePool),
    Postgres(PgPool),
}

/// A natively-connected view of a Ceres database, serving entity reads.
///
/// Connections open lazily on first use, so building a store is cheap and never touches
/// the database. The store connects to the same database the Python layer resolved,
/// including per-instance temporary SQLite paths, which is why it takes resolved
/// connection parameters rather than a configuration.
pub struct RecordStore {
    backend: Backend,
}

impl RecordStore {
    /// Open a store over a SQLite database file.
    pub fn sqlite(path: &str) -> Result<Self, Error> {
        let options = SqliteConnectOptions::new().filename(path).read_only(true);
        let pool = SqlitePoolOptions::new().connect_lazy_with(options);
        Ok(Self {
            backend: Backend::Sqlite(pool),
        })
    }

    /// Open a store over a PostgreSQL database.
    ///
    /// `settings` are per-connection server settings like `search_path`, matching the ones
    /// the Python layer passes its own driver.
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

    /// Fetch a record listing, ordered by timestamp like the Python layer's default.
    pub async fn fetch(
        &self,
        table: RecordTable,
        limit: Option<u64>,
        offset: Option<u64>,
    ) -> Result<Records, Error> {
        if limit == Some(0) {
            return Ok(table.empty());
        }

        let statement = table.listing(limit, offset);
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let rows = sqlx::query_with(&sql, values).fetch_all(pool).await?;
                DecodeRecords::decode(table, rows)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let rows = sqlx::query_with(&sql, values).fetch_all(pool).await?;
                DecodeRecords::decode(table, rows)
            }
        }
    }

    /// Execute a compiled record query, decoding its rows for the given table.
    ///
    /// The statement text and parameters come from the Python query layer's own compiler,
    /// so any filter it can express runs natively with identical semantics. Only `SELECT`
    /// statements are accepted.
    pub async fn fetch_sql(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Records, Error> {
        let head = sql.trim_start();
        if !starts_with_keyword(head, "select") && !starts_with_keyword(head, "with") {
            return Err(Error::Decode("only SELECT statements execute here".into()));
        }

        match &self.backend {
            Backend::Sqlite(pool) => {
                let mut query = sqlx::query(sql);
                for parameter in parameters {
                    query = match parameter {
                        Parameter::Null => query.bind(None::<String>),
                        Parameter::Bool(value) => query.bind(value),
                        Parameter::Integer(value) => query.bind(value),
                        Parameter::Float(value) => query.bind(value),
                        Parameter::Text(value) => query.bind(value),
                        Parameter::Bytes(value) => query.bind(value),
                        // SQLite stores timestamps and UUIDs as text, so parameters have
                        // to compare against that form.
                        Parameter::Timestamp(value) => {
                            query.bind(Parameter::timestamp_text(&value))
                        }
                        Parameter::Uuid(value) => query.bind(value.to_string()),
                    };
                }

                let rows = query.fetch_all(pool).await?;
                DecodeRecords::decode(table, rows)
            }
            Backend::Postgres(pool) => {
                let mut query = sqlx::query(sql);
                for parameter in parameters {
                    query = match parameter {
                        Parameter::Null => query.bind(None::<String>),
                        Parameter::Bool(value) => query.bind(value),
                        Parameter::Integer(value) => query.bind(value),
                        Parameter::Float(value) => query.bind(value),
                        Parameter::Text(value) => query.bind(value),
                        Parameter::Bytes(value) => query.bind(value),
                        Parameter::Timestamp(value) => query.bind(value),
                        Parameter::Uuid(value) => query.bind(value),
                    };
                }

                let rows = query.fetch_all(pool).await?;
                DecodeRecords::decode(table, rows)
            }
        }
    }
}

/// Check a case-insensitive keyword prefix.
fn starts_with_keyword(text: &str, keyword: &str) -> bool {
    text.len() >= keyword.len() && text[..keyword.len()].eq_ignore_ascii_case(keyword)
}

#[cfg(test)]
mod tests {
    use sea_query::SqliteQueryBuilder;

    use super::*;

    #[test]
    fn listings_order_and_bound_like_the_python_layer() {
        let statement = RecordTable::Particles.listing(Some(100), Some(20));
        assert_eq!(
            statement.to_string(SqliteQueryBuilder),
            "SELECT * FROM \"particles\" ORDER BY \"timestamp\" ASC LIMIT 100 OFFSET 20"
        );
    }

    #[test]
    fn tables_parse_by_name() {
        assert_eq!(
            RecordTable::parse("messages").unwrap(),
            RecordTable::Messages
        );
        assert!(RecordTable::parse("users").is_err());
    }
}
