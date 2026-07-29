//! Connection pools and query execution.

use ceres_entities::Records;
use sea_query::{PostgresQueryBuilder, SqliteQueryBuilder};
use sea_query_binder::SqlxBinder;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

use crate::records::{DecodeRecords, RecordTable};

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
    pub fn postgres(
        host: &str,
        port: Option<u16>,
        database: &str,
        user: &str,
        password: Option<&str>,
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
