//! Native bulk record loads.
//!
//! A load reads a whole file of records, validates every row, and writes them in one
//! transaction. Both input shapes reduce to the same intermediate, a wire object per
//! row, which then deserializes into the record struct. That keeps the two readers to
//! the shape of their format and leaves one place deciding what a row means.
//!
//! Rows the native types cannot represent return `None`, which rolls the load back
//! before it starts and delegates, so Pydantic renders the validation error the way the
//! filter port established.

use ceres_entities::{
    Alert, Entities, FieldFamily, Group, GroupMembership, GroupPermission, LogEntry, Message,
    Particle, Records, Setting, Timestamp, User, UserPermission, Variable, Workspace,
    WorkspaceEdit,
};
use serde_json::{Map, Value};

use std::io::BufRead;

use crate::credentials::Credentials;
use crate::entities::EntityTable;
use crate::records::{RecordTable, Schema};

/// How a load resolves a primary key collision.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Conflict {
    /// Let the collision abort the transaction.
    Error,
    /// Leave the stored row alone.
    Ignore,
    /// Take every non-key column from the incoming row.
    Update,
}

impl Conflict {
    /// Select a conflict mode by its wire name.
    pub fn parse(name: &str) -> Option<Self> {
        match name {
            "error" => Some(Self::Error),
            "ignore" => Some(Self::Ignore),
            "update" => Some(Self::Update),
            _ => None,
        }
    }
}

/// The input shapes a load reads.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LoadFormat {
    /// One JSON object per line.
    Json,
    /// A header row naming the fields, then one row per record.
    Csv,
}

impl LoadFormat {
    /// Select a format by its wire name.
    pub fn parse(name: &str) -> Option<Self> {
        match name {
            "json" => Some(Self::Json),
            "csv" => Some(Self::Csv),
            _ => None,
        }
    }

    /// Infer a format from a file extension, the way the Python command does, `None`
    /// for an extension it names no format for.
    pub fn infer(extension: &str) -> Option<Self> {
        match extension {
            "json" | "jsonl" | "ndjson" | "txt" => Some(Self::Json),
            "csv" => Some(Self::Csv),
            _ => None,
        }
    }
}

/// How many rows one insert carries, matching the Python command's batch.
pub(crate) const BATCH: usize = 1000;

/// How a batch of wire objects becomes the rows it will write.
///
/// `Send` because a load hands these batches to a backend, whose transaction runs on the
/// executor's threads rather than the caller's.
type Convert<T> = Box<dyn Fn(&[Map<String, Value>]) -> Option<T> + Send>;

/// Walk an input's rows, decoding one batch at a time.
///
/// A load of any size holds one batch rather than the whole file, matching the Python
/// command, which reads its source lazily and flushes every `BATCH` rows inside a single
/// transaction. A refused item names the row that could not be read, which rolls the
/// whole load back and is reported as the command's own failure.
pub struct Batches<R, T> {
    rows: Rows<R>,
    convert: Convert<T>,
    /// Whether a refusal already ended the walk, past which there is nothing to read.
    spent: bool,
    /// How many rows have been handed over, which is what names the offending one.
    read: usize,
}

impl<R: BufRead, T> Iterator for Batches<R, T> {
    type Item = Result<T, String>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.spent {
            return None;
        }

        let start = self.read;
        let mut objects = Vec::with_capacity(BATCH);
        while objects.len() < BATCH {
            match self.rows.next() {
                None => break,
                Some(None) => {
                    self.spent = true;
                    return Some(Err(refused(start + objects.len() + 1)));
                }
                Some(Some(object)) => objects.push(object),
            }
        }

        if objects.is_empty() {
            return None;
        }

