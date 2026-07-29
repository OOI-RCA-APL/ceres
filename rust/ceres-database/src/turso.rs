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

use ceres_entities::{Address, Alert, LogEntry, Message, Particle, Records, Timestamp};
use chrono::NaiveDateTime;
use tokio::sync::OnceCell;
use turso::Value;
use uuid::Uuid;

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
                // The file's lifecycle belongs to the Python layer, opening a missing
                // path would create an empty database beside the real one.
                if !std::path::Path::new(&self.path).exists() {
                    return Err(Error::Connect(format!("no database file at {}", self.path)));
                }

                turso::Builder::new_local(&self.path)
                    .build()
                    .await
                    .map_err(Error::from)
            })
            .await?;

        // The same commands the query layer runs on its own connections, minus
        // auto_vacuum, which Turso rejects. A pragma only takes effect once its result
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
        decode(table, &mut rows).await
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

/// Decode a result set into natively-held records.
async fn decode(table: RecordTable, rows: &mut turso::Rows) -> Result<Records, Error> {
    let columns = Columns {
        names: rows.column_names(),
    };

    match table {
        RecordTable::Messages => {
            let connection = columns.index("connection")?;
            let direction_column = columns.index("direction")?;
            let data = columns.index("data")?;
            let mut records = Vec::new();
            while let Some(row) = rows.next().await? {
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
            while let Some(row) = rows.next().await? {
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
            while let Some(row) = rows.next().await? {
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
            while let Some(row) = rows.next().await? {
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
    async fn missing_files_refuse_to_open() {
        let store = RecordStore::turso("/nonexistent/records.turso", false);
        let error = store
            .fetch(RecordTable::Logs, None, None)
            .await
            .unwrap_err();
        assert!(matches!(error, Error::Connect(_)));
    }
}
