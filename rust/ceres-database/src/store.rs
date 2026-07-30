//! Connection pools and query execution.

use ceres_entities::Records;
use sea_query::{PostgresQueryBuilder, SelectStatement, SqliteQueryBuilder};
use sea_query_binder::SqlxBinder;
use sqlx::Row;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

use crate::filter::{RecordFilter, SqlDialect};
use crate::records::{DecodeRecords, RecordTable};
use crate::turso::{TursoBackend, parameter_value, sea_value};

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
    /// The six-digit fraction always appears, `.000000` included, because that is the
    /// form the SQLite driver stores and equality against stored text has to collate
    /// identically. A whole-second timestamp rendered without its fraction misses the
    /// stored row.
    pub(crate) fn timestamp_text(timestamp: &chrono::NaiveDateTime) -> String {
        timestamp.format("%Y-%m-%d %H:%M:%S%.6f").to_string()
    }
}

/// A database access failure.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0} is not a record table")]
    UnknownTable(String),
    #[error(transparent)]
    Database(#[from] sqlx::Error),
    #[error(transparent)]
    Turso(#[from] turso::Error),
    #[error("{0}")]
    Connect(String),
    #[error("{0}")]
    Decode(String),
}

/// The standing an authentication gate reads for one user.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct GateUser {
    pub id: uuid::Uuid,
    pub admin: bool,
    pub disabled: bool,
}

/// The connection pool or engine for one backend.
enum Backend {
    Sqlite(SqlitePool),
    Postgres(PgPool),
    Turso(TursoBackend),
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

    /// Open a store over a Turso database file.
    ///
    /// When `mvcc` is set, each connection enables MVCC journaling to match the query
    /// layer's connections on the same file.
    pub fn turso(path: &str, mvcc: bool) -> Self {
        Self {
            backend: Backend::Turso(TursoBackend::new(path, mvcc)),
        }
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

        self.select(table, table.listing(limit, offset)).await
    }

    /// The dialect value forms this store's backend binds.
    fn dialect(&self) -> SqlDialect {
        match &self.backend {
            Backend::Sqlite(_) | Backend::Turso(_) => SqlDialect::SqliteText,
            Backend::Postgres(_) => SqlDialect::Postgres,
        }
    }

    /// Execute one built statement, decoding rows for the table.
    async fn select(
        &self,
        table: RecordTable,
        statement: SelectStatement,
    ) -> Result<Records, Error> {
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
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.query(table, &sql, parameters).await
            }
        }
    }

    /// Fetch the records a parsed native filter matches.
    pub async fn fetch_filter(
        &self,
        table: RecordTable,
        filter: &RecordFilter,
    ) -> Result<Records, Error> {
        if filter.limit() == Some(0) {
            return Ok(table.empty());
        }

        self.select(table, filter.statement(table, self.dialect()))
            .await
    }

    /// Count the records a parsed native filter matches.
    ///
    /// A limit or offset bounds the count itself, matching the Python layer's paged
    /// counting.
    pub async fn count_filter(
        &self,
        table: RecordTable,
        filter: &RecordFilter,
    ) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        let statement = filter.count_statement(table, self.dialect());
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let row = sqlx::query_with(&sql, values).fetch_one(pool).await?;
                let count: i64 = row.try_get(0)?;
                Ok(count.max(0) as u64)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let row = sqlx::query_with(&sql, values).fetch_one(pool).await?;
                let count: i64 = row.try_get(0)?;
                Ok(count.max(0) as u64)
            }
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.scalar_count(&sql, parameters).await
            }
        }
    }

    /// Read the columns an authentication gate needs for one user, `None` when no user
    /// carries the ID.
    ///
    /// The gate needs only standing, whether the account is an administrator and
    /// whether it is disabled, so a record request never crosses into Python just to
    /// admit its caller.
    pub async fn gate_user(&self, id: uuid::Uuid) -> Result<Option<GateUser>, Error> {
        const SQL: &str = "SELECT \"admin\", \"disabled\" FROM \"users\" WHERE \"id\" = ";

        match &self.backend {
            Backend::Sqlite(pool) => {
                let sql = format!("{SQL}?");
                let row = sqlx::query(&sql)
                    .bind(id.to_string())
                    .fetch_optional(pool)
                    .await?;
                row.map(|row| {
                    Ok(GateUser {
                        id,
                        admin: row.try_get("admin")?,
                        disabled: row.try_get("disabled")?,
                    })
                })
                .transpose()
            }
            Backend::Postgres(pool) => {
                let sql = format!("{SQL}$1");
                let row = sqlx::query(&sql).bind(id).fetch_optional(pool).await?;
                row.map(|row| {
                    Ok(GateUser {
                        id,
                        admin: row.try_get("admin")?,
                        disabled: row.try_get("disabled")?,
                    })
                })
                .transpose()
            }
            Backend::Turso(backend) => {
                let sql = format!("{SQL}?");
                backend.gate_user(&sql, id).await
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
            Backend::Turso(backend) => {
                // Turso shares the SQLite dialect, parameters bind in their stored text
                // forms.
                let parameters = parameters.into_iter().map(parameter_value).collect();
                backend.query(table, sql, parameters).await
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