        self.read += objects.len();
        match (self.convert)(&objects) {
            Some(batch) => Some(Ok(batch)),
            None => {
                self.spent = true;
                // The batch says only that something in it was refused, so the rows are
                // walked again one at a time to name which. This runs on the failing
                // load alone, where the cost buys the reader the row number.
                let offending = objects
                    .iter()
                    .position(|object| (self.convert)(std::slice::from_ref(object)).is_none())
                    .map_or(start + 1, |index| start + index + 1);
                Some(Err(refused(offending)))
            }
        }
    }
}

/// What to say about a row that could not be read.
fn refused(row: usize) -> String {
    format!(
        "Row {row} could not be read. Nothing was loaded, because a load either lands \
         whole or not at all."
    )
}

/// Walk an input's rows in batches of records.
///
/// `None` when the source cannot be opened as the format claims, which for CSV means a
/// header row that will not read.
pub fn batches<R: BufRead>(
    table: RecordTable,
    source: R,
    format: LoadFormat,
) -> Option<Batches<R, Records>> {
    Some(Batches {
        rows: Rows::open(source, format)?,
        convert: Box::new(move |objects| records(table, objects)),
        spent: false,
        read: 0,
    })
}

/// Walk an entity input's rows in batches, like the record `batches`.
///
/// `credentials` carries the rules a user's own columns follow, so a row naming a
/// password or an email address is hashed and normalized as it is read. A row either
/// rule refuses ends the walk, which rolls the load back and delegates.
pub fn entity_batches<R: BufRead>(
    table: EntityTable,
    source: R,
    format: LoadFormat,
    credentials: Option<Credentials>,
) -> Option<Batches<R, Entities>> {
    Some(Batches {
        rows: Rows::open(source, format)?,
        convert: Box::new(move |objects| {
            entities(table, &credentialed(table, objects, credentials)?)
        }),
        spent: false,
        read: 0,
    })
}

/// Apply the credential rules to a batch of wire objects, `None` when one is refused.
fn credentialed(
    table: EntityTable,
    objects: &[Map<String, Value>],
    credentials: Option<Credentials>,
) -> Option<Vec<Map<String, Value>>> {
    let mut applied = objects.to_vec();
    if table == EntityTable::Users {
        // A user's columns cannot be written without the rules, so a caller that has
        // none refuses rather than storing a password as it arrived.
        let credentials = credentials?;
        for object in &mut applied {
            if !credentials.apply(table, object) {
                return None;
            }
        }
    }

    Some(applied)
}

/// One input's rows, read lazily in whichever shape the format names.
enum Rows<R> {
    /// One JSON object per line.
    Json(std::io::Lines<R>),
    /// A header row naming the fields, then one row of cells per record.
    Csv(Box<csv::StringRecordsIntoIter<R>>, csv::StringRecord),
}

impl<R: BufRead> Rows<R> {
    fn open(source: R, format: LoadFormat) -> Option<Self> {
        match format {
            LoadFormat::Json => Some(Self::Json(source.lines())),
            LoadFormat::Csv => {
                let mut reader = csv::ReaderBuilder::new().flexible(true).from_reader(source);
                let headers = reader.headers().ok()?.clone();
                Some(Self::Csv(Box::new(reader.into_records()), headers))
            }
        }
    }

    /// The next row's wire object, `None` at the end of the input and `Some(None)` for a
    /// row the reader cannot represent.
    fn next(&mut self) -> Option<Option<Map<String, Value>>> {
        match self {
            Self::Json(lines) => {
                let line = lines.next()?;
                Some(json_object(line.ok()?.as_str()))
            }
            Self::Csv(records, headers) => {
                let row = records.next()?;
                Some(row.ok().and_then(|row| csv_object(&row, headers)))
            }
        }
    }
}

/// Read a whole input into batches of records, `None` when any row falls outside what
/// the native types represent faithfully.
///
/// The batches are the statements the load will issue, so an empty input reads as no
/// batches and writes nothing. Executing a load walks its source rather than collecting
/// it, so this is for callers that genuinely want the whole file at once.
pub fn read(table: RecordTable, text: &str, format: LoadFormat) -> Option<Vec<Records>> {
    batches(table, text.as_bytes(), format)?
        .collect::<Result<_, _>>()
        .ok()
}

