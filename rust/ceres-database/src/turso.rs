//! The Turso backend.
//!
//! Turso reads and writes the SQLite file format through its own engine, so this backend
//! executes the same statements and stored value forms the SQLite dialect does while
//! connecting through the `turso` crate rather than sqlx. The engine opens lazily on
//! first use, and every connection runs the same commands the query layer runs on its
//! own, so both sides of the file see identical semantics.
//!
//! This backend must be the only Turso engine in its process touching the file. The
//! engine coordinates concurrent handles through in-process state and guards the file
//! with an fcntl lock, and fcntl locks never conflict within one process, so a second
//! copy of the engine (a Python driver's, for instance) opens the same file silently and
//! the two copies overwrite each other's WAL frames. That is why the Python layer keeps
//! its own driver for Turso databases and never constructs this backend beside it.

use ceres_entities::{
    Address, Alert, Entities, GrantLevel, Group, GroupMembership, GroupPermission, LogEntry,
    Message, Particle, PermissionTargetType, Records, Setting, Timestamp, User, UserPermission,
    Variable, Workspace, WorkspaceEdit,
};
use chrono::NaiveDateTime;
use tokio::sync::OnceCell;
use turso::Value;
use uuid::Uuid;

use crate::entities::EntityTable;
use crate::records::{RecordTable, direction, json_text, level};
use crate::store::{Error, Parameter};

/// A lazily-opened Turso engine over one database file.
///
/// Reads and writes each connect fresh, because the per-connection commands are cheap on
/// an in-process engine and a shared connection would interleave concurrent statements.
pub(crate) struct TursoBackend {
    path: String,
    mvcc: bool,
    database: OnceCell<turso::Database>,
}

impl TursoBackend {
    pub(crate) fn new(path: &str, mvcc: bool) -> Self {
        Self {
            path: path.to_string(),
            mvcc,
            database: OnceCell::new(),
        }
    }

    /// Open a connection, matching the query layer's per-connection commands.
    async fn connection(&self) -> Result<turso::Connection, Error> {
        let database = self
            .database
            .get_or_try_init(|| async {
                // A missing file is created, because this is what runs a database's
                // migrations and a database has no file before its first one. Callers that
                // mean to read an existing database check for it themselves and say so, an
                // empty database being a worse answer than a refusal for anyone who pointed
                // at the wrong path.
                turso::Builder::new_local(&self.path)
                    .build()
                    .await
                    .map_err(Error::from)
            })
            .await?;

        // The same commands the query layer runs on its own connections, minus
        // `auto_vacuum`, which Turso rejects. A pragma only takes effect once its result
        // rows are read, so they run through the draining helper.
        let connection = database.connect()?;
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

        Ok(connection)
    }

    /// Execute a query and decode its rows for the given record table.
    pub(crate) async fn query(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Records, Error> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(sql, turso::params_from_iter(parameters))
            .await?;
        decode(table, &mut rows, usize::MAX).await
    }

    /// Walk a result set, handing over one chunk of records at a time.
    pub(crate) async fn stream(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Value>,
        sink: &mut impl FnMut(Records) -> Result<(), Error>,
    ) -> Result<(), Error> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(sql, turso::params_from_iter(parameters))
            .await?;

