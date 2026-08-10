//! The Turso backend.
//!
//! Turso reads and writes the SQLite file format through its own engine so this backend
//! executes the same statements and stored value forms the SQLite dialect does while
//! connecting through the `turso` crate rather than sqlx. The engine opens lazily on
//! first use, and every connection runs the same commands the query layer runs on its
//! own so both sides of the file see identical semantics.
//!
//! This backend must be the only Turso engine in its process touching the file. The
//! engine coordinates concurrent handles through in-process state and guards the file
//! with an fcntl lock, and fcntl locks never conflict within one process so a second
//! copy of the engine (a Python driver's, for instance) opens the same file silently and
//! the two copies overwrite each other's WAL frames. That is why the Python layer keeps
//! its own driver for Turso databases and never constructs this backend beside it.

use ceres_entities::{Entities, Records, Timestamp};
use chrono::NaiveDateTime;
use tokio::sync::OnceCell;
use turso::Value;
use uuid::Uuid;

use crate::backend::Writing;
use crate::entities::EntityTable;
use crate::records::{FieldRead, FromRow, RecordTable, json_text};
use crate::store::{Error, Parameter};

/// A lazily-opened Turso engine over one database file.
///
/// Reads and writes each connect fresh because the per-connection commands are cheap on
/// an in-process engine and a shared connection would interleave concurrent statements.
pub(crate) struct TursoBackend {
    path: String,
    mvcc: bool,
    on_init: Vec<String>,
    on_connect: Vec<String>,
    on_close: Vec<String>,
    database: OnceCell<turso::Database>,
    started: OnceCell<()>,
}

impl TursoBackend {
    pub(crate) fn new(
        path: &str,
        mvcc: bool,
        on_init: Vec<String>,
        on_connect: Vec<String>,
        on_close: Vec<String>,
    ) -> Self {
        Self {
            path: path.to_string(),
            mvcc,
            on_init,
            on_connect,
            on_close,
            database: OnceCell::new(),
            started: OnceCell::new(),
        }
    }

    /// Open a connection, matching the query layer's per-connection commands.
    async fn connection(&self) -> Result<turso::Connection, Error> {
        let database = self
            .database
            .get_or_try_init(|| async {
                // A missing file is created, along with the directories leading to it,
                // because this is what runs a database's migrations and a database has no
                // file before its first one. Callers that mean to read an existing
                // database check for it themselves.
                crate::store::create_parent_directories(&self.path)?;
                turso::Builder::new_local(&self.path)
                    .build()
                    .await
                    .map_err(Error::from)
            })
            .await?;

        // The same commands the query layer runs on its own connections, minus
        // `auto_vacuum`, which Turso rejects. A pragma only takes effect once its result
        // rows are read so they run through the draining helper.
        let connection = database.connect()?;

        // The `init` statements belong to the database rather than to a connection, so
        // they run on whichever one opens first and on no other. A failure leaves them
        // un-run so the next connection tries again rather than the database going
        // without them.
        self.started
            .get_or_try_init(|| async {
                for statement in &self.on_init {
                    pragma(&connection, statement).await?;
                }

                Ok::<(), Error>(())
            })
            .await?;

        pragma(&connection, "PRAGMA busy_timeout = 30000").await?;
        pragma(&connection, "PRAGMA foreign_keys = ON").await?;
        if self.mvcc {
            let mode = pragma(&connection, "PRAGMA journal_mode = 'mvcc'").await?;
            let reported = match &mode {
                Some(Value::Text(text)) => text.to_lowercase(),
                _ => String::new(),
            };

            if reported != "mvcc" {
                return Err(Error::Connect(format!(
                    "Turso would not enable MVCC, 'PRAGMA journal_mode' reported {}",
                    match mode {
                        Some(value) => format!("{value:?}"),
                        None => "nothing".to_string(),
                    }
                )));
            }
        }

        // The configuration's own statements come last so one of them can override what
        // this set, which is the point of being able to configure them.
        for statement in &self.on_connect {
            pragma(&connection, statement).await?;
        }

        Ok(connection)
    }

    /// Run one operation on a connection of its own, from open through close.
    ///
    /// A connection here lives for exactly one operation so this is the release point a
    /// pooling backend gets from handing a connection back, and where the configuration's
    /// `close` statements belong. They run whether the operation succeeded or failed, and
    /// after any transaction it opened has settled, which a statement like
    /// `PRAGMA incremental_vacuum` needs to do anything at all.
    async fn using<T>(
        &self,
        work: impl AsyncFnOnce(&turso::Connection) -> Result<T, Error>,
    ) -> Result<T, Error> {
        let connection = self.connection().await?;
        let outcome = work(&connection).await;

        // A failing close statement is only worth reporting when the operation itself
        // succeeded because the caller is waiting on that error, not this one.
        let closed = self.close(&connection).await;
        match outcome {
            Ok(held) => closed.map(|()| held),
            Err(error) => Err(error),
        }
    }