/// Build the one record a create names from its field values, `None` when a field or a
/// value falls outside what the native types represent faithfully.
///
/// Values arrive as the raw argument text. A payload field reads as YAML, the form the
/// create model takes it in, and every other field is the text itself. A field named
/// twice keeps its last value, the way a repeated flag does.
pub fn build(table: RecordTable, values: &[(String, String)]) -> Option<Records> {
    records(table, &[wire_object(table.schema(), values)?])
}

/// Build the one entity a create names from its field values, like the record `build`.
pub fn build_entity(
    table: EntityTable,
    values: &[(String, String)],
    credentials: Option<Credentials>,
) -> Option<Entities> {
    let object = wire_object(table.schema(), values)?;
    entities(table, &credentialed(table, &[object], credentials)?)
}

/// Read a create's raw argument text into one wire object.
///
/// A payload or value column reads as YAML, the form its create model takes it in, and
/// every other column is the text itself. A column named twice keeps its last value,
/// the way a repeated flag does.
fn wire_object(schema: Schema, values: &[(String, String)]) -> Option<Map<String, Value>> {
    let mut object = Map::new();
    for (key, text) in values {
        let field = schema.columns.iter().find(|field| field.key == key)?;
        let value = match field.family {
            FieldFamily::Json | FieldFamily::JsonValue => serde_norway::from_str(text).ok()?,
            _ => text.clone().into(),
        };
        object.insert(key.clone(), value);
    }

    Some(object)
}

/// Read one line as a JSON object.
///
/// Every line has to carry an object, a blank one included, which is what the Python
/// command's line-by-line validation does.
fn json_object(line: &str) -> Option<Map<String, Value>> {
    match serde_json::from_str(line) {
        Ok(Value::Object(object)) => Some(object),
        _ => None,
    }
}

/// Read one row of cells against the header that names them.
///
/// Cells arrive as text, exactly as Python's `DictReader` hands them to validation, so a
/// column holding anything but text refuses here the same way it fails there. A row
/// shorter than the header leaves its trailing fields null rather than absent, matching
/// the reader's own fill value, and a longer one refuses.
fn csv_object(row: &csv::StringRecord, headers: &csv::StringRecord) -> Option<Map<String, Value>> {
    if row.len() > headers.len() {
        return None;
    }

    let mut object = Map::new();
    for (index, name) in headers.iter().enumerate() {
        let cell = row.get(index).map_or(Value::Null, |cell| cell.into());
        // A header naming one field twice would silently drop a column, which the dict
        // reader also does, so the last cell wins here as it does there.
        object.insert(name.to_string(), cell);
    }

    Some(object)
}

/// Deserialize one batch of wire objects into records.
fn records(table: RecordTable, objects: &[Map<String, Value>]) -> Option<Records> {
    let rows = objects
        .iter()
        .map(|object| complete(accepted(table), object, record_default))
        .collect::<Option<Vec<_>>>()?;

    Some(match table {
        RecordTable::Messages => Records::Messages(convert::<Message>(rows)?),
        RecordTable::Particles => Records::Particles(convert::<Particle>(rows)?),
        RecordTable::Alerts => Records::Alerts(convert::<Alert>(rows)?),
        RecordTable::Logs => Records::LogEntries(convert::<LogEntry>(rows)?),
    })
}