        // A batch shorter than the chunk means the cursor is spent, and an empty result
        // still goes over once so a CSV dump writes its header row.
        loop {
            let records = decode(table, &mut rows, crate::store::CHUNK).await?;
            let complete = records.len() == crate::store::CHUNK;
            sink(records)?;
            if !complete {
                return Ok(());
            }
        }
    }

    /// Read a gate user row, `None` when no user carries the ID.
    pub(crate) async fn gate_user(
        &self,
        sql: &str,
        id: uuid::Uuid,
    ) -> Result<Option<crate::store::GateUser>, Error> {
        let connection = self.connection().await?;
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
    }

    /// Execute a single-value count query.
    pub(crate) async fn scalar_count(
        &self,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<u64, Error> {
        let connection = self.connection().await?;
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
    }

    /// Execute a query and decode its rows for the given entity table.
    pub(crate) async fn query_entities(
        &self,
        table: EntityTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Entities, Error> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(sql, turso::params_from_iter(parameters))
            .await?;
        decode_entities(table, &mut rows, usize::MAX).await
    }

    /// Walk an entity result set, handing over one chunk at a time.
    pub(crate) async fn stream_entities(
        &self,
        table: EntityTable,
        sql: &str,
        parameters: Vec<Value>,
        sink: &mut impl FnMut(Entities) -> Result<(), Error>,
    ) -> Result<(), Error> {
        let connection = self.connection().await?;
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
    }

    /// Execute a statement that returns rows, decoding them by column.
    pub(crate) async fn query_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Vec<crate::dynamic::Row>, Error> {
        let connection = self.connection().await?;
        let mut rows = connection
            .query(sql, turso::params_from_iter(parameters))
            .await?;
        let names = rows.column_names();

        let mut decoded = Vec::new();
        while let Some(row) = rows.next().await? {
            decoded.push(crate::dynamic::turso_row(&row, &names, table)?);
        }

        Ok(decoded)
    }

    /// The chunked twin of `query_dynamic`, handing rows over as they are read.
    pub(crate) async fn stream_dynamic(
        &self,
        table: Option<crate::dynamic::Table>,
        sql: &str,
        parameters: Vec<Value>,
        sink: &mut impl FnMut(Vec<crate::dynamic::Row>) -> Result<(), Error>,
    ) -> Result<(), Error> {
        let connection = self.connection().await?;
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
    }

    /// Execute a statement that returns no rows, answering how many it touched.
    pub(crate) async fn execute_dynamic(
        &self,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<u64, Error> {
        self.execute_write(sql, parameters).await
    }

    /// Run a script of `;`-separated statements in one transaction.
    ///
    /// Turso's own `execute_batch` opens a transaction of its own, which would commit
    /// part way through a migration and leave a failure half applied, so the statements
    /// run one at a time inside the transaction opened here. The scripts are the
    /// project's own DDL files, which carry no statement holding a bare semicolon.
    pub(crate) async fn execute_script(&self, sql: &str) -> Result<(), Error> {
        let connection = self.connection().await?;
        connection.execute("BEGIN", ()).await?;
        for statement in sql.split(';') {
            if statement.trim().is_empty() {
                continue;
            }

            if let Err(error) = connection.execute(statement, ()).await {
                let _ = connection.execute("ROLLBACK", ()).await;
                return Err(error.into());
            }
        }

        if let Err(error) = connection.execute("COMMIT", ()).await {
            let _ = connection.execute("ROLLBACK", ()).await;
            return Err(error.into());
        }

        Ok(())
    }

    /// Execute one write in its own transaction, answering how many rows changed.
    pub(crate) async fn execute_write(
        &self,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<u64, Error> {
        let connection = self.connection().await?;
        connection.execute("BEGIN", ()).await?;
        let affected = match connection
            .execute(sql, turso::params_from_iter(parameters))
            .await
        {
            Ok(affected) => affected,
            Err(error) => {
                let _ = connection.execute("ROLLBACK", ()).await;
                return Err(error.into());
            }
        };

        if let Err(error) = connection.execute("COMMIT", ()).await {
            let _ = connection.execute("ROLLBACK", ()).await;
            return Err(error.into());
        }

        Ok(affected)
    }

    /// Execute one write that hands its rows back, in its own transaction.
    ///
    /// `RETURNING` is SQLite's, which this engine implements, so a write says what it
    /// touched without a second query racing it.
    pub(crate) async fn query_write(
        &self,
        table: RecordTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Records, Error> {
        let connection = self.connection().await?;
        connection.execute("BEGIN", ()).await?;
        let decoded = async {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;
            decode(table, &mut rows, usize::MAX).await
        }
        .await;
        self.settle(&connection, decoded).await
    }

    /// The entity form of [`Self::query_write`].
    pub(crate) async fn query_write_entities(
        &self,
        table: EntityTable,
        sql: &str,
        parameters: Vec<Value>,
    ) -> Result<Entities, Error> {
        let connection = self.connection().await?;
        connection.execute("BEGIN", ()).await?;
        let decoded = async {
            let mut rows = connection
                .query(sql, turso::params_from_iter(parameters))
                .await?;
            decode_entities(table, &mut rows, usize::MAX).await
        }
        .await;
        self.settle(&connection, decoded).await
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
    pub(crate) async fn execute_transaction(
        &self,
        statements: Vec<(String, Vec<Value>)>,
    ) -> Result<(), Error> {
        let connection = self.connection().await?;
        connection.execute("BEGIN", ()).await?;
        for (sql, parameters) in statements {
            if let Err(error) = connection
                .execute(&sql, turso::params_from_iter(parameters))
                .await
            {
                let _ = connection.execute("ROLLBACK", ()).await;
                return Err(error.into());
            }
        }

        if let Err(error) = connection.execute("COMMIT", ()).await {
            let _ = connection.execute("ROLLBACK", ()).await;
            return Err(error.into());
        }

        Ok(())
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
/// The SQLite dialect pre-renders timestamps, UUIDs, and JSON payloads to text, so only
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
/// The cursor keeps its place, so calling this again resumes where it stopped, and a
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
        RecordTable::Messages => {
            let connection = columns.index("connection")?;
            let direction_column = columns.index("direction")?;
            let data = columns.index("data")?;
            let mut records = Vec::new();
            while records.len() < limit
                && let Some(row) = rows.next().await?
            {
                records.push(Message {
                    id: id(&row, &columns)?,
                    address: address(&row, &columns)?,
                    timestamp: timestamp(&row, &columns)?,
                    connection: optional_text(&row, connection)?,
                    direction: direction(text(&row, direction_column)?)?,
                    data: blob(&row, data)?,
                });
            }

            Ok(Records::Messages(records))
        }
        RecordTable::Particles => {
            let kind = columns.index("type")?;
            let data = columns.index("data")?;
            let mut records = Vec::new();
            while records.len() < limit
                && let Some(row) = rows.next().await?
            {
                records.push(Particle {
                    id: id(&row, &columns)?,
                    address: address(&row, &columns)?,
                    timestamp: timestamp(&row, &columns)?,
                    kind: text(&row, kind)?,
                    data: json_text(text(&row, data)?)?,
                    span: None,
                });
            }

            Ok(Records::Particles(records))
        }
        RecordTable::Alerts => {
            let level_column = columns.index("level")?;
            let kind = columns.index("type")?;
            let data = columns.index("data")?;
            let mut records = Vec::new();
            while records.len() < limit
                && let Some(row) = rows.next().await?
            {
                records.push(Alert {
                    id: id(&row, &columns)?,
                    address: address(&row, &columns)?,
                    timestamp: timestamp(&row, &columns)?,
                    level: level(text(&row, level_column)?)?,
                    kind: text(&row, kind)?,
                    data: json_text(text(&row, data)?)?,
                });
            }

            Ok(Records::Alerts(records))
        }
        RecordTable::Logs => {
            let level_column = columns.index("level")?;
            let content = columns.index("content")?;
            let mut records = Vec::new();
            while records.len() < limit
                && let Some(row) = rows.next().await?
            {
                records.push(LogEntry {
                    id: id(&row, &columns)?,
                    address: address(&row, &columns)?,
                    timestamp: timestamp(&row, &columns)?,
                    level: level(text(&row, level_column)?)?,
                    content: text(&row, content)?,
                });
            }

            Ok(Records::LogEntries(records))
        }
    }
}

/// The column names of a result set, resolving fields to positions.
/// Decode up to `limit` rows for the given entity table.
///
/// The columns are read by name rather than by position, because a `RETURNING *` and a
/// listing do not have to order them the same way.
async fn decode_entities(
    table: EntityTable,
    rows: &mut turso::Rows,
    limit: usize,
) -> Result<Entities, Error> {
    let columns = Columns {
        names: rows.column_names(),
    };

    match table {
        EntityTable::Users => {
            let username = columns.index("username")?;
            let email = columns.index("email")?;
            let password = columns.index("password")?;
            let admin = columns.index("admin")?;
            let disabled = columns.index("disabled")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(User {
                    id: id(&row, &columns)?,
                    username: text(&row, username)?,
                    email: text(&row, email)?,
                    password: text(&row, password)?,
                    admin: boolean(&row, admin)?,
                    disabled: boolean(&row, disabled)?,
                });
            }

            Ok(Entities::Users(entities))
        }
        EntityTable::Variables => {
            let name = columns.index("name")?;
            let value = columns.index("value")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(Variable {
                    address: address(&row, &columns)?,
                    name: text(&row, name)?,
                    value: json(&row, value)?,
                });
            }

            Ok(Entities::Variables(entities))
        }
        EntityTable::Settings => {
            let user = columns.index("user_id")?;
            let name = columns.index("name")?;
            let value = columns.index("value")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(Setting {
                    user_id: uuid(&row, user)?,
                    name: text(&row, name)?,
                    value: json(&row, value)?,
                });
            }

            Ok(Entities::Settings(entities))
        }
        EntityTable::Workspaces => {
            let name = columns.index("name")?;
            let scope = columns.index("scope")?;
            let owner = columns.index("owner_id")?;
            let shown = columns.index("show_when_logged_out")?;
            let data = columns.index("data")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                let held = json(&row, data)?;
                let serde_json::Value::Object(held) = held else {
                    return Err(Error::Decode(
                        "a workspace's data is not an object".to_string(),
                    ));
                };
                entities.push(Workspace {
                    id: id(&row, &columns)?,
                    name: text(&row, name)?,
                    // Addresses were validated when written, so the value is trusted on
                    // the way out the way a record's address is.
                    scope: Address::trusted(text(&row, scope)?),
                    owner_id: optional_text(&row, owner)?
                        .map(|held| {
                            held.parse()
                                .map_err(|_| Error::Decode(format!("{held:?} is not a UUID")))
                        })
                        .transpose()?,
                    show_when_logged_out: boolean(&row, shown)?,
                    data: held,
                });
            }

            Ok(Entities::Workspaces(entities))
        }
        EntityTable::WorkspaceEdits => {
            let user = columns.index("user_id")?;
            let workspace = columns.index("workspace_id")?;
            let data = columns.index("data")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(WorkspaceEdit {
                    user_id: uuid(&row, user)?,
                    workspace_id: uuid(&row, workspace)?,
                    data: object(&row, data, "a workspace edit's data")?,
                });
            }

            Ok(Entities::WorkspaceEdits(entities))
        }
        EntityTable::Groups => {
            let name = columns.index("name")?;
            let description = columns.index("description")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(Group {
                    id: id(&row, &columns)?,
                    name: text(&row, name)?,
                    description: text(&row, description)?,
                });
            }

            Ok(Entities::Groups(entities))
        }
        EntityTable::GroupMemberships => {
            let user = columns.index("user_id")?;
            let group = columns.index("group_id")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(GroupMembership {
                    user_id: uuid(&row, user)?,
                    group_id: uuid(&row, group)?,
                });
            }

            Ok(Entities::GroupMemberships(entities))
        }
        EntityTable::UserPermissions => {
            let user = columns.index("user_id")?;
            let kind = columns.index("target_type")?;
            let target = columns.index("target")?;
            let level = columns.index("level")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(UserPermission {
                    user_id: uuid(&row, user)?,
                    target_type: target_type(&row, kind)?,
                    target: text(&row, target)?,
                    level: access_level(&row, level)?,
                });
            }

            Ok(Entities::UserPermissions(entities))
        }
        EntityTable::GroupPermissions => {
            let group = columns.index("group_id")?;
            let kind = columns.index("target_type")?;
            let target = columns.index("target")?;
            let level = columns.index("level")?;
            let mut entities = Vec::new();
            while entities.len() < limit
                && let Some(row) = rows.next().await?
            {
                entities.push(GroupPermission {
                    group_id: uuid(&row, group)?,
                    target_type: target_type(&row, kind)?,
                    target: text(&row, target)?,
                    level: access_level(&row, level)?,
                });
            }

            Ok(Entities::GroupPermissions(entities))
        }
    }
}

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

