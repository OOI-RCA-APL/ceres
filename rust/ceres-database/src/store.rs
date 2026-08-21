//! Connection parameters and the operations a database serves.
//!
//! Everything here is written once against [`DatabaseBackend`], the trait in
//! [`crate::backend`] that every backend implements. Building a statement and choosing a
//! backend are separate concerns so this file holds the first and knows nothing of the
//! second beyond which dialect it renders for.

use std::sync::Arc;

use ceres_entities::{Entities, Records};
use sea_query::{Alias, OnConflict, SelectStatement};
use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};

use crate::backend::{DatabaseBackend, PostgresBackend, Sink, SqliteBackend, Write, Writing};
use crate::credentials::Credentials;
use crate::dynamic::Cell;
use crate::entities::EntityTable;
use crate::filter::{EntityFilter, Filter, RecordFilter, SqlDialect, Tabled};
use crate::load::Conflict;
use crate::records::RecordTable;
use crate::selector::Scope;
use crate::turso::TursoBackend;

/// How many branches a listing expands over before the plain statement is used instead.
///
/// Every branch is a seek and a subquery, so the union stops being the cheaper shape once a
/// selector reaches a whole deployment's components rather than one subtree. The cap bounds the
/// statement rather than picking the faster plan, the range form it falls back to being
/// proportional to the table however many branches there are.
const BRANCH_CAP: usize = 256;