    /// Whether this engine was configured for MVCC journaling.
    ///
    /// MVCC is what lets two write transactions overlap. Without it the engine admits one
    /// writer at a time, the same as SQLite, and `BEGIN CONCURRENT` is refused outright.
    pub(crate) fn mvcc(&self) -> bool {
        self.mvcc
    }

    /// Open a transaction on `connection`, in the form `writing` asks for.
    ///
    /// `BEGIN CONCURRENT` is what allows overlapping writers, and the engine accepts it
    /// only under MVCC journaling so a concurrent transaction asked of a database
    /// without it opens plainly rather than failing. It is also refused around schema
    /// changes, which is why a migration never asks for one.
    async fn begin(&self, connection: &turso::Connection, writing: Writing) -> Result<(), Error> {
        let statement = match writing {
            Writing::Concurrent if self.mvcc => "BEGIN CONCURRENT",
            Writing::Concurrent | Writing::Default => "BEGIN",
        };
        connection.execute(statement, ()).await?;
        Ok(())
    }

    /// Run the configuration's `close` statements on a connection being let go.
    async fn close(&self, connection: &turso::Connection) -> Result<(), Error> {
        for statement in &self.on_close {
            pragma(connection, statement).await?;
        }

        Ok(())
    }

    /// Execute a query and decode its rows for the given record table.
    pub(crate) async fn query(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Records, Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;
            decode(table, &mut rows, usize::MAX).await
        })
        .await
    }

    /// Walk a result set, handing over one chunk of records at a time.
    pub(crate) async fn stream(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Value>,
        sink: &mut (impl FnMut(Records) -> Result<(), Error> + ?Sized),
    ) -> Result<(), Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;

            // A batch shorter than the chunk means the cursor is spent, and an empty
            // result still goes over once so a CSV dump writes its header row.
            loop {
                let records = decode(table, &mut rows, crate::store::CHUNK).await?;
                let complete = records.len() == crate::store::CHUNK;
                sink(records)?;
                if !complete {
                    return Ok(());
                }
            }
        })
        .await
    }

    /// Read a gate user row, `None` when no user carries the ID.
    pub(crate) async fn gate_user(
        &self,
        sql: &str,
        id: uuid::Uuid,
    ) -> Result<Option<crate::store::GateUser>, Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter([Value::Text(id.to_string())]))
                .await?;
            let Some(row) = rows.next().await? else {
                return Ok(None);
            };

            let flag = |value: Value| match value {
                Value::Integer(value) => Ok(value != 0),
                other => Err(Error::Decode(format!("{other:?} is not a flag"))),
            };
            Ok(Some(crate::store::GateUser {
                id,
                admin: flag(row.get_value(0)?)?,
                disabled: flag(row.get_value(1)?)?,
            }))
        })
        .await
    }

    /// Execute a single-value count query.
    pub(crate) async fn scalar_count(
        &self,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<u64, Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;
            let Some(row) = rows.next().await? else {
                return Ok(0);
            };

            match row.get_value(0)? {
                Value::Integer(count) => Ok(count.max(0) as u64),
                other => Err(Error::Decode(format!("{other:?} is not a count"))),
            }
        })
        .await
    }

    /// Walk an entity result set, handing over one chunk at a time.
    pub(crate) async fn stream_entities(
        &self,
        table: EntityTable,
        sql: &str,
        parameters: Vec<Value>,
        sink: &mut (impl FnMut(Entities) -> Result<(), Error> + ?Sized),
    ) -> Result<(), Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;

            loop {
                let entities = decode_entities(table, &mut rows, crate::store::CHUNK).await?;
                let complete = entities.len() == crate::store::CHUNK;
                sink(entities)?;
                if !complete {
                    return Ok(());
                }
            }
        })
        .await
    }

    /// Execute a statement that returns rows, decoding them by column.
    pub(crate) async fn query_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Vec<crate::dynamic::Row>, Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;
            let names = rows.column_names();

            let mut decoded = Vec::new();
            while let Some(row) = rows.next().await? {
                decoded.push(crate::dynamic::turso_row(&row, &names, table)?);
            }

            Ok(decoded)
        })
        .await
    }

    /// The chunked twin of `query_dynamic`, handing rows over as they are read.
    pub(crate) async fn stream_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Value>,
        sink: &mut (impl FnMut(Vec<crate::dynamic::Row>) -> Result<(), Error> + ?Sized),
    ) -> Result<(), Error> {
        self.using(async |connection| {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;
            let names = rows.column_names();

            let mut chunk = Vec::with_capacity(crate::store::CHUNK);
            while let Some(row) = rows.next().await? {
                chunk.push(crate::dynamic::turso_row(&row, &names, table)?);
                if chunk.len() >= crate::store::CHUNK {
                    sink(std::mem::take(&mut chunk))?;
                    chunk.reserve(crate::store::CHUNK);
                }
            }

            // The trailing rows go over even when they do not fill a chunk.
            if !chunk.is_empty() {
                sink(chunk)?;
            }

            Ok(())
        })
        .await
    }

    /// Run a script of `;`-separated statements in one transaction.
    ///
    /// Turso's own `execute_batch` opens a transaction of its own, which would commit
    /// part way through a migration and leave a failure half applied so the statements
    /// run one at a time inside the transaction opened here. The scripts are the
    /// project's own DDL files, which carry no statement holding a bare semicolon.
    pub(crate) async fn execute_script(&self, sql: &str) -> Result<(), Error> {
        self.using(async |connection| {
            // Plainly, never concurrently. A script is how a migration runs, and the
            // engine refuses a schema change inside a concurrent transaction.
            self.begin(connection, Writing::Default).await?;
            let ran: Result<(), Error> = async {
                for statement in sql.split(';') {
                    if statement.trim().is_empty() {
                        continue;
                    }

                    connection.execute(statement, ()).await?;
                }

                Ok(())
            }
            .await;
            self.settle(connection, ran).await
        })
        .await
    }

    /// Execute one write in its own transaction, returning how many rows changed.
    pub(crate) async fn execute_write(
        &self,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<u64, Error> {
        self.using(async |connection| {
            self.begin(connection, Writing::Default).await?;
            let affected = connection
                .execute(sql, turso::params_from_iter(parameters))
                .await
                .map_err(Error::from);
            self.settle(connection, affected).await
        })
        .await
    }

    /// Execute one write that returns its rows, in its own transaction.
    ///
    /// `RETURNING` is SQLite's, which this engine implements, so a write says what it
    /// touched without a second query racing it.
    pub(crate) async fn query_write(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Records, Error> {
        self.using(async |connection| {
            self.begin(connection, Writing::Default).await?;
            let decoded = async {
                let mut rows = connection
                    .query(sql, turso::params_from_iter(parameters))
                    .await?;
                decode(table, &mut rows, usize::MAX).await
            }
            .await;
            self.settle(connection, decoded).await
        })
        .await
    }

    /// The entity form of [`Self::query_write`].
    pub(crate) async fn query_write_entities(
        &self,
        table: EntityTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Entities, Error> {
        self.using(async |connection| {
            self.begin(connection, Writing::Default).await?;
            let decoded = async {
                let mut rows = connection
                    .query(sql, turso::params_from_iter(parameters))
                    .await?;
                decode_entities(table, &mut rows, usize::MAX).await
            }
            .await;
            self.settle(connection, decoded).await
        })
        .await
    }

    /// Commit what a write produced, or roll back what it failed at.
    async fn settle<T>(
        &self,
        connection: &turso::Connection,
        outcome: Result<T, Error>,
    ) -> Result<T, Error> {
        let held = match outcome {
            Ok(held) => held,
            Err(error) => {
                let _ = connection.execute("ROLLBACK", ()).await;
                return Err(error);
            }
        };

        if let Err(error) = connection.execute("COMMIT", ()).await {
            let _ = connection.execute("ROLLBACK", ()).await;
            return Err(error.into());
        }

        Ok(held)
    }

    /// Execute statements in one transaction, rolling back if any of them fails.
    ///
    /// `writing` decides whether the transaction may overlap other writers. A concurrent
    /// one that touched the same rows as another fails when it commits so the caller
    /// asking for it has to be willing to run these statements again.
    pub(crate) async fn execute_transaction(
        &self,
        writing: Writing,
        statements: Vec<(String, Vec<Value>)>,
    ) -> Result<(), Error> {
        self.using(async |connection| {
            self.begin(connection, writing).await?;
            let ran: Result<(), Error> = async {
                for (sql, parameters) in statements {
                    connection
                        .execute(&sql, turso::params_from_iter(parameters))
                        .await?;
                }

                Ok(())
            }
            .await;
            self.settle(connection, ran).await
        })
        .await
    }
}

/// Run a pragma, draining its rows so it takes effect, and return the first value.
async fn pragma(connection: &turso::Connection, sql: &str) -> Result<Option<Value>, Error> {
    let mut rows = connection.query(sql, ()).await?;
    let mut first = None;
    while let Some(row) = rows.next().await? {
        if first.is_none() && row.column_count() > 0 {
            first = Some(row.get_value(0)?);
        }
    }

    Ok(first)
}

/// A statement parameter in the SQLite dialect's stored value form.
pub(crate) fn parameter_value(parameter: Parameter) -> Value {
    match parameter {
        Parameter::Null => Value::Null,
        Parameter::Bool(value) => Value::Integer(i64::from(value)),
        Parameter::Integer(value) => Value::Integer(value),
        Parameter::Float(value) => Value::Real(value),
        Parameter::Text(value) => Value::Text(value),
        Parameter::Bytes(value) => Value::Blob(value),
        Parameter::Timestamp(value) => Value::Text(Parameter::timestamp_text(&value)),
        Parameter::Uuid(value) => Value::Text(value.to_string()),
        Parameter::Json(value) => Value::Text(value.to_string()),
    }
}

/// Convert a sea-query bound value into Turso's, for statements built in Rust.
///
/// The SQLite dialect pre-renders timestamps, UUIDs, and JSON payloads to text so only
/// primitive values reach this conversion.
pub(crate) fn sea_value(value: sea_query::Value) -> Result<Value, Error> {
    use sea_query::Value as Sea;

    fn from<T>(value: Option<T>, convert: impl Fn(T) -> Value) -> Value {
        value.map_or(Value::Null, convert)
    }

    Ok(match value {
        Sea::Bool(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::TinyInt(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::SmallInt(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::Int(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::BigInt(value) => from(value, Value::Integer),
        Sea::TinyUnsigned(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::SmallUnsigned(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::Unsigned(value) => from(value, |value| Value::Integer(i64::from(value))),
        Sea::BigUnsigned(Some(value)) => Value::Integer(
            i64::try_from(value)
                .map_err(|_| Error::Decode(format!("{value} overflows an integer column")))?,
        ),
        Sea::BigUnsigned(None) => Value::Null,
        Sea::Float(value) => from(value, |value| Value::Real(f64::from(value))),
        Sea::Double(value) => from(value, Value::Real),
        Sea::Char(value) => from(value, |value| Value::Text(value.to_string())),
        Sea::String(value) => from(value, |value| Value::Text(*value)),
        Sea::Bytes(value) => from(value, |value| Value::Blob(*value)),
        other => {
            return Err(Error::Decode(format!(
                "{other:?} is not a value the Turso backend binds"
            )));
        }
    })
}

/// Decode up to `limit` rows of a result set into natively-held records.
///
/// The cursor keeps its place so calling this again resumes where it stopped, and a
/// batch shorter than the limit means the result set is exhausted.
async fn decode(
    table: RecordTable,
    rows: &mut turso::Rows,
    limit: usize,
) -> Result<Records, Error> {
    let columns = Columns {
        names: rows.column_names(),
    };

    match table {
        RecordTable::Messages => collect(rows, &columns, limit).await.map(Records::Messages),
        RecordTable::Particles => collect(rows, &columns, limit).await.map(Records::Particles),
        RecordTable::Alerts => collect(rows, &columns, limit).await.map(Records::Alerts),
        RecordTable::Logs => collect(rows, &columns, limit)
            .await
            .map(Records::LogEntries),
    }
}

/// Decode up to `limit` rows for the given entity table.
async fn decode_entities(
    table: EntityTable,
    rows: &mut turso::Rows,
    limit: usize,
) -> Result<Entities, Error> {
    let columns = Columns {
        names: rows.column_names(),
    };

    match table {
        EntityTable::Users => collect(rows, &columns, limit).await.map(Entities::Users),
        EntityTable::Variables => collect(rows, &columns, limit)
            .await
            .map(Entities::Variables),
        EntityTable::Settings => collect(rows, &columns, limit).await.map(Entities::Settings),
        EntityTable::Workspaces => collect(rows, &columns, limit)
            .await
            .map(Entities::Workspaces),
        EntityTable::WorkspaceEdits => collect(rows, &columns, limit)
            .await
            .map(Entities::WorkspaceEdits),
        EntityTable::Groups => collect(rows, &columns, limit).await.map(Entities::Groups),
        EntityTable::GroupMemberships => collect(rows, &columns, limit)
            .await
            .map(Entities::GroupMemberships),
        EntityTable::UserPermissions => collect(rows, &columns, limit)
            .await
            .map(Entities::UserPermissions),
        EntityTable::GroupPermissions => collect(rows, &columns, limit)
            .await
            .map(Entities::GroupPermissions),
    }
}

/// Walk the cursor, decoding one entity per row until `limit` rows or exhaustion.
async fn collect<T: FromRow>(
    rows: &mut turso::Rows,
    columns: &Columns,
    limit: usize,
) -> Result<Vec<T>, Error> {
    let mut held = Vec::new();
    while held.len() < limit
        && let Some(row) = rows.next().await?
    {
        held.push(T::from_row(&Fields { row: &row, columns })?);
    }

    Ok(held)
}

/// The column names of a result set, resolving fields to positions.
///
/// The columns are read by name rather than by position because a `RETURNING *` and a
/// listing do not have to order them the same way. A lookup scans the handful of names
/// a table carries, once per field per row.
struct Columns {
    names: Vec<String>,
}

impl Columns {
    fn index(&self, name: &str) -> Result<usize, Error> {
        self.names
            .iter()
            .position(|column| column == name)
            .ok_or_else(|| Error::Decode(format!("no column named {name:?}")))
    }
}

/// One row of a result set with its column names, read by the shared field mappings.
struct Fields<'a> {
    row: &'a turso::Row,
    columns: &'a Columns,
}

impl Fields<'_> {
    fn value(&self, column: &str) -> Result<Value, Error> {
        Ok(self.row.get_value(self.columns.index(column)?)?)
    }
}

impl FieldRead for Fields<'_> {
    fn text(&self, column: &str) -> Result<String, Error> {
        match self.value(column)? {
            Value::Text(text) => Ok(text),
            other => Err(Error::Decode(format!("expected text, found {other:?}"))),
        }
    }

    fn optional_text(&self, column: &str) -> Result<Option<String>, Error> {
        match self.value(column)? {
            Value::Null => Ok(None),
            Value::Text(text) => Ok(Some(text)),
            other => Err(Error::Decode(format!("expected text, found {other:?}"))),
        }
    }

    /// Decode an ID column, stored as hyphenated UUID text.
    fn uuid(&self, column: &str) -> Result<Uuid, Error> {
        let held = self.text(column)?;
        held.parse()
            .map_err(|_| Error::Decode(format!("{held:?} is not a UUID")))
    }

    fn optional_uuid(&self, column: &str) -> Result<Option<Uuid>, Error> {
        self.optional_text(column)?
            .map(|held| {
                held.parse()
                    .map_err(|_| Error::Decode(format!("{held:?} is not a UUID")))
            })
            .transpose()
    }

    /// Decode a timestamp column, stored as naive UTC text.
    fn timestamp(&self, column: &str) -> Result<Timestamp, Error> {
        let text = self.text(column)?;
        let naive = NaiveDateTime::parse_from_str(&text, "%Y-%m-%d %H:%M:%S%.f")
            .map_err(|_| Error::Decode(format!("{text:?} is not a timestamp")))?;
        Ok(Timestamp(naive.and_utc()))
    }

    /// Decode a boolean column, which SQLite stores as an integer.
    fn boolean(&self, column: &str) -> Result<bool, Error> {
        match self.value(column)? {
            Value::Integer(held) => Ok(held != 0),
            other => Err(Error::Decode(format!(
                "expected a boolean, found {other:?}"
            ))),
        }
    }

    fn blob(&self, column: &str) -> Result<Vec<u8>, Error> {
        match self.value(column)? {
            Value::Blob(bytes) => Ok(bytes),
            other => Err(Error::Decode(format!("expected a blob, found {other:?}"))),
        }
    }

    /// Decode a JSON column in whatever storage class it landed in.
    fn json(&self, column: &str) -> Result<serde_json::Value, Error> {
        match self.value(column)? {
            Value::Null => Ok(serde_json::Value::Null),
            Value::Text(held) => serde_json::from_str(&held)
                .map_err(|error| Error::Decode(format!("{held:?} is not JSON. {error}"))),
            Value::Integer(held) => Ok(held.into()),
            Value::Real(held) => Ok(serde_json::Number::from_f64(held)
                .map(serde_json::Value::Number)
                .unwrap_or(serde_json::Value::Null)),
            other => Err(Error::Decode(format!("expected JSON, found {other:?}"))),
        }
    }

    /// Decode a JSON object column, stored as its text the way the query layer writes
    /// it.
    fn json_object(
        &self,
        column: &str,
    ) -> Result<serde_json::Map<String, serde_json::Value>, Error> {
        json_text(self.text(column)?)
    }

    /// Decode a JSON object column, naming what was expected when the value is not one.
    fn object(
        &self,
        column: &str,
        what: &str,
    ) -> Result<serde_json::Map<String, serde_json::Value>, Error> {
        match self.json(column)? {
            serde_json::Value::Object(held) => Ok(held),
            _ => Err(Error::Decode(format!("{what} is not an object"))),
        }
    }
}

#[cfg(test)]
mod tests {
    use ceres_entities::{Address, Level, LogEntry, Message, MessageDirection, Particle};
    use chrono::{TimeZone, Utc};
    use serde_json::json;

    use super::*;
    use crate::store::RecordStore;
    use crate::writer::RecordWriter;

    /// Create the record tables through the same engine copy the backend opens.
    async fn create_database(path: &str) {
        let database = turso::Builder::new_local(path).build().await.unwrap();
        let connection = database.connect().unwrap();
        for sql in [
            "CREATE TABLE messages (id TEXT PRIMARY KEY, address TEXT, timestamp TEXT, \
             connection TEXT, direction TEXT, data BLOB)",
            "CREATE TABLE particles (id TEXT PRIMARY KEY, address TEXT, timestamp TEXT, \
             type TEXT, data TEXT)",
            "CREATE TABLE logs (id TEXT PRIMARY KEY, address TEXT, timestamp TEXT, \
             level TEXT, content TEXT)",
        ] {
            connection.execute(sql, ()).await.unwrap();
        }
    }

    fn particle(micros: u32, kind: &str) -> Particle {
        Particle {
            id: Uuid::from_u128(u128::from(micros) + 1),
            address: Address::parse("@sensor.temp").unwrap(),
            timestamp: Timestamp(
                Utc.with_ymd_and_hms(2026, 7, 29, 1, 2, 3).unwrap()
                    + chrono::Duration::microseconds(i64::from(micros)),
            ),
            kind: kind.to_string(),
            data: json!({"a": 1, "b": [1.5]}).as_object().unwrap().clone(),
            span: None,
        }
    }

    async fn round_trip(mvcc: bool) {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("records.turso");
        let path = path.to_str().unwrap();
        create_database(path).await;

        // Timestamps with and without sub-second precision store different text forms.
        let first = particle(0, "sample");
        let second = particle(250_000, "status");
        let message = Message {
            id: Uuid::from_u128(9),
            address: Address::parse("@sensor.temp").unwrap(),
            timestamp: first.timestamp,
            connection: None,
            direction: MessageDirection::Receive,
            data: vec![0, 65, 255],
        };

        let writer = RecordWriter::turso(path, mvcc, Vec::new(), Vec::new());
        writer
            .upsert(vec![
                Records::Particles(vec![first.clone(), second.clone()]),
                Records::Messages(vec![message.clone()]),
            ])
            .await
            .unwrap();

        let store = RecordStore::turso(path, mvcc, Vec::new(), Vec::new(), Vec::new());
        let records = store
            .fetch(RecordTable::Particles, None, None)
            .await
            .unwrap();
        assert_eq!(records, Records::Particles(vec![first, second.clone()]));

        let records = store
            .fetch(RecordTable::Messages, None, None)
            .await
            .unwrap();
        assert_eq!(records, Records::Messages(vec![message]));

        // Compiled-style SQL binds timestamps in their stored text form.
        let records = store
            .fetch_sql(
                RecordTable::Particles,
                "SELECT * FROM particles WHERE timestamp > ? AND type = ?",
                vec![
                    Parameter::Timestamp(
                        second.timestamp.0.naive_utc() - chrono::Duration::seconds(1),
                    ),
                    Parameter::Text("status".to_string()),
                ],
            )
            .await
            .unwrap();
        assert_eq!(records, Records::Particles(vec![second]));

        // A rewrite under the same ID updates rather than duplicates.
        let entry = LogEntry {
            id: Uuid::from_u128(7),
            address: Address::parse("@sensor.temp").unwrap(),
            timestamp: Timestamp(Utc.with_ymd_and_hms(2026, 7, 29, 1, 2, 3).unwrap()),
            level: Level::Info,
            content: "first".to_string(),
        };
        let revised = LogEntry {
            content: "revised".to_string(),
            level: Level::Warning,
            ..entry.clone()
        };
        writer
            .upsert(vec![Records::LogEntries(vec![entry])])
            .await
            .unwrap();
        writer
            .upsert(vec![Records::LogEntries(vec![revised.clone()])])
            .await
            .unwrap();
        let records = store.fetch(RecordTable::Logs, None, None).await.unwrap();
        assert_eq!(records, Records::LogEntries(vec![revised]));
    }

    #[tokio::test]
    async fn records_round_trip_through_one_engine() {
        round_trip(false).await;
    }

    #[tokio::test]
    async fn records_round_trip_under_mvcc_journaling() {
        round_trip(true).await;
    }

    #[tokio::test]
    async fn a_missing_file_and_the_directories_leading_to_it_are_created() {
        // A database has no file before its first migration so opening one creates it,
        // along with the directories a configured path names.
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("nested").join("fresh.turso");
        let store = RecordStore::turso(
            path.to_str().expect("the path is text"),
            false,
            Vec::new(),
            Vec::new(),
            Vec::new(),
        );
        // Nothing has created the schema so the table is missing rather than the file.
        assert!(store.fetch(RecordTable::Logs, None, None).await.is_err());
        assert!(path.exists(), "opening the database created its file");

        // A directory the process cannot create is still a path pointing at nothing.
        let store = RecordStore::turso(
            "/nonexistent/records.turso",
            false,
            Vec::new(),
            Vec::new(),
            Vec::new(),
        );
        assert!(store.fetch(RecordTable::Logs, None, None).await.is_err());
    }

    /// A `close` statement runs at the end of every operation, whatever kind it was.
    ///
    /// The connection here lives for one operation so its close is the operation's end,
    /// and a statement that counts its own runs shows how many operations reached it.
    #[tokio::test]
    async fn a_close_statement_runs_at_the_end_of_every_operation() {
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("closed.turso");
        let path = path.to_str().expect("the path is text");

        // The counter is a table rather than a pragma, a pragma's effect not being
        // something a later query can read back.
        let store = RecordStore::turso(path, false, Vec::new(), Vec::new(), Vec::new());
        store
            .execute_script("CREATE TABLE closes (id INTEGER PRIMARY KEY AUTOINCREMENT)")
            .await
            .expect("the counter table is created");

        let counted = RecordStore::turso(
            path,
            false,
            Vec::new(),
            Vec::new(),
            vec!["INSERT INTO closes DEFAULT VALUES".to_string()],
        );
        // A read and a write because a write settles a transaction before its close.
        counted
            .execute_dynamic("CREATE TABLE probe (id INTEGER PRIMARY KEY)", Vec::new())
            .await
            .expect("the write runs");
        counted
            .fetch_dynamic(None, "SELECT * FROM probe", Vec::new())
            .await
            .expect("the read runs");

        let rows = store
            .fetch_dynamic(None, "SELECT COUNT(*) AS total FROM closes", Vec::new())
            .await
            .expect("the count is read");
        assert_eq!(
            rows.first()
                .and_then(|row| row.first())
                .map(|(_, cell)| cell),
            Some(&crate::dynamic::Cell::Integer(2)),
            "both operations ran the close statement"
        );
    }

    /// Only MVCC journaling reports that writers can overlap.
    ///
    /// This is what a caller reads to know whether a concurrent transaction can lose a
    /// race at commit so it has to follow the setting rather than the request.
    #[test]
    fn overlapping_writers_are_reported_only_under_mvcc() {
        use crate::backend::DatabaseBackend;

        let backend = |mvcc| TursoBackend::new("unused.turso", mvcc, vec![], vec![], vec![]);
        assert!(!backend(false).overlaps_writers());
        assert!(backend(true).overlaps_writers());
    }

    /// Two write transactions overlap on an MVCC database and both commit.
    ///
    /// This is the reason the backend exists. Each writer holds an open transaction while
    /// the other writes, which under a single-writer engine would block or fail, and both
    /// rows are there afterwards. `mvcc = false` is not asserted against because the two
    /// would simply serialize and still both land, which proves nothing either way.
    #[tokio::test]
    async fn concurrent_transactions_overlap_under_mvcc() {
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("concurrent.turso");
        let path = path.to_str().expect("the path is text");

        let store = RecordStore::turso(path, true, Vec::new(), Vec::new(), Vec::new());
        store
            .execute_script("CREATE TABLE probe (k TEXT PRIMARY KEY)")
            .await
            .expect("the table is created");
        assert!(store.overlaps_writers(), "MVCC allows overlapping writers");

        let backend = TursoBackend::new(path, true, vec![], vec![], vec![]);
        let first = backend.connection().await.expect("the first connects");
        let second = backend.connection().await.expect("the second connects");

        // Both transactions are open at once, which a single writer forbids.
        backend
            .begin(&first, Writing::Concurrent)
            .await
            .expect("the first transaction opens");
        backend
            .begin(&second, Writing::Concurrent)
            .await
            .expect("the second transaction opens");

        first
            .execute("INSERT INTO probe VALUES ('a')", ())
            .await
            .expect("the first writes");
        second
            .execute("INSERT INTO probe VALUES ('b')", ())
            .await
            .expect("the second writes while the first is still open");

        first
            .execute("COMMIT", ())
            .await
            .expect("the first commits");
        second
            .execute("COMMIT", ())
            .await
            .expect("the second commits");

        let rows = store
            .fetch_dynamic(None, "SELECT COUNT(*) AS total FROM probe", Vec::new())
            .await
            .expect("the count is read");
        assert_eq!(
            rows.first()
                .and_then(|row| row.first())
                .map(|(_, cell)| cell),
            Some(&crate::dynamic::Cell::Integer(2)),
            "both overlapping transactions landed"
        );
    }

    /// A plain transaction and a concurrent one still overlap under MVCC.
    ///
    /// This is the pair production actually runs. Only the record flush asks to be
    /// concurrent so every store write and every migration it overlaps with is opening
    /// plainly, and a plain transaction that blocked a concurrent one would leave the
    /// setting buying nothing where it matters.
    #[tokio::test]
    async fn a_plain_transaction_and_a_concurrent_one_overlap_under_mvcc() {
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("mixed.turso");
        let path = path.to_str().expect("the path is text");

        let store = RecordStore::turso(path, true, Vec::new(), Vec::new(), Vec::new());
        store
            .execute_script("CREATE TABLE probe (k TEXT PRIMARY KEY)")
            .await
            .expect("the table is created");

        let backend = TursoBackend::new(path, true, vec![], vec![], vec![]);
        let plain = backend.connection().await.expect("the plain one connects");
        let concurrent = backend
            .connection()
            .await
            .expect("the concurrent one connects");

        backend
            .begin(&plain, Writing::Default)
            .await
            .expect("the plain transaction opens");
        plain
            .execute("INSERT INTO probe VALUES ('plain')", ())
            .await
            .expect("the plain one writes");

        backend
            .begin(&concurrent, Writing::Concurrent)
            .await
            .expect("the concurrent transaction opens beside it");
        concurrent
            .execute("INSERT INTO probe VALUES ('concurrent')", ())
            .await
            .expect("the concurrent one writes while the plain one is still open");

        plain
            .execute("COMMIT", ())
            .await
            .expect("the plain commits");
        concurrent
            .execute("COMMIT", ())
            .await
            .expect("the concurrent commits");
    }

    /// Two concurrent transactions touching the same row settle at commit, not at write.
    ///
    /// This is the cost of asking to overlap, and the failure mode the record flush now
    /// has to survive. What matters to the layer above is that the loser fails at all and
    /// says something recognizable because a flush that fails is requeued and written
    /// again rather than lost.
    #[tokio::test]
    async fn a_concurrent_transaction_that_loses_a_race_fails() {
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("conflict.turso");
        let path = path.to_str().expect("the path is text");

        let store = RecordStore::turso(path, true, Vec::new(), Vec::new(), Vec::new());
        store
            .execute_script("CREATE TABLE probe (k TEXT PRIMARY KEY, v TEXT)")
            .await
            .expect("the table is created");

        let backend = TursoBackend::new(path, true, vec![], vec![], vec![]);
        let first = backend.connection().await.expect("the first connects");
        let second = backend.connection().await.expect("the second connects");

        backend
            .begin(&first, Writing::Concurrent)
            .await
            .expect("the first transaction opens");
        backend
            .begin(&second, Writing::Concurrent)
            .await
            .expect("the second transaction opens");

        // Both write the same key, which is the collision a concurrent transaction
        // defers rather than blocks on.
        first
            .execute("INSERT INTO probe VALUES ('same', 'first')", ())
            .await
            .expect("the first writes");
        let wrote = second
            .execute("INSERT INTO probe VALUES ('same', 'second')", ())
            .await;

        first
            .execute("COMMIT", ())
            .await
            .expect("the first commits");
        let committed = second.execute("COMMIT", ()).await;

        let refusal = match (&wrote, &committed) {
            (Err(error), _) => error.to_string(),
            (_, Err(error)) => error.to_string(),
            _ => panic!("one of the two colliding writers has to lose"),
        };

        // The wording is what the Python layer's error translation reads so it is pinned
        // here rather than left to whatever the engine calls it next release. This one
        // matches neither of that layer's constraint patterns so it crosses as a plain
        // value error, which is one of the failures a record flush requeues on. A release
        // that reworded this would still requeue, but `test_a_write_conflict_requeues`
        // in `tests/test_turso.py` is what says so from the other side.
        assert!(
            refusal.contains("Write-write conflict"),
            "the refusal names why it lost, got {refusal:?}"
        );

        // Whatever the engine calls it, the loser's rows are still the caller's to write
        // again, and the row that did land is the winner's.
        let rows = store
            .fetch_dynamic(None, "SELECT v FROM probe WHERE k = 'same'", Vec::new())
            .await
            .expect("the row is read");
        assert_eq!(rows.len(), 1, "exactly one of the two writes landed");
    }
}