fn id(row: &turso::Row, columns: &Columns) -> Result<Uuid, Error> {
    let text = text(row, columns.index("id")?)?;
    text.parse()
        .map_err(|_| Error::Decode(format!("{text:?} is not a UUID")))
}

fn address(row: &turso::Row, columns: &Columns) -> Result<Address, Error> {
    // Addresses were validated when written, the value is trusted on the way out.
    Ok(Address::trusted(text(row, columns.index("address")?)?))
}

/// Decode a timestamp column, stored as naive UTC text.
fn timestamp(row: &turso::Row, columns: &Columns) -> Result<Timestamp, Error> {
    let text = text(row, columns.index("timestamp")?)?;
    let naive = NaiveDateTime::parse_from_str(&text, "%Y-%m-%d %H:%M:%S%.f")
        .map_err(|_| Error::Decode(format!("{text:?} is not a timestamp")))?;
    Ok(Timestamp(naive.and_utc()))
}

fn text(row: &turso::Row, index: usize) -> Result<String, Error> {
    match row.get_value(index)? {
        Value::Text(text) => Ok(text),
        other => Err(Error::Decode(format!("expected text, found {other:?}"))),
    }
}

fn optional_text(row: &turso::Row, index: usize) -> Result<Option<String>, Error> {
    match row.get_value(index)? {
        Value::Null => Ok(None),
        Value::Text(text) => Ok(Some(text)),
        other => Err(Error::Decode(format!("expected text, found {other:?}"))),
    }
}