/// Deserialize one batch of wire objects into entities.
fn entities(table: EntityTable, objects: &[Map<String, Value>]) -> Option<Entities> {
    let accepted: Vec<&'static str> = table
        .schema()
        .columns
        .iter()
        .map(|column| column.key)
        .collect();
    let rows = objects
        .iter()
        .map(|object| {
            let mut row = complete(&accepted, object, |key| entity_default(table, key))?;
            // A JSON column on an entity is declared `FromYAML`, so a value arriving as
            // text parses as YAML rather than staying a string. That is how a CSV cell
            // holding `1` becomes a number, and it applies to a JSON input naming a
            // string too, because the model's validator sees no difference.
            for field in table.schema().columns {
                if !matches!(field.family, FieldFamily::Json | FieldFamily::JsonValue) {
                    continue;
                }

                if let Some(Value::String(text)) = row.get(field.key) {
                    let parsed = serde_norway::from_str(text).ok()?;
                    row.insert(field.key.to_string(), parsed);
                }
            }

            Some(row)
        })
        .collect::<Option<Vec<_>>>()?;

    Some(match table {
        EntityTable::Users => Entities::Users(convert::<User>(rows)?),
        EntityTable::Variables => Entities::Variables(convert::<Variable>(rows)?),
        EntityTable::Settings => Entities::Settings(convert::<Setting>(rows)?),
        EntityTable::Workspaces => Entities::Workspaces(convert::<Workspace>(rows)?),
        EntityTable::WorkspaceEdits => Entities::WorkspaceEdits(convert::<WorkspaceEdit>(rows)?),
        EntityTable::Groups => Entities::Groups(convert::<Group>(rows)?),
        EntityTable::GroupMemberships => {
            Entities::GroupMemberships(convert::<GroupMembership>(rows)?)
        }
        EntityTable::UserPermissions => Entities::UserPermissions(convert::<UserPermission>(rows)?),
        EntityTable::GroupPermissions => {
            Entities::GroupPermissions(convert::<GroupPermission>(rows)?)
        }
    })
}

fn convert<T: serde::de::DeserializeOwned>(rows: Vec<Map<String, Value>>) -> Option<Vec<T>> {
    rows.into_iter()
        .map(|row| serde_json::from_value(Value::Object(row)).ok())
        .collect()
}

/// Fill in a row's absent fields and refuse one carrying a field the entity has no place
/// for, which the Python models reject rather than ignore.
///
/// A key the create model gives no default stays absent, so deserializing reports it
/// missing rather than reading a null the model would have refused.
fn complete(
    accepted: &[&str],
    object: &Map<String, Value>,
    default: impl Fn(&str) -> Option<Value>,
) -> Option<Map<String, Value>> {
    let mut remaining = object.len();
    let mut completed = Map::new();
    for &key in accepted {
        match object.get(key) {
            Some(value) => {
                remaining -= 1;
                completed.insert(key.to_string(), value.clone());
            }
            None => {
                if let Some(value) = default(key) {
                    completed.insert(key.to_string(), value);
                }
            }
        }
    }

    (remaining == 0).then_some(completed)
}

/// The wire keys a record accepts, its stored columns plus the fields it carries without
/// storing.
pub(crate) fn accepted(table: RecordTable) -> &'static [&'static str] {
    match table {
        // A particle's span locates it within the message bytes it was parsed from. It
        // travels with the entity but has no column, so a row may carry it and the
        // insert never binds it.
        RecordTable::Particles => &["id", "address", "timestamp", "type", "data", "span"],
        other => crate::writer::columns(other),
    }
}

/// The value an absent record field takes, matching the record models' own defaults.
fn record_default(key: &str) -> Option<Value> {
    Some(match key {
        "id" => uuid::Uuid::now_v7().to_string().into(),
        "timestamp" => Timestamp(chrono::Utc::now()).to_wire().into(),
        // Everything else on a record is either optional, which reads a null as absent,
        // or required, which refuses one.
        _ => Value::Null,
    })
}