/// A statement parameter, as the Python layer's bind processors produce them.
///
/// Most values arrive as primitives, but the PostgreSQL driver takes timestamps and UUIDs
/// natively so its processors pass those through as objects.
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
    /// A whole JSON document, for the columns that store one.
    ///
    /// Separate from [`Text`](Parameter::Text) because PostgreSQL's `jsonb` refuses a
    /// text bind while SQLite stores the same document as its serialized text so the
    /// column's type decides the binding.
    Json(serde_json::Value),
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
    #[error("{}", database_message(.0))]
    Database(#[from] sqlx::Error),
    #[error(transparent)]
    Turso(#[from] turso::Error),
    #[error("{0}")]
    Connect(String),
    #[error("{0}")]
    Decode(String),
    #[error("the native path does not serve this operation on this backend")]
    Unsupported,
    /// The writer refused the command, with a user-facing message to report.
    ///
    /// Nothing was written because a refusal happens before the transaction opens or
    /// rolls it back.
    #[error("{0}")]
    Refused(String),
}

/// Create the directories leading to a local database file.
///
/// A backend that creates its own missing file creates the directories holding it too, so a
/// configured path works on a first run rather than failing to open.
pub(crate) fn create_parent_directories(path: &str) -> Result<(), Error> {
    let parent = std::path::Path::new(path).parent().unwrap_or_else(|| {
        // A bare filename names the working directory, which is already there.
        std::path::Path::new("")
    });
    if parent.as_os_str().is_empty() {
        return Ok(());
    }

    std::fs::create_dir_all(parent).map_err(|error| {
        Error::Connect(format!(
            "could not create the directory {}: {error}",
            parent.display()
        ))
    })
}

/// Attach a configuration's connection lifecycle statements to a pool.
///
/// These are the `init`, `connect`, and `close` hooks a database configuration declares,
/// and they run after whatever this backend sets for itself. A statement that fails on
/// connect fails the checkout because a connection that skipped its setup is not the
/// connection that was configured. One that fails on release retires the connection
/// instead of reporting, the caller having already finished with it by then.
///
/// The `init` statements belong to the database rather than to a connection so they run
/// on whichever connection opens first and on no other. A failure leaves them un-run, so
/// the next connection to open tries again rather than the database going without them.
pub(crate) fn lifecycle<DB>(
    options: sqlx::pool::PoolOptions<DB>,
    on_init: Vec<String>,
    on_connect: Vec<String>,
    on_close: Vec<String>,
) -> sqlx::pool::PoolOptions<DB>
where
    DB: sqlx::Database,
    for<'c> &'c mut DB::Connection: sqlx::Executor<'c, Database = DB>,
{
    use sqlx::{AssertSqlSafe, Executor};

    let mut options = options;
    if !on_init.is_empty() || !on_connect.is_empty() {
        let initial = std::sync::Arc::new(on_init);
        let statements = std::sync::Arc::new(on_connect);
        let started = std::sync::Arc::new(tokio::sync::OnceCell::new());
        options = options.after_connect(move |connection, _| {
            let initial = initial.clone();
            let statements = statements.clone();
            let started = started.clone();
            Box::pin(async move {
                started
                    .get_or_try_init(|| async {
                        for statement in initial.iter() {
                            connection.execute(AssertSqlSafe(statement.clone())).await?;
                        }

                        Ok::<(), sqlx::Error>(())
                    })
                    .await?;

                // One at a time because these are separate configured statements rather
                // than a script, and the one that failed is the one worth naming.
                for statement in statements.iter() {
                    connection.execute(AssertSqlSafe(statement.clone())).await?;
                }

                Ok(())
            })
        });
    }

    if !on_close.is_empty() {
        let statements = std::sync::Arc::new(on_close);
        options = options.after_release(move |connection, _| {
            let statements = statements.clone();
            Box::pin(async move {
                for statement in statements.iter() {
                    connection.execute(AssertSqlSafe(statement.clone())).await?;
                }

                Ok(false)
            })
        });
    }

    options
}

/// A driver failure in the driver's own words, with the detail it offered.
///
/// PostgreSQL names the broken constraint on the first line and the offending column
/// and value on a `DETAIL` line. Callers classify failures from this wording, so
/// dropping the detail would lose which column and value collided.
fn database_message(error: &sqlx::Error) -> String {
    let sqlx::Error::Database(database) = error else {
        return error.to_string();
    };

    match database.try_downcast_ref::<sqlx::postgres::PgDatabaseError>() {
        Some(postgres) => match postgres.detail() {
            Some(detail) => format!("{postgres}\nDETAIL:  {detail}"),
            None => postgres.to_string(),
        },
        None => database.to_string(),
    }
}

/// Build the connection options for a PostgreSQL database.
///
/// `settings` are per-connection server settings like `search_path`, which shape what a
/// query sees. `parameters` are the connection string's own, applied by name and
/// refused when unrecognized because silently ignoring `sslmode` would connect
/// differently than configured.
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

/// A natively-connected view of a Ceres database, serving entity reads.
///
/// Connections open lazily on first use so building a store is cheap and never touches
/// the database. The store connects to the same database the Python layer resolved,
/// including per-instance temporary SQLite paths, which is why it takes resolved
/// connection parameters rather than a configuration.
///
/// Which backend is behind it is known only through the private `DatabaseBackend` trait
/// so every operation below is written once.
pub struct RecordStore {
    backend: Arc<dyn DatabaseBackend>,
}

impl RecordStore {
    /// Open a read-only store over a SQLite database file.
    ///
    /// `on_connect` and `on_close` are the configuration's own statements for the two
    /// ends of a connection's life. The `init` statements belong to whichever store
    /// opens the database for writing because a read-only connection cannot set them.
    pub fn sqlite(
        path: &str,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Result<Self, Error> {
        let options = SqliteConnectOptions::new().filename(path).read_only(true);
        let pool = lifecycle(SqlitePoolOptions::new(), Vec::new(), on_connect, on_close)
            .connect_lazy_with(options);
        Ok(Self {
            backend: Arc::new(SqliteBackend(pool)),
        })
    }

    /// Open a writable store over a SQLite database file.
    ///
    /// The connection carries the query layer's busy timeout and foreign key enforcement,
    /// and holds one connection since the backend serializes writers anyway.
    ///
    /// A missing file is created, along with the directories leading to it, since the store
    /// runs migrations and a database has no file before its first one. Callers that mean to
    /// read an existing database check for it themselves.
    ///
    /// Incremental `auto_vacuum` is set here because the setting only takes on an empty
    /// database, and one that missed it can only reclaim freed pages through a full
    /// `VACUUM`.
    ///
    /// `on_init`, `on_connect`, and `on_close` are the configuration's statements for the
    /// first connection and the two ends of every connection's life, run after this
    /// backend's own.
    pub fn sqlite_writable(
        path: &str,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Result<Self, Error> {
        create_parent_directories(path)?;
        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .busy_timeout(std::time::Duration::from_secs(30))
            .auto_vacuum(sqlx::sqlite::SqliteAutoVacuum::Incremental)
            .foreign_keys(true);
        let pool = lifecycle(
            SqlitePoolOptions::new().max_connections(1),
            on_init,
            on_connect,
            on_close,
        )
        .connect_lazy_with(options);
        Ok(Self {
            backend: Arc::new(SqliteBackend(pool)),
        })
    }

    /// Open a store over a PostgreSQL database.
    ///
    /// `settings` are per-connection server settings like `search_path`. `on_init`,
    /// `on_connect`, and `on_close` are the statements a configuration asked to run on the
    /// first connection and at the two ends of every connection's life.
    #[allow(clippy::too_many_arguments)]
    pub fn postgres(
        host: &str,
        port: Option<u16>,
        database: &str,
        user: &str,
        password: Option<&str>,
        settings: Vec<(String, String)>,
        parameters: Vec<(String, String)>,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Result<Self, Error> {
        let options = postgres_options(host, port, database, user, password, settings, parameters)?;
        let pool = lifecycle(PgPoolOptions::new(), on_init, on_connect, on_close)
            .connect_lazy_with(options);
        Ok(Self {
            backend: Arc::new(PostgresBackend(pool)),
        })
    }

    /// Open a store over a Turso database file.
    ///
    /// When `mvcc` is set, each connection enables MVCC journaling. `on_init`,
    /// `on_connect`, and `on_close` are the statements a configuration asked to run on the
    /// first connection and at the two ends of every connection's life, in order, after
    /// this backend's own.
    ///
    /// This backend opens a connection per operation rather than pooling them so a
    /// connection reaches its close at the end of the operation that opened it, and the
    /// `close` statements run there rather than on return to a pool.
    pub fn turso(
        path: &str,
        mvcc: bool,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Self {
        Self {
            backend: Arc::new(TursoBackend::new(path, mvcc, on_init, on_connect, on_close)),
        }
    }

    /// Whether two write transactions on this database can overlap.
    ///
    /// `false` says a [`Writing::Concurrent`] transaction ran serialized anyway so no
    /// commit conflict is possible and a caller that would retry one never has to.
    pub fn overlaps_writers(&self) -> bool {
        self.backend.overlaps_writers()
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
    pub fn dialect(&self) -> SqlDialect {
        self.backend.dialect()
    }

    /// Execute one built statement, decoding rows for the table.
    async fn select(
        &self,
        table: RecordTable,
        statement: SelectStatement,
    ) -> Result<Records, Error> {
        self.backend.select_records(table, statement).await
    }

    /// Fetch the records a parsed native filter matches.
    pub async fn fetch_filter(&self, filter: &RecordFilter) -> Result<Records, Error> {
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let statement = self
            .listing_statement(filter, filter.table().schema().name)
            .await?;
        self.select(filter.table(), statement).await
    }

    /// The listing statement to run, expanded over the selector's branches where that pays.
    ///
    /// A subtree selector compiles to a range on the address, which finds its rows but returns
    /// them ordered by address rather than by the sort column, so the whole subtree is read and
    /// sorted to answer for one page. Seeking each branch separately keeps the ordering, at one
    /// seek per branch. Falls back to the plain statement whenever the rewrite would not hold.
    async fn listing_statement<T: Tabled>(
        &self,
        filter: &Filter<T>,
        table: &str,
    ) -> Result<SelectStatement, Error> {
        let Some(scope) = filter.expansion_scope() else {
            return Ok(filter.statement(self.dialect(), None));
        };

        let branches = self.discover_branches(table, "address", &scope).await?;

        // No branches means nothing was written under the selector, which the plain statement
        // answers as cheaply. Past the cap the union grows longer than the scan it replaces.
        if branches.is_empty() || branches.len() > BRANCH_CAP {
            return Ok(filter.statement(self.dialect(), None));
        }

        Ok(filter.statement_over(&branches, self.dialect(), None))
    }

    /// The distinct addresses a scope covers, read from the records themselves.
    ///
    /// Discovery reads the data rather than the configuration, because a decommissioned
    /// component's history is reachable only if its address is still discoverable, and that is
    /// the case this whole rewrite exists to serve.
    ///
    /// Each hop seeks to the next distinct value, so the cost is one index seek per branch
    /// rather than one per row. The bounds are a range and never a prefix pattern, a pattern's
    /// residual per-row check defeating the `min()` short-circuit while reporting an identical
    /// query plan.
    async fn discover_branches(
        &self,
        table: &str,
        column: &str,
        scope: &Scope,
    ) -> Result<Vec<String>, Error> {
        let mut found: Vec<String> = scope.literals.clone();
        let ranges: Vec<(Option<String>, Option<String>)> = if scope.unbounded {
            vec![(None, None)]
        } else {
            scope
                .prefixes
                .iter()
                .map(|prefix| (Some(prefix.clone()), Some(Scope::ceiling(prefix))))
                .collect()
        };

        for (floor, ceiling) in ranges {
            let walked = self.walk_distinct(table, column, &floor, &ceiling).await?;
            found.extend(walked);
            if found.len() > BRANCH_CAP {
                break;
            }
        }

        found.sort();
        found.dedup();
        Ok(found)
    }

    /// Walk one range's distinct values, seeking from each to the next.
    async fn walk_distinct(
        &self,
        table: &str,
        column: &str,
        floor: &Option<String>,
        ceiling: &Option<String>,
    ) -> Result<Vec<String>, Error> {
        let mut found = Vec::new();
        let mut cursor = floor.clone();
        let mut inclusive = floor.is_some();
        while found.len() <= BRANCH_CAP {
            let mut conditions = Vec::new();
            let mut parameters = Vec::new();
            if let Some(cursor) = &cursor {
                let comparison = if inclusive { ">=" } else { ">" };
                parameters.push(Parameter::Text(cursor.clone()));
                conditions.push(format!("\"{column}\" {comparison} {}", self.placeholder(1)));
            }

            if let Some(ceiling) = ceiling {
                parameters.push(Parameter::Text(ceiling.clone()));
                conditions.push(format!(
                    "\"{column}\" < {}",
                    self.placeholder(parameters.len())
                ));
            }

            let where_clause = if conditions.is_empty() {
                String::new()
            } else {
                format!(" WHERE {}", conditions.join(" AND "))
            };
            let sql = format!("SELECT min(\"{column}\") AS next FROM \"{table}\"{where_clause}");
            let rows = self.backend.query_rows(None, &sql, parameters).await?;
            let next = rows.first().and_then(|row| match row.first() {
                Some((_, Cell::Text(value))) => Some(value.clone()),
                _ => None,
            });

            let Some(next) = next else { break };
            found.push(next.clone());
            cursor = Some(next);
            inclusive = false;
        }

        Ok(found)
    }

    /// One bind placeholder, numbered where the dialect wants it numbered.
    fn placeholder(&self, position: usize) -> String {
        match self.dialect() {
            SqlDialect::Postgres => format!("${position}"),
            SqlDialect::SqliteText => "?".to_string(),
        }
    }

    /// Fetch the records a parsed native filter matches, a chunk at a time.
    ///
    /// Rows decode and reach `sink` as the driver yields them so a dump of any size
    /// holds one chunk rather than the whole table. The sink decides what a chunk means,
    /// which for the CLI is rendering it and writing it out.
    pub async fn stream_filter(
        &self,
        filter: &RecordFilter,
        sink: &mut (impl FnMut(Records) -> Result<(), Error> + Send),
    ) -> Result<(), Error> {
        self.stream_matches(filter, sink).await
    }

    /// Fetch the entities a parsed native filter matches, a chunk at a time.
    pub async fn stream_entity_filter(
        &self,
        filter: &EntityFilter,
        sink: &mut (impl FnMut(Entities) -> Result<(), Error> + Send),
    ) -> Result<(), Error> {
        self.stream_matches(filter, sink).await
    }

    /// Count the records a parsed native filter matches.
    ///
    /// A limit or offset bounds the count itself, matching the Python layer's paged
    /// counting.
    pub async fn count_filter(&self, filter: &RecordFilter) -> Result<u64, Error> {
        self.count_matches(filter).await
    }

    /// Whether any record matches a parsed native filter.
    ///
    /// Existence stops at the first matching row so this stays cheap on a large table
    /// where counting would not.
    pub async fn any_filter(&self, filter: &RecordFilter) -> Result<bool, Error> {
        self.any_matches(filter).await
    }

    /// Delete the records a parsed native filter matches, returning the deleted count.
    ///
    /// The delete runs in its own transaction and commits only on success so a failure
    /// leaves the table untouched and the command is free to delegate.
    pub async fn delete_filter(&self, filter: &RecordFilter) -> Result<u64, Error> {
        self.delete_matches(filter).await
    }

    /// Assign values to the records a parsed native filter matches, returning how many
    /// changed.
    ///
    /// Like a delete, this runs in its own transaction and commits only on success.
    pub async fn update_filter(&self, filter: &RecordFilter, set: &str) -> Result<u64, Error> {
        self.update_matches(filter, set, None).await
    }

    /// Assign values and return the records that changed, for `--collect`.
    pub async fn update_filter_returning(
        &self,
        filter: &RecordFilter,
        set: &str,
    ) -> Result<Records, Error> {
        self.update_matches_returning(filter, set, None).await
    }

    /// Delete the records a parsed native filter matches and return the deleted rows,
    /// for `--collect`.
    pub async fn delete_filter_returning(&self, filter: &RecordFilter) -> Result<Records, Error> {
        self.delete_matches_returning(filter).await
    }

    /// Fetch what a parsed native filter matches, a chunk at a time.
    async fn stream_matches<T: Stored>(
        &self,
        filter: &Filter<T>,
        sink: &mut (impl FnMut(T::Batch) -> Result<(), Error> + Send),
    ) -> Result<(), Error> {
        if filter.limit() == Some(0) {
            return sink(filter.table().empty());
        }

        let statement = self
            .listing_statement(filter, filter.table().schema().name)
            .await?;
        T::stream(self.backend.as_ref(), filter.table(), statement, sink).await
    }

    /// Count what a parsed native filter matches.
    async fn count_matches<T: Tabled>(&self, filter: &Filter<T>) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.scalar_count(filter.count_statement(self.dialect(), None))
            .await
    }

    /// Whether any row matches a parsed native filter.
    async fn any_matches<T: Tabled>(&self, filter: &Filter<T>) -> Result<bool, Error> {
        if filter.limit() == Some(0) {
            return Ok(false);
        }

        self.backend
            .exists(filter.exists_statement(self.dialect(), None))
            .await
    }

    /// Delete what a parsed native filter matches, returning the deleted count.
    async fn delete_matches<T: Tabled>(&self, filter: &Filter<T>) -> Result<u64, Error> {
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.write(filter.delete_statement(self.dialect(), None))
            .await
    }

    /// Delete what a parsed native filter matches and return the deleted rows.
    async fn delete_matches_returning<T: Stored>(
        &self,
        filter: &Filter<T>,
    ) -> Result<T::Batch, Error> {
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let mut statement = filter.delete_statement(self.dialect(), None);
        statement.returning_all();
        T::write_returning(self.backend.as_ref(), filter.table(), statement.into()).await
    }

    /// Assign values to what a parsed native filter matches, returning how many rows
    /// changed.
    async fn update_matches<T: Stored>(
        &self,
        filter: &Filter<T>,
        set: &str,
        credentials: Option<Credentials>,
    ) -> Result<u64, Error> {
        let set_clauses = self.set_clauses(filter, set, credentials)?;
        if filter.limit() == Some(0) {
            return Ok(0);
        }

        self.write(filter.update_statement(self.dialect(), &set_clauses, None))
            .await
    }

    /// Assign values to what a parsed native filter matches and return the changed
    /// rows.
    async fn update_matches_returning<T: Stored>(
        &self,
        filter: &Filter<T>,
        set: &str,
        credentials: Option<Credentials>,
    ) -> Result<T::Batch, Error> {
        let set_clauses = self.set_clauses(filter, set, credentials)?;
        if filter.limit() == Some(0) {
            return Ok(filter.table().empty());
        }

        let mut statement = filter.update_statement(self.dialect(), &set_clauses, None);
        statement.returning_all();
        T::write_returning(self.backend.as_ref(), filter.table(), statement.into()).await
    }

    /// Encode an update's set clauses for this backend, with the rules the table
    /// imposes on a write applied first.
    ///
    /// A refusal carries a user-facing message because the reader is fixing a
    /// command line.
    fn set_clauses<T: Stored>(
        &self,
        filter: &Filter<T>,
        set: &str,
        credentials: Option<Credentials>,
    ) -> Result<Vec<crate::set::SetClause>, Error> {
        // The values are one YAML or JSON object, and anything else is not a set
        // object at all.
        let mut values = match yaml_serde::from_str(set) {
            Ok(serde_json::Value::Object(values)) => values,
            Ok(_) => {
                return Err(Error::Refused(
                    "--set takes an object of column names and values, like \
                     `{\"name\": \"rate\"}`."
                        .to_string(),
                ));
            }
            Err(error) => {
                return Err(Error::Refused(format!(
                    "--set is not readable as JSON or YAML. {error}"
                )));
            }
        };

        T::prepare(filter.table(), &mut values, credentials)?;
        filter
            .table()
            .schema()
            .set_clauses(&values, self.dialect())
            .map_err(Error::Refused)
    }

    /// Run one write statement in its own transaction, returning how many rows changed.
    ///
    /// Nothing lands unless the statement succeeds so a failure leaves the table
    /// exactly as it was and the command is free to delegate.
    async fn write(&self, statement: impl Into<Write>) -> Result<u64, Error> {
        self.backend.write(statement.into()).await
    }

    /// Count the entities a parsed native filter matches.
    pub async fn count_entity_filter(&self, filter: &EntityFilter) -> Result<u64, Error> {
        self.count_matches(filter).await
    }

    /// Whether any entity matches a parsed native filter.
    pub async fn any_entity_filter(&self, filter: &EntityFilter) -> Result<bool, Error> {
        self.any_matches(filter).await
    }

    /// Delete the entities a parsed native filter matches, returning the deleted
    /// count.
    ///
    /// Like every native write this runs in its own transaction and commits only on
    /// success so a failure leaves the table untouched and the command may delegate.
    pub async fn delete_entity_filter(&self, filter: &EntityFilter) -> Result<u64, Error> {
        self.delete_matches(filter).await
    }

    /// Assign values to the entities a parsed native filter matches, returning how many
    /// changed.
    ///
    /// A user's password hashes and their email address normalizes on the way in, the
    /// same rules a create follows so a row written here is one the model would have
    /// written.
    pub async fn update_entity_filter(
        &self,
        filter: &EntityFilter,
        set: &str,
        credentials: Option<Credentials>,
    ) -> Result<u64, Error> {
        self.update_matches(filter, set, credentials).await
    }

    /// Assign values and return the entities that changed, for `--collect`.
    pub async fn update_entity_filter_returning(
        &self,
        filter: &EntityFilter,
        set: &str,
        credentials: Option<Credentials>,
    ) -> Result<Entities, Error> {
        self.update_matches_returning(filter, set, credentials)
            .await
    }

    /// Delete the entities a parsed native filter matches and return the deleted
    /// rows, for `--collect`.
    pub async fn delete_entity_filter_returning(
        &self,
        filter: &EntityFilter,
    ) -> Result<Entities, Error> {
        self.delete_matches_returning(filter).await
    }

    /// Run one count statement.
    async fn scalar_count(&self, statement: SelectStatement) -> Result<u64, Error> {
        self.backend.count(statement).await
    }

    /// Write a bulk load's batches in one transaction, reading as it writes.
    ///
    /// Batches arrive from a reader that walks its source so a load of any size holds
    /// one batch rather than the whole file, matching the Python command. Nothing lands
    /// unless the whole load succeeds so a collision under `Conflict::Error`, or a row
    /// the reader refuses, leaves the table exactly as it was. Answers how many rows were
    /// written.
    pub async fn load_records(
        &self,
        batches: impl Iterator<Item = Result<Records, String>> + Send,
        conflict: Conflict,
    ) -> Result<usize, Error> {
        let dialect = self.dialect();
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
                crate::records::table_of(&batch).column_names(),
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
        batches: impl Iterator<Item = Result<Entities, String>> + Send,
        conflict: Conflict,
    ) -> Result<usize, Error> {
        let dialect = self.dialect();
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

    /// Execute a load's batches in one transaction, committing only when all of them
    /// land.
    ///
    /// The batches are pulled one at a time so the reader behind them walks its source
    /// as the writes go out rather than collecting it first. A batch of `None` is a row
    /// the reader refused, which rolls everything back by returning before the commit and
    /// reports which row it was.
    async fn write_batches(
        &self,
        mut batches: impl Iterator<Item = Result<(sea_query::InsertStatement, usize), String>> + Send,
    ) -> Result<usize, Error> {
        // A load takes the whole write lock. Its batches are one caller's own rows going
        // into tables nobody else is touching so overlapping buys nothing and a conflict
        // at commit would mean re-reading the source.
        self.backend
            .insert_all(Writing::Default, &mut batches)
            .await
    }

    /// Read the columns an authentication gate needs for one user, `None` when no user
    /// carries the ID.
    ///
    /// The gate needs only standing, whether the account is an administrator and
    /// whether it is disabled so a record request never crosses into Python just to
    /// admit its caller.
    pub async fn gate_user(&self, id: uuid::Uuid) -> Result<Option<GateUser>, Error> {
        self.backend.gate_user(id).await
    }

    /// Execute a compiled record query, decoding its rows for the given table.
    ///
    /// The statement text and parameters come from the Python query layer's own compiler
    /// so any filter it can express runs natively with identical semantics. Only `SELECT`
    /// statements are accepted.
    pub async fn fetch_sql(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Records, Error> {
        assert_readonly(sql)?;
        self.backend.query_records(table, sql, parameters).await
    }

    /// Execute a compiled record query, decoding its rows a chunk at a time.
    ///
    /// The chunked twin of [`fetch_sql`](Self::fetch_sql) so a dump of a table of any
    /// size renders and writes as it reads rather than holding the whole result.
    pub async fn stream_sql(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: &mut (impl FnMut(Records) -> Result<(), Error> + Send),
    ) -> Result<(), Error> {
        assert_readonly(sql)?;
        self.backend
            .stream_query_records(table, sql, parameters, sink)
            .await
    }

    /// Execute a statement that returns rows, decoding them by column.
    ///
    /// The query layer compiles its own statement and then reads whatever it selected
    /// so this decodes by column rather than into a table's struct. Values arrive in the
    /// form their column declares, which lets one caller read the same row the
    /// same way on every backend.
    pub async fn fetch_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<Vec<crate::dynamic::Row>, Error> {
        self.backend.query_rows(table, sql, parameters).await
    }

    /// The chunked twin of [`fetch_dynamic`](Self::fetch_dynamic).
    ///
    /// Rows reach the caller as they arrive so a query over a large table costs one
    /// chunk of memory rather than the whole result.
    pub async fn stream_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Parameter>,
        sink: &mut (impl FnMut(Vec<crate::dynamic::Row>) -> Result<(), Error> + Send),
    ) -> Result<(), Error> {
        self.backend.stream_rows(table, sql, parameters, sink).await
    }

    /// Execute a statement that returns no rows and report how many it touched.
    pub async fn execute_dynamic(
        &self,
        sql: &str,
        parameters: Vec<Parameter>,
    ) -> Result<u64, Error> {
        self.backend.execute(sql, parameters).await
    }

    /// Run a script of `;`-separated statements.
    ///
    /// `raw_sql` sends the whole script so the driver separates the statements rather
    /// than this guessing where one ends. Migrations rely on that because a `PRAGMA`
    /// the SQLite family needs before rebuilding a table does nothing inside a
    /// transaction.
    pub async fn execute_script(&self, sql: &str) -> Result<(), Error> {
        self.backend.execute_script(sql).await
    }
}

/// The storage dispatch a filter's table kind carries.
///
/// [`Tabled`] is what the compiler needs from a table. This adds what the store needs,
/// which backend call decodes a result set of the table's kind, and the rules the table
/// imposes on written values before a statement is built from them.
#[async_trait::async_trait]
pub(crate) trait Stored: Tabled {
    /// Stream the statement's rows to `sink` as decoded batches of this kind.
    async fn stream(
        backend: &dyn DatabaseBackend,
        table: Self,
        statement: SelectStatement,
        sink: Sink<'_, Self::Batch>,
    ) -> Result<(), Error>;

    /// Run a returning write in its own transaction, decoding the rows it touched.
    async fn write_returning(
        backend: &dyn DatabaseBackend,
        table: Self,
        statement: Write,
    ) -> Result<Self::Batch, Error>;

    /// Apply the rules this table imposes on values about to be written.
    fn prepare(
        table: Self,
        values: &mut serde_json::Map<String, serde_json::Value>,
        credentials: Option<Credentials>,
    ) -> Result<(), Error>;
}

#[async_trait::async_trait]
impl Stored for RecordTable {
    async fn stream(
        backend: &dyn DatabaseBackend,
        table: Self,
        statement: SelectStatement,
        sink: Sink<'_, Records>,
    ) -> Result<(), Error> {
        backend.stream_records(table, statement, sink).await
    }

    async fn write_returning(
        backend: &dyn DatabaseBackend,
        table: Self,
        statement: Write,
    ) -> Result<Records, Error> {
        backend.write_records(table, statement).await
    }

    fn prepare(
        _table: Self,
        _values: &mut serde_json::Map<String, serde_json::Value>,
        _credentials: Option<Credentials>,
    ) -> Result<(), Error> {
        Ok(())
    }
}

#[async_trait::async_trait]
impl Stored for EntityTable {
    async fn stream(
        backend: &dyn DatabaseBackend,
        table: Self,
        statement: SelectStatement,
        sink: Sink<'_, Entities>,
    ) -> Result<(), Error> {
        backend.stream_entities(table, statement, sink).await
    }

    async fn write_returning(
        backend: &dyn DatabaseBackend,
        table: Self,
        statement: Write,
    ) -> Result<Entities, Error> {
        backend.write_entities(table, statement).await
    }

    /// A user's password hashes and their email address normalizes on the way in, the
    /// same rules a create follows so a row written here is one the model would have
    /// written.
    fn prepare(
        table: Self,
        values: &mut serde_json::Map<String, serde_json::Value>,
        credentials: Option<Credentials>,
    ) -> Result<(), Error> {
        if table != EntityTable::Users {
            return Ok(());
        }

        let Some(credentials) = credentials else {
            return Err(Error::Refused(
                "This database hashes passwords in a way this command cannot reproduce, \
                 so it will not write a user."
                    .to_string(),
            ));
        };

        credentials
            .apply(table, values)
            .map_err(|reason| Error::Refused(format!("{reason} It will not be written.")))
    }
}

/// Refuse anything but a read, for the paths that only ever run one.
fn assert_readonly(sql: &str) -> Result<(), Error> {
    let head = sql.trim_start();
    if starts_with_keyword(head, "select") || starts_with_keyword(head, "with") {
        return Ok(());
    }

    Err(Error::Decode("only SELECT statements execute here".into()))
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

pub use crate::backend::CHUNK;

/// Check a case-insensitive keyword prefix.
fn starts_with_keyword(text: &str, keyword: &str) -> bool {
    text.get(..keyword.len())
        .is_some_and(|prefix| prefix.eq_ignore_ascii_case(keyword))
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

        RecordStore::sqlite_writable(path, Vec::new(), Vec::new(), Vec::new()).unwrap()
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
    async fn a_writable_store_creates_the_directories_leading_to_its_file() {
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("nested").join("records.sqlite");
        let store = RecordStore::sqlite_writable(
            path.to_str().expect("the path is text"),
            Vec::new(),
            Vec::new(),
            Vec::new(),
        )
        .expect("the store opens");

        // Nothing has created the schema so the table is missing rather than the file.
        assert!(store.fetch(RecordTable::Logs, None, None).await.is_err());
        assert!(path.exists(), "opening the database created its file");
    }

    #[tokio::test]
    async fn a_read_only_store_creates_nothing() {
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("nested").join("records.sqlite");
        let store = RecordStore::sqlite(
            path.to_str().expect("the path is text"),
            Vec::new(),
            Vec::new(),
        )
        .expect("the store opens");

        assert!(store.fetch(RecordTable::Logs, None, None).await.is_err());
        assert!(
            !path.parent().expect("the path has a parent").exists(),
            "a read-only open left the filesystem alone"
        );
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
        // SQLite's affinity keywords so it takes NUMERIC affinity and converts a
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

        // The affinity really does split the rows across storage classes, which makes
        // reading them all as text wrong.
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

        let store = RecordStore::sqlite(path, Vec::new(), Vec::new()).unwrap();
        let filter = EntityFilter::parse(EntityTable::Variables, &[]).expect("an empty filter");
        let mut variables = Vec::new();
        store
            .stream_entity_filter(&filter, &mut |entities| {
                let Entities::Variables(chunk) = entities else {
                    panic!("expected variables");
                };
                variables.extend(chunk);
                Ok(())
            })
            .await
            .expect("the listing reads");

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

    #[test]
    fn readonly_check_reads_keywords_and_survives_multibyte_text() {
        assert!(assert_readonly("SELECT 1").is_ok());
        assert!(assert_readonly("  with x as (select 1) select * from x").is_ok());
        assert!(assert_readonly("DELETE FROM logs").is_err());

        // A keyword-length prefix that splits a multibyte character is a refusal, not a
        // panic.
        assert!(assert_readonly("aéé").is_err());
    }
}
