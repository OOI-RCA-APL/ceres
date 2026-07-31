//! Connection pools and query execution.

use ceres_entities::{Entities, Records};
use sea_query::{Alias, OnConflict, PostgresQueryBuilder, SelectStatement, SqliteQueryBuilder};
use sea_query_binder::SqlxBinder;
use sqlx::Row;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

use crate::entities::{DecodeEntities, EntityTable};
use crate::filter::{EntityFilter, RecordFilter, SqlDialect};
use crate::load::Conflict;
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
    #[error("the native path does not serve this operation on this backend")]
    Unsupported,
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

    /// Open a writable store over a SQLite database file.
    ///
    /// The connection matches the query layer's, the same busy timeout and foreign key
    /// enforcement, because both pools share the file. It never creates a missing file,
    /// whose lifecycle belongs to the Python layer, and holds one connection, since the
    /// backend serializes writers anyway.
    pub fn sqlite_writable(path: &str) -> Result<Self, Error> {
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(false)
            .busy_timeout(std::time::Duration::from_secs(30))
            .foreign_keys(true);
        let pool = SqlitePoolOptions::new()
            .max_connections(1)
            .connect_lazy_with(options);
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
    pub async fn fetch_filter(&self, filter: &RecordFilter) -> Result<Records, Error> {
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        self.select(filter.table(), filter.statement(self.dialect()))
            .await
    }

    /// Count the records a parsed native filter matches.
    ///
    /// A limit or offset bounds the count itself, matching the Python layer's paged
    /// counting.
    pub async fn count_filter(&self, filter: &RecordFilter) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.scalar_count(filter.count_statement(self.dialect()))
            .await
    }

    /// Whether any record matches a parsed native filter.
    ///
    /// Existence stops at the first matching row, so this stays cheap on a large table
    /// where counting would not.
    pub async fn any_filter(&self, filter: &RecordFilter) -> Result<bool, Error> {
        if filter.limit() == Some(0) {
            return Ok(false);
        }

        let statement = filter.exists_statement(self.dialect());
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let row = sqlx::query_with(&sql, values).fetch_one(pool).await?;
                let exists: bool = row.try_get(0)?;
                Ok(exists)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let row = sqlx::query_with(&sql, values).fetch_one(pool).await?;
                let exists: bool = row.try_get(0)?;
                Ok(exists)
            }
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(backend.scalar_count(&sql, parameters).await? > 0)
            }
        }
    }

    /// Delete the records a parsed native filter matches, returning how many went.
    ///
    /// The delete runs in its own transaction and commits only on success, so a failure
    /// leaves the table untouched and the command is free to delegate.
    pub async fn delete_filter(&self, filter: &RecordFilter) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.write(filter.delete_statement(self.dialect())).await
    }

    /// Assign values to the records a parsed native filter matches, returning how many
    /// changed. `None` when the assignments fall outside what the native path encodes.
    ///
    /// Like a delete, this runs in its own transaction and commits only on success.
    pub async fn update_filter(
        &self,
        filter: &RecordFilter,
        assign: &str,
    ) -> Result<Option<u64>, Error> {
        let Some(assignments) = self.encode_assignments(filter.table().schema(), assign) else {
            return Ok(None);
        };
        if filter.limit() == Some(0) {
            return Ok(Some(0));
        }

        self.write(filter.update_statement(self.dialect(), &assignments))
            .await
            .map(Some)
    }

    /// Encode an update's assignments for this backend, `None` when the object itself
    /// or any value in it falls outside what the native path represents faithfully.
    fn encode_assignments(
        &self,
        schema: crate::records::Schema,
        assign: &str,
    ) -> Option<Vec<crate::assign::Assignment>> {
        // The assignments are one YAML or JSON object, the form the Python command
        // takes, and anything else leaves the table untouched.
        let Ok(serde_json::Value::Object(values)) = serde_norway::from_str(assign) else {
            return None;
        };

        crate::assign::assignments(
            schema,
            &values,
            match self.dialect() {
                SqlDialect::SqliteText => crate::writer::Dialect::Sqlite,
                SqlDialect::Postgres => crate::writer::Dialect::Postgres,
            },
        )
    }

    /// Run one write statement in its own transaction, returning how many rows changed.
    ///
    /// Nothing lands unless the statement succeeds, so a failure leaves the table
    /// exactly as it was and the command is free to delegate.
    async fn write<S: SqlxBinder>(&self, statement: S) -> Result<u64, Error> {
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let mut transaction = pool.begin().await?;
                let affected = sqlx::query_with(&sql, values)
                    .execute(&mut *transaction)
                    .await?
                    .rows_affected();
                transaction.commit().await?;
                Ok(affected)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let mut transaction = pool.begin().await?;
                let affected = sqlx::query_with(&sql, values)
                    .execute(&mut *transaction)
                    .await?
                    .rows_affected();
                transaction.commit().await?;
                Ok(affected)
            }
            // Turso keeps the Python write path until its native writer is wired.
            Backend::Turso(_) => Err(Error::Unsupported),
        }
    }

    /// Fetch an entity listing, ordered by the entity's own default.
    ///
    /// Turso shares the SQLite dialect but not its driver, and the entity decoders are
    /// written against the two `sqlx` row types, so it keeps the Python path.
    pub async fn fetch_entities(
        &self,
        table: EntityTable,
        limit: Option<u64>,
        offset: Option<u64>,
    ) -> Result<Entities, Error> {
        if limit == Some(0) {
            return Ok(table.empty());
        }

        let statement = table.listing(limit, offset);
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let rows = sqlx::query_with(&sql, values).fetch_all(pool).await?;
                DecodeEntities::decode(table, rows)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let rows = sqlx::query_with(&sql, values).fetch_all(pool).await?;
                DecodeEntities::decode(table, rows)
            }
            Backend::Turso(_) => Err(Error::Unsupported),
        }
    }

    /// Fetch the entities a parsed native filter matches.
    pub async fn fetch_entity_filter(&self, filter: &EntityFilter) -> Result<Entities, Error> {
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let statement = filter.statement(self.dialect());
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let rows = sqlx::query_with(&sql, values).fetch_all(pool).await?;
                DecodeEntities::decode(filter.table(), rows)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let rows = sqlx::query_with(&sql, values).fetch_all(pool).await?;
                DecodeEntities::decode(filter.table(), rows)
            }
            Backend::Turso(_) => Err(Error::Unsupported),
        }
    }

    /// Count the entities a parsed native filter matches.
    pub async fn count_entity_filter(&self, filter: &EntityFilter) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.scalar_count(filter.count_statement(self.dialect()))
            .await
    }

    /// Whether any entity matches a parsed native filter.
    pub async fn any_entity_filter(&self, filter: &EntityFilter) -> Result<bool, Error> {
        if filter.limit() == Some(0) {
            return Ok(false);
        }

        let statement = filter.exists_statement(self.dialect());
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let row = sqlx::query_with(&sql, values).fetch_one(pool).await?;
                Ok(row.try_get(0)?)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let row = sqlx::query_with(&sql, values).fetch_one(pool).await?;
                Ok(row.try_get(0)?)
            }
            Backend::Turso(_) => Err(Error::Unsupported),
        }
    }

    /// Delete the entities a parsed native filter matches, returning how many went.
    ///
    /// Like every native write this runs in its own transaction and commits only on
    /// success, so a failure leaves the table untouched and the command may delegate.
    pub async fn delete_entity_filter(&self, filter: &EntityFilter) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.write(filter.delete_statement(self.dialect())).await
    }

    /// Assign values to the entities a parsed native filter matches, returning how many
    /// changed. `None` when the assignments fall outside what the native path encodes.
    pub async fn update_entity_filter(
        &self,
        filter: &EntityFilter,
        assign: &str,
    ) -> Result<Option<u64>, Error> {
        let Some(assignments) = self.encode_assignments(filter.table().schema(), assign) else {
            return Ok(None);
        };
        if filter.limit() == Some(0) {
            return Ok(Some(0));
        }

        self.write(filter.update_statement(self.dialect(), &assignments))
            .await
            .map(Some)
    }

    /// Run one count statement, whichever backend serves it.
    async fn scalar_count(&self, statement: SelectStatement) -> Result<u64, Error> {
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

    /// Write every batch of a bulk load in one transaction.
    ///
    /// Nothing lands unless the whole load succeeds, so a collision under `Conflict::Error`
    /// leaves the table exactly as it was and the command is free to delegate.
    pub async fn load_records(&self, batches: &[Records], conflict: Conflict) -> Result<(), Error> {
        let dialect = match self.dialect() {
            SqlDialect::SqliteText => crate::writer::Dialect::Sqlite,
            SqlDialect::Postgres => crate::writer::Dialect::Postgres,
        };
        let statements = batches
            .iter()
            .filter_map(|batch| {
                crate::writer::load_statement(batch, dialect).map(|mut statement| {
                    match conflict {
                        // Without a conflict clause a collision aborts the transaction,
                        // which is exactly what this mode promises.
                        Conflict::Error => {}
                        Conflict::Ignore => {
                            statement.on_conflict(
                                OnConflict::column(Alias::new("id")).do_nothing().to_owned(),
                            );
                        }
                        Conflict::Update => {
                            let mut on_conflict = OnConflict::column(Alias::new("id"));
                            on_conflict.update_columns(
                                crate::writer::columns(crate::records::table_of(batch))
                                    .iter()
                                    .filter(|&&column| column != "id")
                                    .map(|&column| Alias::new(column)),
                            );
                            statement.on_conflict(on_conflict);
                        }
                    }

                    statement
                })
            })
            .collect::<Vec<_>>();

        self.transaction(statements).await
    }

    /// Run every statement in one transaction, committing only when all of them land.
    async fn transaction<S: SqlxBinder>(&self, statements: Vec<S>) -> Result<(), Error> {
        match &self.backend {
            Backend::Sqlite(pool) => {
                let mut transaction = pool.begin().await?;
                for statement in statements {
                    let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                    sqlx::query_with(&sql, values)
                        .execute(&mut *transaction)
                        .await?;
                }

                transaction.commit().await?;
                Ok(())
            }
            Backend::Postgres(pool) => {
                let mut transaction = pool.begin().await?;
                for statement in statements {
                    let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                    sqlx::query_with(&sql, values)
                        .execute(&mut *transaction)
                        .await?;
                }

                transaction.commit().await?;
                Ok(())
            }
            Backend::Turso(_) => Err(Error::Unsupported),
        }
    }

    /// Write every batch of a bulk entity load in one transaction.
    ///
    /// The conflict target is the table's whole primary key, which for a variable or a
    /// setting is a pair of columns rather than an ID.
    pub async fn load_entities(
        &self,
        batches: &[Entities],
        conflict: Conflict,
    ) -> Result<(), Error> {
        let dialect = match self.dialect() {
            SqlDialect::SqliteText => crate::writer::Dialect::Sqlite,
            SqlDialect::Postgres => crate::writer::Dialect::Postgres,
        };
        let statements = batches
            .iter()
            .filter_map(|batch| {
                let schema = crate::entities::table_of(batch).schema();
                crate::writer::entity_load_statement(batch, dialect).map(|mut statement| {
                    let key = || schema.key.iter().map(|&column| Alias::new(column));
                    match conflict {
                        // Without a conflict clause a collision aborts the transaction,
                        // which is exactly what this mode promises.
                        Conflict::Error => {}
                        Conflict::Ignore => {
                            statement
                                .on_conflict(OnConflict::columns(key()).do_nothing().to_owned());
                        }
                        Conflict::Update => {
                            let mut on_conflict = OnConflict::columns(key());
                            on_conflict.update_columns(
                                crate::writer::entity_columns(batch)
                                    .iter()
                                    .filter(|column| !schema.key.contains(column))
                                    .map(|&column| Alias::new(column)),
                            );
                            statement.on_conflict(on_conflict);
                        }
                    }

                    statement
                })
            })
            .collect::<Vec<_>>();

        self.transaction(statements).await
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
    use crate::load::LoadFormat;

    /// Open a store over a fresh database holding the log table.
    async fn logs_store(directory: &std::path::Path) -> RecordStore {
        let path = directory.join("records.sqlite");
        let path = path.to_str().unwrap();
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true);
        let pool = SqlitePoolOptions::new()
            .connect_with(options)
            .await
            .unwrap();
        sqlx::query(
            "CREATE TABLE logs (id TEXT PRIMARY KEY, address TEXT, timestamp TEXT, \
             level TEXT, content TEXT)",
        )
        .execute(&pool)
        .await
        .unwrap();
        pool.close().await;

        RecordStore::sqlite_writable(path).unwrap()
    }

    /// The stored entries, ordered by content so a comparison is stable.
    async fn contents(store: &RecordStore) -> Vec<String> {
        let Records::LogEntries(entries) = store
            .fetch(RecordTable::Logs, None, None)
            .await
            .expect("the listing reads")
        else {
            panic!("expected log entries");
        };

        let mut contents: Vec<String> = entries.into_iter().map(|entry| entry.content).collect();
        contents.sort();
        contents
    }

    const FIRST: &str = "{\"id\": \"0198c0de-0000-7000-8000-000000000001\", \"address\": \"@a\", \
         \"timestamp\": \"2026-07-29T00:00:00Z\", \"level\": \"info\", \"content\": \"before\"}\n";
    const SECOND: &str = "{\"id\": \"0198c0de-0000-7000-8000-000000000001\", \"address\": \"@a\", \
         \"timestamp\": \"2026-07-29T00:00:00Z\", \"level\": \"info\", \"content\": \"after\"}\n";

    #[tokio::test]
    async fn conflict_modes_decide_what_a_collision_does() {
        let directory = tempfile::tempdir().unwrap();
        let store = logs_store(directory.path()).await;
        async fn load(store: &RecordStore, text: &str, conflict: Conflict) -> Result<(), Error> {
            let batches = crate::load::read(RecordTable::Logs, text, LoadFormat::Json).unwrap();
            store.load_records(&batches, conflict).await
        }

        load(&store, FIRST, Conflict::Error).await.unwrap();
        assert_eq!(contents(&store).await, vec!["before"]);

        // A collision aborts the transaction under the error mode, leaves the row alone
        // under ignore, and takes the incoming values under update.
        assert!(load(&store, SECOND, Conflict::Error).await.is_err());
        assert_eq!(contents(&store).await, vec!["before"]);

        load(&store, SECOND, Conflict::Ignore).await.unwrap();
        assert_eq!(contents(&store).await, vec!["before"]);

        load(&store, SECOND, Conflict::Update).await.unwrap();
        assert_eq!(contents(&store).await, vec!["after"]);
    }

    #[tokio::test]
    async fn a_failed_batch_rolls_every_earlier_one_back() {
        let directory = tempfile::tempdir().unwrap();
        let store = logs_store(directory.path()).await;

        let fresh = "{\"id\": \"0198c0de-0000-7000-8000-000000000009\", \"address\": \"@b\", \
             \"timestamp\": \"2026-07-29T00:00:00Z\", \"level\": \"info\", \"content\": \"fresh\"}\n";
        let text = format!("{FIRST}{fresh}{SECOND}");
        let batches = crate::load::read(RecordTable::Logs, &text, LoadFormat::Json).unwrap();

        assert!(store.load_records(&batches, Conflict::Error).await.is_err());
        assert!(contents(&store).await.is_empty());
    }

    #[tokio::test]
    async fn entity_rows_decode_whatever_storage_class_they_landed_in() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("records.sqlite");
        let path = path.to_str().unwrap();
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true);
        let pool = SqlitePoolOptions::new()
            .connect_with(options)
            .await
            .unwrap();

        // The column types are the migration's own. A `JSON` column carries none of
        // SQLite's affinity keywords, so it takes NUMERIC affinity and converts a
        // numeric-looking value out of the text the driver bound.
        sqlx::query(
            "CREATE TABLE variables (address TEXT, name TEXT, value JSON, \
             PRIMARY KEY (address, name))",
        )
        .execute(&pool)
        .await
        .unwrap();
        for (name, value) in [
            ("number", "5"),
            ("float", "1.5"),
            ("flag", "true"),
            ("text", "\"hello\""),
            ("structure", "{\"k\":1}"),
        ] {
            sqlx::query("INSERT INTO variables VALUES ('@a', ?, ?)")
                .bind(name)
                .bind(value)
                .execute(&pool)
                .await
                .unwrap();
        }

        // The affinity really does split the rows across storage classes, which is what
        // makes reading them all as text wrong.
        let classes: Vec<String> =
            sqlx::query_scalar("SELECT typeof(value) FROM variables ORDER BY name")
                .fetch_all(&pool)
                .await
                .unwrap();
        assert_eq!(
            classes,
            vec!["text", "real", "integer", "text", "text"],
            "the value column takes NUMERIC affinity"
        );

        pool.close().await;

        let store = RecordStore::sqlite(path).unwrap();
        let Entities::Variables(variables) = store
            .fetch_entities(EntityTable::Variables, None, None)
            .await
            .expect("the listing reads")
        else {
            panic!("expected variables");
        };

        // Ordered by the entity's own default, which is the key tuple.
        let held: Vec<(&str, serde_json::Value)> = variables
            .iter()
            .map(|variable| (variable.name.as_str(), variable.value.clone()))
            .collect();
        assert_eq!(
            held,
            vec![
                ("flag", serde_json::json!(true)),
                ("float", serde_json::json!(1.5)),
                ("number", serde_json::json!(5)),
                ("structure", serde_json::json!({"k": 1})),
                ("text", serde_json::json!("hello")),
            ]
        );
    }

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