/// The value an absent entity field takes, `None` for one its create model requires.
///
/// A variable's value is required and may still be null, so an absent one cannot read
/// as a null the way a record's optional column does.
fn entity_default(table: EntityTable, key: &str) -> Option<Value> {
    match (table, key) {
        (EntityTable::Workspaces, "id") => Some(uuid::Uuid::now_v7().to_string().into()),
        (EntityTable::Workspaces, "scope") => Some("~".into()),
        (EntityTable::Workspaces, "owner_id") => Some(Value::Null),
        (EntityTable::Workspaces, "show_when_logged_out") => Some(false.into()),
        (EntityTable::Workspaces, "data") => Some(Value::Object(Map::new())),
        (EntityTable::Users, "id") => Some(uuid::Uuid::now_v7().to_string().into()),
        (EntityTable::Users, "admin" | "disabled") => Some(false.into()),
        (EntityTable::Groups, "id") => Some(uuid::Uuid::now_v7().to_string().into()),
        (EntityTable::Groups, "description") => Some("".into()),
        // A permission and a membership name every one of their columns, and an edit
        // carries the draft it exists to hold, so none of them default.
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rows(records: &Records) -> usize {
        match records {
            Records::Messages(rows) => rows.len(),
            Records::Particles(rows) => rows.len(),
            Records::Alerts(rows) => rows.len(),
            Records::LogEntries(rows) => rows.len(),
        }
    }

    #[test]
    fn absent_keys_take_the_model_defaults() {
        let batches = read(
            RecordTable::Logs,
            "{\"address\": \"@a\", \"level\": \"info\", \"content\": \"x\"}\n",
            LoadFormat::Json,
        )
        .unwrap();
        let Records::LogEntries(entries) = &batches[0] else {
            panic!("expected log entries");
        };

        assert_eq!(entries.len(), 1);
        // A generated ID is a version 7 UUID, the same form the entity model generates.
        assert_eq!(entries[0].id.get_version_num(), 7);
        assert!(entries[0].timestamp.0 > chrono::DateTime::UNIX_EPOCH);
    }

    #[test]
    fn a_field_the_entity_has_no_place_for_refuses() {
        assert!(
            read(
                RecordTable::Logs,
                "{\"address\": \"@a\", \"level\": \"info\", \"content\": \"x\", \"nope\": 1}\n",
                LoadFormat::Json,
            )
            .is_none()
        );
    }

    #[test]
    fn a_particle_span_reads_without_a_column_to_store_it() {
        let batches = read(
            RecordTable::Particles,
            "{\"address\": \"@a\", \"type\": \"s\", \"data\": {\"k\": 1}, \"span\": [0, 3]}\n",
            LoadFormat::Json,
        )
        .unwrap();
        let Records::Particles(particles) = &batches[0] else {
            panic!("expected particles");
        };

        assert_eq!(particles[0].span, Some((0, 3)));
    }

    #[test]
    fn a_blank_or_malformed_line_refuses() {
        let line = "{\"address\": \"@a\", \"level\": \"info\", \"content\": \"x\"}";
        assert!(
            read(
                RecordTable::Logs,
                &format!("{line}\n\n{line}\n"),
                LoadFormat::Json
            )
            .is_none()
        );
        assert!(read(RecordTable::Logs, "[1]\n", LoadFormat::Json).is_none());
        // An empty input is a load of nothing, not a refusal.
        assert_eq!(
            read(RecordTable::Logs, "", LoadFormat::Json).unwrap().len(),
            0
        );
    }

    #[test]
    fn rows_batch_at_the_python_batch_size() {
        let line = "{\"address\": \"@a\", \"level\": \"info\", \"content\": \"x\"}\n";
        let batches = read(RecordTable::Logs, &line.repeat(BATCH + 1), LoadFormat::Json).unwrap();

        assert_eq!(batches.len(), 2);
        assert_eq!(rows(&batches[0]), BATCH);
        assert_eq!(rows(&batches[1]), 1);
    }

    #[test]
    fn csv_cells_read_as_the_text_they_are() {
        let batches = read(
            RecordTable::Messages,
            "id,address,timestamp,connection,direction,data\n\
             0198c0de-0000-7000-8000-000000000001,@a,2026-07-29T00:00:00Z,,receive,\"a,b\"\n",
            LoadFormat::Csv,
        )
        .unwrap();
        let Records::Messages(messages) = &batches[0] else {
            panic!("expected messages");
        };

        // An empty cell is the empty string, which is what the dict reader yields and
        // what the Python model then stores.
        assert_eq!(messages[0].connection.as_deref(), Some(""));
        assert_eq!(messages[0].data, b"a,b");
    }

    #[test]
    fn a_csv_column_holding_anything_but_text_refuses() {
        // A particle's payload crosses a CSV cell as JSON text, which the entity model
        // will not read back, so the load delegates rather than reading it differently.
        assert!(
            read(
                RecordTable::Particles,
                "id,address,timestamp,type,data\n\
                 0198c0de-0000-7000-8000-000000000001,@a,2026-07-29T00:00:00Z,s,\"{\"\"k\"\": 1}\"\n",
                LoadFormat::Csv,
            )
            .is_none()
        );
    }

    #[test]
    fn a_short_csv_row_leaves_its_trailing_fields_null() {
        // A missing optional column reads as null, which is the reader's fill value.
        let batches = read(
            RecordTable::Messages,
            "id,address,timestamp,direction,data,connection\n\
             0198c0de-0000-7000-8000-000000000001,@a,2026-07-29T00:00:00Z,receive,hi\n",
            LoadFormat::Csv,
        )
        .unwrap();
        let Records::Messages(messages) = &batches[0] else {
            panic!("expected messages");
        };

        assert_eq!(messages[0].connection, None);

        // A row longer than the header has cells with no field to land in.
        assert!(
            read(
                RecordTable::Logs,
                "address,level,content\n@a,info,x,extra\n",
                LoadFormat::Csv,
            )
            .is_none()
        );
    }

    #[test]
    fn a_created_record_fills_in_the_fields_it_was_not_given() {
        let pairs = |values: &[(&str, &str)]| {
            values
                .iter()
                .map(|(key, value)| (key.to_string(), value.to_string()))
                .collect::<Vec<_>>()
        };

        let Some(Records::Messages(messages)) = build(
            RecordTable::Messages,
            &pairs(&[("address", "@a"), ("direction", "receive"), ("data", "hi")]),
        ) else {
            panic!("expected one message");
        };

        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].id.get_version_num(), 7);
        assert_eq!(messages[0].connection, None);
        assert_eq!(messages[0].data, b"hi");

        // A payload reads as YAML, which is the grammar the create model takes.
        let Some(Records::Alerts(alerts)) = build(
            RecordTable::Alerts,
            &pairs(&[
                ("address", "@a"),
                ("level", "warning"),
                ("type", "t"),
                ("data", "{k: 1}"),
            ]),
        ) else {
            panic!("expected one alert");
        };

        assert_eq!(alerts[0].data["k"], 1);

        // A field the entity does not carry, a value outside a closed set, and a payload
        // that is not an object all refuse.
        assert!(build(RecordTable::Logs, &pairs(&[("nope", "1")])).is_none());
        assert!(
            build(
                RecordTable::Messages,
                &pairs(&[("address", "@a"), ("direction", "sideways"), ("data", "")]),
            )
            .is_none()
        );
        assert!(
            build(
                RecordTable::Alerts,
                &pairs(&[
                    ("address", "@a"),
                    ("level", "warning"),
                    ("type", "t"),
                    ("data", "3"),
                ]),
            )
            .is_none()
        );
    }

    #[test]
    fn formats_resolve_by_name_and_by_extension() {
        assert_eq!(LoadFormat::parse("csv"), Some(LoadFormat::Csv));
        assert_eq!(LoadFormat::parse("CSV"), None);
        assert_eq!(LoadFormat::infer("ndjson"), Some(LoadFormat::Json));
        assert_eq!(LoadFormat::infer("txt"), Some(LoadFormat::Json));
        assert_eq!(LoadFormat::infer("yaml"), None);
    }
}
