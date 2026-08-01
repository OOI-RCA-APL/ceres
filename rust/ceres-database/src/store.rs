//! Connection pools and query execution.

use ceres_entities::{Entities, Records};
use sea_query::{Alias, OnConflict, PostgresQueryBuilder, SelectStatement, SqliteQueryBuilder};
use sea_query_binder::SqlxBinder;
use sqlx::Row;
use sqlx::postgres::{PgConnectOptions, PgPool, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool, SqlitePoolOptions};

use crate::assign::assignments;
use crate::credentials::Credentials;
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
    /// The command asked for something the writer will not do, said in a sentence.
    ///
    /// Nothing was written, because a refusal happens before the transaction opens or
    /// rolls it back, so this is the command's own message to report.
    #[error("{0}")]
    Refused(String),
}

/// Build the connection options for a PostgreSQL database.
///
/// `settings` are per-connection server settings like `search_path`, which shape what a
/// query sees. `parameters` are the connection string's own, applied by name rather than
/// guessed at, because a connection that quietly ignored `sslmode` would not be the
/// connection that was configured.
pub(crate) fn postgres_options(
    host: &str,
    port: Option<u16>,
    database: &str,
    user: &str,
    password: Option<&str>,
    settings: Vec<(String, String)>,
    parameters: Vec<(String, String)>,
) -> Result<PgConnectOptions, Error> {
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

    for (key, value) in parameters {
        options = match key.as_str() {
            "sslmode" | "ssl_mode" => {
                let mode = value.parse().map_err(|_| {
                    Error::Refused(format!("`{value}` is not an SSL mode this connects with."))
                })?;
                options.ssl_mode(mode)
            }
            "sslrootcert" | "ssl_root_cert" => options.ssl_root_cert(&value),
            "sslcert" | "ssl_client_cert" => options.ssl_client_cert(&value),
            "sslkey" | "ssl_client_key" => options.ssl_client_key(&value),
            "application_name" => options.application_name(&value),
            "options" => options.options([("options", value.as_str())]),
            _ => {
                return Err(Error::Refused(format!(
                    "The database configuration sets the connection parameter `{key}`, \
                     which this does not know how to apply."
                )));
            }
        };
    }

    Ok(options)
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
        parameters: Vec<(String, String)>,
    ) -> Result<Self, Error> {
        let options = postgres_options(host, port, database, user, password, settings, parameters)?;
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

    /// Fetch the records a parsed native filter matches, a chunk at a time.
    ///
    /// Rows decode and reach `sink` as the driver yields them, so a dump of any size
    /// holds one chunk rather than the whole table. The sink decides what a chunk means,
    /// which for the CLI is rendering it and writing it out.
    pub async fn stream_filter(
        &self,
        filter: &RecordFilter,
        sink: &mut impl FnMut(Records) -> Result<(), Error>,
    ) -> Result<(), Error> {
        if filter.limit() == Some(0) {
            return sink(filter.table().empty());
        }

        let table = filter.table();
        let statement = filter.statement(self.dialect());
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let mut cursor = sqlx::query_with(&sql, values).fetch(pool);
                drain(&mut cursor, |rows| DecodeRecords::decode(table, rows), sink).await
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let mut cursor = sqlx::query_with(&sql, values).fetch(pool);
                drain(&mut cursor, |rows| DecodeRecords::decode(table, rows), sink).await
            }
            // Turso holds its result set behind its own cursor, which the backend walks
            // in chunks of its own.
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.stream(table, &sql, parameters, sink).await
            }
        }
    }

    /// Fetch the entities a parsed native filter matches, a chunk at a time.
    pub async fn stream_entity_filter(
        &self,
        filter: &EntityFilter,
        sink: &mut impl FnMut(Entities) -> Result<(), Error>,
    ) -> Result<(), Error> {
        if filter.limit() == Some(0) {
            return sink(filter.table().empty());
        }

        let table = filter.table();
        let statement = filter.statement(self.dialect());
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let mut cursor = sqlx::query_with(&sql, values).fetch(pool);
                drain(
                    &mut cursor,
                    |rows| DecodeEntities::decode(table, rows),
                    sink,
                )
                .await
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let mut cursor = sqlx::query_with(&sql, values).fetch(pool);
                drain(
                    &mut cursor,
                    |rows| DecodeEntities::decode(table, rows),
                    sink,
                )
                .await
            }
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.stream_entities(table, &sql, parameters, sink).await
            }
        }
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
    /// changed.
    ///
    /// Like a delete, this runs in its own transaction and commits only on success.
    pub async fn update_filter(&self, filter: &RecordFilter, assign: &str) -> Result<u64, Error> {
        let assignments = self
            .encode_assignments(filter.table().schema(), assign)
            .map_err(Error::Refused)?;
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.write(filter.update_statement(self.dialect(), &assignments))
            .await
    }

    /// Assign values and hand back the records that changed, for `--collect`.
    pub async fn update_filter_returning(
        &self,
        filter: &RecordFilter,
        assign: &str,
    ) -> Result<Records, Error> {
        let assignments = self
            .encode_assignments(filter.table().schema(), assign)
            .map_err(Error::Refused)?;
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let mut statement = filter.update_statement(self.dialect(), &assignments);
        statement.returning_all();
        self.write_returning(filter.table(), statement).await
    }

    /// Delete the records a parsed native filter matches and hand back the ones that
    /// went, for `--collect`.
    pub async fn delete_filter_returning(&self, filter: &RecordFilter) -> Result<Records, Error> {
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let mut statement = filter.delete_statement(self.dialect());
        statement.returning_all();
        self.write_returning(filter.table(), statement).await
    }

    /// Encode an update's assignments for this backend.
    ///
    /// A refusal carries the sentence to show, because the reader is holding a command
    /// line they can fix and the alternative is a validation dump.
    fn encode_assignments(
        &self,
        schema: crate::records::Schema,
        assign: &str,
    ) -> Result<Vec<crate::assign::Assignment>, String> {
        // The assignments are one YAML or JSON object, and anything else is not an
        // assignment at all.
        let values = match serde_norway::from_str(assign) {
            Ok(serde_json::Value::Object(values)) => values,
            Ok(_) => {
                return Err(
                    "--assign takes an object of column names and values, like                      `{\"name\": \"rate\"}`."
                        .to_string(),
                );
            }
            Err(error) => return Err(format!("--assign is not readable as JSON or YAML. {error}")),
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
    async fn write<S: SqlxBinder + sea_query::QueryStatementWriter>(
        &self,
        statement: S,
    ) -> Result<u64, Error> {
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
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.execute_write(&sql, parameters).await
            }
        }
    }

    /// Run one write statement that hands its rows back, in its own transaction.
    ///
    /// `RETURNING` is how a write says what it touched without a second query racing it,
    /// which is what `--collect` asks for. SQLite has had it since 3.35 and PostgreSQL
    /// always has.
    async fn write_returning<S: SqlxBinder + sea_query::QueryStatementWriter>(
        &self,
        table: RecordTable,
        statement: S,
    ) -> Result<Records, Error> {
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let mut transaction = pool.begin().await?;
                let rows = sqlx::query_with(&sql, values)
                    .fetch_all(&mut *transaction)
                    .await?;
                transaction.commit().await?;
                DecodeRecords::decode(table, rows)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let mut transaction = pool.begin().await?;
                let rows = sqlx::query_with(&sql, values)
                    .fetch_all(&mut *transaction)
                    .await?;
                transaction.commit().await?;
                DecodeRecords::decode(table, rows)
            }
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.query_write(table, &sql, parameters).await
            }
        }
    }

    /// The entity form of [`Self::write_returning`].
    async fn write_returning_entities<S: SqlxBinder + sea_query::QueryStatementWriter>(
        &self,
        table: EntityTable,
        statement: S,
    ) -> Result<Entities, Error> {
        match &self.backend {
            Backend::Sqlite(pool) => {
                let (sql, values) = statement.build_sqlx(SqliteQueryBuilder);
                let mut transaction = pool.begin().await?;
                let rows = sqlx::query_with(&sql, values)
                    .fetch_all(&mut *transaction)
                    .await?;
                transaction.commit().await?;
                DecodeEntities::decode(table, rows)
            }
            Backend::Postgres(pool) => {
                let (sql, values) = statement.build_sqlx(PostgresQueryBuilder);
                let mut transaction = pool.begin().await?;
                let rows = sqlx::query_with(&sql, values)
                    .fetch_all(&mut *transaction)
                    .await?;
                transaction.commit().await?;
                DecodeEntities::decode(table, rows)
            }
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.query_write_entities(table, &sql, parameters).await
            }
        }
    }

    /// Fetch an entity listing, ordered by the entity's own default.
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
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend.query_entities(table, &sql, parameters).await
            }
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
            Backend::Turso(backend) => {
                let (sql, values) = statement.build(SqliteQueryBuilder);
                let parameters = values
                    .into_iter()
                    .map(sea_value)
                    .collect::<Result<Vec<_>, _>>()?;
                backend
                    .query_entities(filter.table(), &sql, parameters)
                    .await
            }
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

    /// Read an entity update's assignment object, with the credential rules applied.
    ///
    /// A user's password hashes and their email address normalizes on the way in, the
    /// same rules a create follows, so a row written here is one the model would have
    /// written.
    fn entity_assignments(
        &self,
        filter: &EntityFilter,
        assign: &str,
        credentials: Option<Credentials>,
    ) -> Result<serde_json::Map<String, serde_json::Value>, Error> {
        let mut values = match serde_norway::from_str::<serde_json::Value>(assign) {
            Ok(serde_json::Value::Object(values)) => values,
            Ok(_) => {
                return Err(Error::Refused(
                    "--assign takes an object of column names and values, like \
                     `{\"name\": \"rate\"}`."
                        .to_string(),
                ));
            }
            Err(error) => {
                return Err(Error::Refused(format!(
                    "--assign is not readable as JSON or YAML. {error}"
                )));
            }
        };

        if filter.table() == EntityTable::Users {
            let Some(credentials) = credentials else {
                return Err(Error::Refused(
                    "This database hashes passwords in a way this command cannot reproduce, \
                     so it will not write a user."
                        .to_string(),
                ));
            };
            if !credentials.apply(filter.table(), &mut values) {
                return Err(Error::Refused(
                    "A user's password must be between 1 and 72 bytes, and their email \
                     address must be one this command can normalize."
                        .to_string(),
                ));
            }
        }

        Ok(values)
    }

    /// Assign values to the entities a parsed native filter matches, returning how many
    /// changed.
    pub async fn update_entity_filter(
        &self,
        filter: &EntityFilter,
        assign: &str,
        credentials: Option<Credentials>,
    ) -> Result<u64, Error> {
        let values = self.entity_assignments(filter, assign, credentials)?;
        let assignments = assignments(filter.table().schema(), &values, self.writer_dialect())
            .map_err(Error::Refused)?;
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.write(filter.update_statement(self.dialect(), &assignments))
            .await
    }

    /// Assign values and hand back the entities that changed, for `--collect`.
    pub async fn update_entity_filter_returning(
        &self,
        filter: &EntityFilter,
        assign: &str,
        credentials: Option<Credentials>,
    ) -> Result<Entities, Error> {
        let values = self.entity_assignments(filter, assign, credentials)?;
        let assignments = assignments(filter.table().schema(), &values, self.writer_dialect())
            .map_err(Error::Refused)?;
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let mut statement = filter.update_statement(self.dialect(), &assignments);
        statement.returning_all();
        self.write_returning_entities(filter.table(), statement)
            .await
    }

    /// Delete the entities a parsed native filter matches and hand back the ones that
    /// went, for `--collect`.
    pub async fn delete_entity_filter_returning(
        &self,
        filter: &EntityFilter,
    ) -> Result<Entities, Error> {
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let mut statement = filter.delete_statement(self.dialect());
        statement.returning_all();
        self.write_returning_entities(filter.table(), statement)
            .await
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

    /// Write a bulk load's batches in one transaction, reading as it writes.
    ///
    /// Batches arrive from a reader that walks its source, so a load of any size holds
    /// one batch rather than the whole file, matching the Python command. Nothing lands
    /// unless the whole load succeeds, so a collision under `Conflict::Error`, or a row
    /// the reader refuses, leaves the table exactly as it was. Answers how many rows were
    /// written.
    pub async fn load_records(
        &self,
        batches: impl Iterator<Item = Result<Records, String>>,
        conflict: Conflict,
    ) -> Result<usize, Error> {
        let dialect = self.writer_dialect();
        self.write_batches(batches.map(|batch| {
            let batch = batch?;
            let rows = batch.len();
            let mut statement = crate::writer::load_statement(&batch, dialect)
                .ok_or_else(|| "A row holds a value this command cannot store.".to_string())?;
            let key = crate::records::table_of(&batch).schema().key;
            on_conflict(
                &mut statement,
                conflict,
                key,
                crate::writer::columns(crate::records::table_of(&batch)),
            );
            Ok((statement, rows))
        }))
        .await
    }

    /// Write a bulk entity load's batches in one transaction, reading as it writes.
    ///
    /// The conflict target is the table's whole primary key, which for a variable or a
    /// setting is a pair of columns rather than an ID.
    pub async fn load_entities(
        &self,
        batches: impl Iterator<Item = Result<Entities, String>>,
        conflict: Conflict,
    ) -> Result<usize, Error> {
        let dialect = self.writer_dialect();
        self.write_batches(batches.map(|batch| {
            let batch = batch?;
            let rows = batch.len();
            let mut statement = crate::writer::entity_load_statement(&batch, dialect)
                .ok_or_else(|| "A row holds a value this command cannot store.".to_string())?;
            let schema = crate::entities::table_of(&batch).schema();
            on_conflict(
                &mut statement,
                conflict,
                schema.key,
                crate::writer::entity_columns(&batch),
            );
            Ok((statement, rows))
        }))
        .await
    }

    /// The value forms this store's backend binds on the write path.
    fn writer_dialect(&self) -> crate::writer::Dialect {
        match self.dialect() {
            SqlDialect::SqliteText => crate::writer::Dialect::Sqlite,
            SqlDialect::Postgres => crate::writer::Dialect::Postgres,
        }
    }

    /// Execute a load's batches in one transaction, committing only when all of them
    /// land.
    ///
    /// The batches are pulled one at a time, so the reader behind them walks its source
    /// as the writes go out rather than collecting it first. A batch of `None` is a row
    /// the reader refused, which rolls everything back by returning before the commit and
    /// reports which row it was.
    async fn write_batches(
        &self,
        mut batches: impl Iterator<Item = Result<(sea_query::InsertStatement, usize), String>>,
    ) -> Result<usize, Error> {
        macro_rules! run {
            ($pool:expr, $builder:expr) => {{
                let mut transaction = $pool.begin().await?;
                let mut written = 0;
                for batch in &mut batches {
                    // Dropping the transaction rolls it back, so the table is exactly as
                    // it was and the refusal is the command's own to report.
                    let (statement, rows) = batch.map_err(Error::Refused)?;

                    let (sql, values) = statement.build_sqlx($builder);
                    sqlx::query_with(&sql, values)
                        .execute(&mut *transaction)
                        .await?;
                    written += rows;
                }

                transaction.commit().await?;
                Ok(written)
            }};
        }

        match &self.backend {
            Backend::Sqlite(pool) => run!(pool, SqliteQueryBuilder),
            Backend::Postgres(pool) => run!(pool, PostgresQueryBuilder),
            Backend::Turso(backend) => {
                // The engine takes its statements together rather than one at a time, so
                // the batches are built here and the transaction is its own.
                let mut statements = Vec::new();
                let mut written = 0;
                for batch in &mut batches {
                    let (statement, rows) = batch.map_err(Error::Refused)?;
                    let (sql, values) = statement.build(SqliteQueryBuilder);
                    let parameters = values
                        .into_iter()
                        .map(sea_value)
                        .collect::<Result<Vec<_>, _>>()?;
                    statements.push((sql, parameters));
                    written += rows;
                }

                backend.execute_transaction(statements).await?;
                Ok(written)
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
                let rows = bind_sqlite(sqlx::query(sql), parameters)
                    .fetch_all(pool)
                    .await?;
                DecodeRecords::decode(table, rows)
            }
            Backend::Postgres(pool) => {
                let rows = bind_postgres(sqlx::query(sql), parameters)
                    .fetch_all(pool)
                    .await?;
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

    /// Execute a compiled record query, decoding its rows a chunk at a time.
    ///
    /// The chunked twin of [`fetch_sql`](Self::fetch_sql), so a dump of a table of any
    /// size renders and writes as it reads rather than holding the whole result.
    pub async fn stream_sql(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: &mut impl FnMut(Records) -> Result<(), Error>,
    ) -> Result<(), Error> {
        let head = sql.trim_start();
        if !starts_with_keyword(head, "select") && !starts_with_keyword(head, "with") {
            return Err(Error::Decode("only SELECT statements execute here".into()));
        }

        match &self.backend {
            Backend::Sqlite(pool) => {
                let mut cursor = bind_sqlite(sqlx::query(sql), parameters).fetch(pool);
                drain(&mut cursor, |rows| DecodeRecords::decode(table, rows), sink).await
            }
            Backend::Postgres(pool) => {
                let mut cursor = bind_postgres(sqlx::query(sql), parameters).fetch(pool);
                drain(&mut cursor, |rows| DecodeRecords::decode(table, rows), sink).await
            }
            Backend::Turso(backend) => {
                let parameters = parameters.into_iter().map(parameter_value).collect();
                backend.stream(table, sql, parameters, sink).await
            }
        }
    }

    /// Execute a statement that returns rows, decoding them by column.
    ///
    /// The query layer compiles its own statement and then reads whatever it selected,
    /// so this decodes by column rather than into a table's struct. Values arrive in the
    /// form their column declares, which is what lets one caller read the same row the
    /// same way on every backend.
    pub async fn fetch_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Vec<crate::dynamic::Row>, Error> {
        match &self.backend {
            Backend::Sqlite(pool) => bind_sqlite(sqlx::query(sql), parameters)
                .fetch_all(pool)
                .await?
                .iter()
                .map(|row| crate::dynamic::sqlite_row(row, table))
                .collect(),
            Backend::Postgres(pool) => bind_postgres(sqlx::query(sql), parameters)
                .fetch_all(pool)
                .await?
                .iter()
                .map(crate::dynamic::postgres_row)
                .collect(),
            Backend::Turso(backend) => {
                let parameters = parameters.into_iter().map(parameter_value).collect();
                backend.query_dynamic(table, sql, parameters).await
            }
        }
    }

    /// Execute a statement that returns no rows, answering how many it touched.
    pub async fn execute_dynamic(
        &self,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<u64, Error> {
        match &self.backend {
            Backend::Sqlite(pool) => Ok(bind_sqlite(sqlx::query(sql), parameters)
                .execute(pool)
                .await?
                .rows_affected()),
            Backend::Postgres(pool) => Ok(bind_postgres(sqlx::query(sql), parameters)
                .execute(pool)
                .await?
                .rows_affected()),
            Backend::Turso(backend) => {
                let parameters = parameters.into_iter().map(parameter_value).collect();
                backend.execute_dynamic(sql, parameters).await
            }
        }
    }

    /// Run a script of `;`-separated statements.
    ///
    /// `raw_sql` sends the whole script, so the driver separates the statements rather
    /// than this guessing where one ends. A migration relies on that, since a `PRAGMA`
    /// the SQLite family needs before rebuilding a table does nothing inside a
    /// transaction, and a script sent whole is the driver's business to sequence.
    pub async fn execute_script(&self, sql: &str) -> Result<(), Error> {
        match &self.backend {
            Backend::Sqlite(pool) => {
                sqlx::raw_sql(sql).execute(pool).await?;
                Ok(())
            }
            Backend::Postgres(pool) => {
                sqlx::raw_sql(sql).execute(pool).await?;
                Ok(())
            }
            Backend::Turso(backend) => backend.execute_script(sql).await,
        }
    }
}

/// Bind compiled parameters onto a SQLite statement.
///
/// SQLite stores timestamps and UUIDs as text, so those bind in the stored form rather
/// than as their own types, or equality against a stored row misses.
fn bind_sqlite<'q>(
    mut query: sqlx::query::Query<'q, sqlx::Sqlite, sqlx::sqlite::SqliteArguments<'q>>,
    parameters: Vec<Parameter>,
) -> sqlx::query::Query<'q, sqlx::Sqlite, sqlx::sqlite::SqliteArguments<'q>> {
    for parameter in parameters {
        query = match parameter {
            Parameter::Null => query.bind(None::<String>),
            Parameter::Bool(value) => query.bind(value),
            Parameter::Integer(value) => query.bind(value),
            Parameter::Float(value) => query.bind(value),
            Parameter::Text(value) => query.bind(value),
            Parameter::Bytes(value) => query.bind(value),
            Parameter::Timestamp(value) => query.bind(Parameter::timestamp_text(&value)),
            Parameter::Uuid(value) => query.bind(value.to_string()),
        };
    }

    query
}

/// Bind compiled parameters onto a PostgreSQL statement, which takes timestamps and
/// UUIDs as themselves.
fn bind_postgres<'q>(
    mut query: sqlx::query::Query<'q, sqlx::Postgres, sqlx::postgres::PgArguments>,
    parameters: Vec<Parameter>,
) -> sqlx::query::Query<'q, sqlx::Postgres, sqlx::postgres::PgArguments> {
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

    query
}

/// Apply a load's conflict mode to one insert, over the table's whole primary key.
fn on_conflict(
    statement: &mut sea_query::InsertStatement,
    conflict: Conflict,
    key: &[&'static str],
    columns: &[&'static str],
) {
    let target = || key.iter().map(|&column| Alias::new(column));
    match conflict {
        // Without a conflict clause a collision aborts the transaction, which is exactly
        // what this mode promises.
        Conflict::Error => {}
        Conflict::Ignore => {
            statement.on_conflict(OnConflict::columns(target()).do_nothing().to_owned());
        }
        Conflict::Update => {
            let mut clause = OnConflict::columns(target());
            clause.update_columns(
                columns
                    .iter()
                    .filter(|column| !key.contains(column))
                    .map(|&column| Alias::new(column)),
            );
            statement.on_conflict(clause);
        }
    }
}

/// How many rows one streamed chunk carries.
///
/// A dump decodes, renders, and writes per chunk rather than whole, so memory stays flat
/// over a table of any size. The size also decides how much of a result a caller can
/// hold back before writing, which is what keeps a late refusal able to delegate.
pub const CHUNK: usize = 1000;

/// Walk a row cursor, decoding and handing over one chunk at a time.
///
/// A chunk decodes only once it is full, so a decode failure surfaces having produced no
/// partial batch, and the trailing rows go over even when they do not fill one.
async fn drain<Row, Batch, Cursor>(
    cursor: &mut Cursor,
    decode: impl Fn(Vec<Row>) -> Result<Batch, Error>,
    sink: &mut impl FnMut(Batch) -> Result<(), Error>,
) -> Result<(), Error>
where
    Cursor: futures_util::Stream<Item = Result<Row, sqlx::Error>> + Unpin,
{
    use futures_util::StreamExt;

    let mut buffer = Vec::with_capacity(CHUNK);
    let mut sent = false;
    while let Some(row) = cursor.next().await {
        buffer.push(row?);
        if buffer.len() == CHUNK {
            sink(decode(std::mem::take(&mut buffer))?)?;
            sent = true;
            buffer.reserve(CHUNK);
        }
    }

    // An empty result still reaches the sink once, because a CSV dump writes its header
    // row whether or not any record follows it.
    if !buffer.is_empty() || !sent {
        sink(decode(buffer)?)?;
    }

    Ok(())
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
            let batches =
                crate::load::batches(RecordTable::Logs, text.as_bytes(), LoadFormat::Json)
                    .expect("the reader opens");
            store.load_records(batches, conflict).await.map(|_| ())
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
        let batches = crate::load::batches(RecordTable::Logs, text.as_bytes(), LoadFormat::Json)
            .expect("the reader opens");

        assert!(store.load_records(batches, Conflict::Error).await.is_err());
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