fn uuid(row: &turso::Row, index: usize) -> Result<Uuid, Error> {
    let held = text(row, index)?;
    held.parse()
        .map_err(|_| Error::Decode(format!("{held:?} is not a UUID")))
}

/// Decode a boolean column, which SQLite stores as an integer.
fn boolean(row: &turso::Row, index: usize) -> Result<bool, Error> {
    match row.get_value(index)? {
        Value::Integer(held) => Ok(held != 0),
        other => Err(Error::Decode(format!(
            "expected a boolean, found {other:?}"
        ))),
    }
}

/// Decode a JSON column, stored as its text the way the query layer writes it.
fn json(row: &turso::Row, index: usize) -> Result<serde_json::Value, Error> {
    match row.get_value(index)? {
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

/// Decode a JSON object column, naming what was expected when the value is not one.
fn object(
    row: &turso::Row,
    index: usize,
    what: &str,
) -> Result<serde_json::Map<String, serde_json::Value>, Error> {
    match json(row, index)? {
        serde_json::Value::Object(held) => Ok(held),
        _ => Err(Error::Decode(format!("{what} is not an object"))),
    }
}

/// Decode a permission's target type from the text the column stores.
fn target_type(row: &turso::Row, index: usize) -> Result<PermissionTargetType, Error> {
    let held = text(row, index)?;
    PermissionTargetType::parse(&held)
        .ok_or_else(|| Error::Decode(format!("{held:?} is not a permission target type")))
}

/// Decode a permission's access level from the text the column stores.
fn access_level(row: &turso::Row, index: usize) -> Result<GrantLevel, Error> {
    let held = text(row, index)?;
    GrantLevel::parse(&held)
        .ok_or_else(|| Error::Decode(format!("{held:?} is not an access level")))
}

fn blob(row: &turso::Row, index: usize) -> Result<Vec<u8>, Error> {
    match row.get_value(index)? {
        Value::Blob(bytes) => Ok(bytes),
        other => Err(Error::Decode(format!("expected a blob, found {other:?}"))),
    }
}

#[cfg(test)]
mod tests {
    use ceres_entities::{Level, LogEntry, Message, MessageDirection, Particle};
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

        let writer = RecordWriter::turso(path, mvcc);
        writer
            .upsert(vec![
                Records::Particles(vec![first.clone(), second.clone()]),
                Records::Messages(vec![message.clone()]),
            ])
            .await
            .unwrap();

        let store = RecordStore::turso(path, mvcc);
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
    async fn a_missing_file_is_created_but_a_missing_directory_is_not() {
        // A database has no file before its first migration, so opening one creates it.
        let directory = tempfile::tempdir().expect("the temporary directory is made");
        let path = directory.path().join("fresh.turso");
        let store = RecordStore::turso(path.to_str().expect("the path is text"), false);
        // Nothing has created the schema, so the table is missing rather than the file.
        assert!(store.fetch(RecordTable::Logs, None, None).await.is_err());
        assert!(path.exists(), "opening the database created its file");

        // A path whose directory does not exist is still someone pointing at nothing.
        let store = RecordStore::turso("/nonexistent/records.turso", false);
        assert!(store.fetch(RecordTable::Logs, None, None).await.is_err());
    }
}
