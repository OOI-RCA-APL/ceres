//! The record entities, the high-volume rows components produce and the API streams.
//!
//! Every record carries an ID, an address, and a timestamp, followed by its own fields.
//! Serialization order matches that layout, and each type's serialized form is the API's
//! wire format for it.

use ceres_config::Level;
use ceres_macros::{FilterValues, Filterable};
use enum_dispatch::enum_dispatch;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::address::Address;
// The entity types are named here because `enum_dispatch` expands the trait's impls for
// both batch enums at the trait's own module, pasting each variant's payload type name
// into this scope.
use crate::entities::{
    Entities, Group, GroupMembership, GroupPermission, Setting, User, UserPermission, Variable,
    Workspace, WorkspaceEdit,
};
use crate::filterable::Filterable;
use crate::timestamp::Timestamp;

/// The direction a message traveled through a connection.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, FilterValues)]
#[serde(rename_all = "lowercase")]
pub enum MessageDirection {
    Send,
    Receive,
}

/// Raw bytes exchanged with an external system over a component connection.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Message {
    pub id: Uuid,
    pub address: Address,
    pub timestamp: Timestamp,
    pub connection: Option<String>,
    pub direction: MessageDirection,
    #[serde(with = "latin1")]
    #[filterable(bare_operations)]
    pub data: Vec<u8>,
}

/// A parsed sample extracted from message bytes or produced directly by a component.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Particle {
    pub id: Uuid,
    pub address: Address,
    pub timestamp: Timestamp,
    #[serde(rename = "type")]
    pub kind: String,
    pub data: Map<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub span: Option<(i64, i64)>,
}

/// A leveled notification raised by a component.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct Alert {
    pub id: Uuid,
    pub address: Address,
    pub timestamp: Timestamp,
    pub level: Level,
    #[serde(rename = "type")]
    pub kind: String,
    pub data: Map<String, Value>,
}

/// One line of component log output.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize, Filterable)]
pub struct LogEntry {
    pub id: Uuid,
    pub address: Address,
    pub timestamp: Timestamp,
    pub level: Level,
    #[filterable(bare_operations)]
    pub content: String,
}

/// The latin-1 text form message bytes take on the wire.
///
/// Decoding bytes to text is total, every byte maps to the code point of its value.
/// Encoding text back to bytes drops characters above U+00FF, matching the API's
/// long-standing lossy `errors="ignore"` contract.
pub mod latin1 {
    use serde::{Deserialize, Deserializer, Serializer};

    /// Decode bytes into their latin-1 text form.
    pub fn decode(bytes: &[u8]) -> String {
        bytes.iter().map(|&byte| byte as char).collect()
    }

    /// Encode latin-1 text into bytes, dropping characters outside the range.
    pub fn encode(text: &str) -> Vec<u8> {
        text.chars()
            .filter_map(|character| u8::try_from(character as u32).ok())
            .collect()
    }

    pub fn serialize<S: Serializer>(bytes: &[u8], serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&decode(bytes))
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Vec<u8>, D::Error> {
        Ok(encode(&String::deserialize(deserializer)?))
    }
}

/// One CSV cell, quoted the way Python's `csv` module minimally quotes.
///
/// A cell quotes only when it holds the delimiter, a quote, or a line break, and an
/// inner quote doubles. Everything else passes through verbatim, including the raw
/// latin-1 text of message bytes.
fn csv_cell(value: &str, line: &mut String) {
    if value.contains(['"', ',', '\n', '\r']) {
        line.push('"');
        for character in value.chars() {
            if character == '"' {
                line.push('"');
            }

            line.push(character);
        }

        line.push('"');
    } else {
        line.push_str(value);
    }
}

/// One CSV row from its cells, an absent value rendering as an empty cell.
fn csv_row(cells: &[Option<String>], lines: &mut String) {
    for (index, cell) in cells.iter().enumerate() {
        if index > 0 {
            lines.push(',');
        }

        if let Some(cell) = cell {
            csv_cell(cell, lines);
        }
    }

    lines.push('\n');
}

/// Render a sequence of records as CSV lines, under a header row unless suppressed.
///
/// The full wire schema is the implicit projection, every field under its own wire key
/// in declaration order, so the cells here are the projected cells and cannot drift
/// from them. An empty sequence still renders the header, so the output always carries
/// its schema.
pub(crate) fn to_csv_lines<T: Serialize + Filterable>(
    records: &[T],
    header: bool,
) -> serde_json::Result<String> {
    let fields: Vec<(String, String)> = T::WIRE_KEYS
        .iter()
        .map(|key| (key.to_string(), key.to_string()))
        .collect();
    to_csv_lines_projected(records, &fields, header)
}

/// Serialize a sequence of records as one JSON array.
pub(crate) fn to_json_array<T: Serialize>(records: &[T]) -> serde_json::Result<Vec<u8>> {
    serde_json::to_vec(records)
}

/// Serialize a sequence's first record, `null` when the sequence is empty.
pub(crate) fn to_json_first<T: Serialize>(records: &[T]) -> serde_json::Result<Vec<u8>> {
    match records.first() {
        Some(record) => serde_json::to_vec(record),
        None => Ok(b"null".to_vec()),
    }
}

/// Serialize a sequence of records as JSON lines, one record per line.
pub(crate) fn to_json_lines<T: Serialize>(records: &[T]) -> serde_json::Result<Vec<u8>> {
    let mut lines = Vec::new();
    for record in records {
        serde_json::to_writer(&mut lines, record)?;
        lines.push(b'\n');
    }

    Ok(lines)
}

/// One record's projected wire object, aliased keys in projection order.
///
/// A name the wire object lacks, whether unknown or an omitted `span`, projects as
/// null. A repeated alias keeps its first position and takes the last field's value,
/// which is how a Python dict built from the same pairs behaves.
fn project<T: Serialize>(
    record: &T,
    fields: &[(String, String)],
) -> serde_json::Result<Map<String, Value>> {
    let mut object = match serde_json::to_value(record)? {
        Value::Object(object) => object,
        _ => Map::new(),
    };

    let mut projected = Map::new();
    for (field, alias) in fields {
        let value = object.remove(field).unwrap_or(Value::Null);
        projected.insert(alias.clone(), value);
    }

    Ok(projected)
}

/// The aliases a projection outputs, first occurrence winning the position.
fn projected_aliases(fields: &[(String, String)]) -> Vec<&str> {
    let mut aliases: Vec<&str> = Vec::new();
    for (_, alias) in fields {
        if !aliases.contains(&alias.as_str()) {
            aliases.push(alias);
        }
    }

    aliases
}

/// One projected wire value as its CSV cell, JSON text for anything structured.
fn projected_cell(value: Value) -> Option<String> {
    match value {
        Value::Null => None,
        Value::String(text) => Some(text),
        other => Some(other.to_string()),
    }
}

/// Serialize projected records as JSON lines, one aliased object per line.
pub(crate) fn to_json_lines_projected<T: Serialize>(
    records: &[T],
    fields: &[(String, String)],
) -> serde_json::Result<Vec<u8>> {
    let mut lines = Vec::new();
    for record in records {
        serde_json::to_writer(&mut lines, &Value::Object(project(record, fields)?))?;
        lines.push(b'\n');
    }

    Ok(lines)
}

/// Render projected records as CSV lines, an alias header row unless suppressed.
///
/// An empty sequence still renders the header, so the output always carries its
/// schema.
pub(crate) fn to_csv_lines_projected<T: Serialize>(
    records: &[T],
    fields: &[(String, String)],
    header: bool,
) -> serde_json::Result<String> {
    let mut lines = String::new();
    if header {
        let aliases: Vec<Option<String>> = projected_aliases(fields)
            .into_iter()
            .map(|alias| Some(alias.to_string()))
            .collect();
        csv_row(&aliases, &mut lines);
    }

    for record in records {
        let cells: Vec<Option<String>> = project(record, fields)?
            .into_iter()
            .map(|(_, value)| projected_cell(value))
            .collect();
        csv_row(&cells, &mut lines);
    }

    Ok(lines)
}

/// Render a batch of one entity type in every shape the CLI and API emit.
///
/// The batch enums implement this through `enum_dispatch`, each method reaching the
/// variant's payload vector, and the one generic impl below serves every payload. A new
/// entity type is one enum line, and it cannot be added while being forgotten by the
/// renderers. The enums keep inherent methods over this trait for callers holding a
/// concrete batch, while code generic over both bounds on the trait itself.
#[enum_dispatch]
pub trait RenderRows {
    /// The number of rows held.
    fn len(&self) -> usize;

    /// Whether no rows are held.
    fn is_empty(&self) -> bool;

    /// Serialize the first row in the wire format, `null` when none matched.
    fn to_json_first(&self) -> serde_json::Result<Vec<u8>>;

    /// Serialize the rows as one JSON array in the API's wire format.
    fn to_json_array(&self) -> serde_json::Result<Vec<u8>>;

    /// Serialize the rows as JSON lines in the wire format, one per line.
    fn to_json_lines(&self) -> serde_json::Result<Vec<u8>>;

    /// Render the rows as CSV lines in the wire cell forms, under a header row unless
    /// suppressed.
    fn to_csv_lines(&self, header: bool) -> serde_json::Result<String>;

    /// Serialize a field projection of the rows as JSON lines, aliased objects.
    fn to_json_lines_projected(&self, fields: &[(String, String)]) -> serde_json::Result<Vec<u8>>;

    /// Render a field projection of the rows as CSV lines, an alias header row unless
    /// suppressed.
    fn to_csv_lines_projected(
        &self,
        fields: &[(String, String)],
        header: bool,
    ) -> serde_json::Result<String>;
}

impl<T: Serialize + Filterable> RenderRows for Vec<T> {
    fn len(&self) -> usize {
        Vec::len(self)
    }

    fn is_empty(&self) -> bool {
        Vec::is_empty(self)
    }

    fn to_json_first(&self) -> serde_json::Result<Vec<u8>> {
        to_json_first(self)
    }

    fn to_json_array(&self) -> serde_json::Result<Vec<u8>> {
        to_json_array(self)
    }

    fn to_json_lines(&self) -> serde_json::Result<Vec<u8>> {
        to_json_lines(self)
    }

    fn to_csv_lines(&self, header: bool) -> serde_json::Result<String> {
        to_csv_lines(self, header)
    }

    fn to_json_lines_projected(&self, fields: &[(String, String)]) -> serde_json::Result<Vec<u8>> {
        to_json_lines_projected(self, fields)
    }

    fn to_csv_lines_projected(
        &self,
        fields: &[(String, String)],
        header: bool,
    ) -> serde_json::Result<String> {
        to_csv_lines_projected(self, fields, header)
    }
}

/// The records of one query result, all of a single entity type.
#[enum_dispatch(RenderRows)]
#[derive(Clone, Debug, PartialEq)]
pub enum Records {
    Messages(Vec<Message>),
    Particles(Vec<Particle>),
    Alerts(Vec<Alert>),
    LogEntries(Vec<LogEntry>),
}

impl Records {
    /// The number of records held.
    pub fn len(&self) -> usize {
        RenderRows::len(self)
    }

    /// Whether no records are held.
    pub fn is_empty(&self) -> bool {
        RenderRows::is_empty(self)
    }

    /// Serialize the first record in the wire format, `null` when none matched.
    pub fn to_json_first(&self) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_first(self)
    }

    /// Serialize the records as one JSON array in the API's wire format.
    pub fn to_json_array(&self) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_array(self)
    }

    /// Serialize the records as JSON lines in the wire format, one record per line.
    pub fn to_json_lines(&self) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_lines(self)
    }

    /// Render the records as CSV lines in the wire cell forms, under a header row
    /// unless suppressed.
    pub fn to_csv_lines(&self, header: bool) -> serde_json::Result<String> {
        RenderRows::to_csv_lines(self, header)
    }

    /// Serialize a field projection of the records as JSON lines, aliased objects.
    pub fn to_json_lines_projected(
        &self,
        fields: &[(String, String)],
    ) -> serde_json::Result<Vec<u8>> {
        RenderRows::to_json_lines_projected(self, fields)
    }

    /// Render a field projection of the records as CSV lines, an alias header row
    /// unless suppressed.
    pub fn to_csv_lines_projected(
        &self,
        fields: &[(String, String)],
        header: bool,
    ) -> serde_json::Result<String> {
        RenderRows::to_csv_lines_projected(self, fields, header)
    }
}

#[cfg(test)]
mod tests {
    use chrono::{TimeZone, Utc};

    use super::*;

    fn timestamp() -> Timestamp {
        let base = Utc.with_ymd_and_hms(2026, 7, 29, 12, 30, 45).unwrap();
        Timestamp(Utc.timestamp_opt(base.timestamp(), 123_456_000).unwrap())
    }

    fn id() -> Uuid {
        "0198c0de-0000-7000-8000-000000000001".parse().unwrap()
    }

    fn address() -> Address {
        Address::parse("@sensor.temp").unwrap()
    }

    #[test]
    fn messages_serialize_like_the_api() {
        let message = Message {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            connection: None,
            direction: MessageDirection::Receive,
            data: vec![0x01, 0x02, b'A', b'B', b'C', 0xff],
        };
        let serialized = serde_json::to_string(&message).unwrap();
        let expected = concat!(
            "{\"id\":\"0198c0de-0000-7000-8000-000000000001\",",
            "\"address\":\"@sensor.temp\",",
            "\"timestamp\":\"2026-07-29T12:30:45.123456Z\",",
            "\"connection\":null,",
            "\"direction\":\"receive\",",
            "\"data\":\"\\u0001\\u0002ABCÿ\"}",
        );
        assert_eq!(
            serde_json::from_str::<Message>(&serialized).unwrap(),
            message
        );
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&serialized).unwrap(),
            serde_json::from_str::<serde_json::Value>(expected).unwrap()
        );
    }

    #[test]
    fn particles_omit_an_unset_span() {
        let mut data = Map::new();
        data.insert("a".to_string(), Value::from(1));

        let mut particle = Particle {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            kind: "sample".to_string(),
            data,
            span: None,
        };
        let serialized = serde_json::to_string(&particle).unwrap();
        assert!(serialized.contains("\"type\":\"sample\""));
        assert!(!serialized.contains("span"));

        particle.span = Some((3, 17));
        let serialized = serde_json::to_string(&particle).unwrap();
        assert!(serialized.ends_with("\"span\":[3,17]}"));
    }

    #[test]
    fn log_entries_serialize_like_the_api() {
        let entry = LogEntry {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            level: Level::Info,
            content: "hello".to_string(),
        };
        assert_eq!(
            serde_json::to_string(&entry).unwrap(),
            "{\"id\":\"0198c0de-0000-7000-8000-000000000001\",\
             \"address\":\"@sensor.temp\",\
             \"timestamp\":\"2026-07-29T12:30:45.123456Z\",\
             \"level\":\"info\",\"content\":\"hello\"}"
        );
    }

    #[test]
    fn csv_rows_quote_like_the_python_writer() {
        let messages = vec![
            Message {
                id: id(),
                address: address(),
                timestamp: timestamp(),
                connection: None,
                direction: MessageDirection::Receive,
                data: b"plain".to_vec(),
            },
            Message {
                id: id(),
                address: address(),
                timestamp: timestamp(),
                connection: Some("serial".to_string()),
                direction: MessageDirection::Send,
                data: b"a,b \"c\"\nd".to_vec(),
            },
        ];
        let rendered = to_csv_lines(&messages, true).unwrap();
        let mut lines = rendered.split_inclusive('\n');
        assert_eq!(
            lines.next().unwrap(),
            "id,address,timestamp,connection,direction,data\n"
        );
        assert_eq!(
            lines.next().unwrap(),
            "0198c0de-0000-7000-8000-000000000001,@sensor.temp,\
             2026-07-29T12:30:45.123456Z,,receive,plain\n"
        );
        // The quoted cell keeps its inner line break, so the row spans two raw lines.
        assert_eq!(
            rendered,
            concat!(
                "id,address,timestamp,connection,direction,data\n",
                "0198c0de-0000-7000-8000-000000000001,@sensor.temp,",
                "2026-07-29T12:30:45.123456Z,,receive,plain\n",
                "0198c0de-0000-7000-8000-000000000001,@sensor.temp,",
                "2026-07-29T12:30:45.123456Z,serial,send,\"a,b \"\"c\"\"\nd\"\n",
            )
        );
    }

    #[test]
    fn csv_cells_render_json_and_absent_values() {
        let mut data = Map::new();
        data.insert("b".to_string(), Value::from(2));
        data.insert("a".to_string(), Value::from(1));

        let particles = vec![Particle {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            kind: "sample".to_string(),
            data,
            span: None,
        }];
        let rendered = to_csv_lines(&particles, true).unwrap();
        assert!(rendered.starts_with("id,address,timestamp,type,data,span\n"));
        // JSON cells quote for their commas, keys staying in insertion order, and an
        // absent span renders as an empty cell.
        assert!(
            rendered.ends_with(",sample,\"{\"\"b\"\":2,\"\"a\"\":1}\",\n"),
            "{rendered}"
        );
    }

    #[test]
    fn latin1_round_trips_bytes_and_drops_wide_characters() {
        let bytes: Vec<u8> = (0..=255).collect();
        assert_eq!(latin1::encode(&latin1::decode(&bytes)), bytes);
        assert_eq!(latin1::encode("A\u{2603}B"), b"AB");
    }

    fn pairs(fields: &[(&str, &str)]) -> Vec<(String, String)> {
        fields
            .iter()
            .map(|(field, alias)| (field.to_string(), alias.to_string()))
            .collect()
    }

    #[test]
    fn projections_alias_reorder_and_null_unknown_fields() {
        let mut data = Map::new();
        data.insert("a".to_string(), Value::from(1));

        let particles = vec![Particle {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            kind: "sample".to_string(),
            data,
            span: None,
        }];
        let fields = pairs(&[
            ("type", "kind"),
            ("id", "id"),
            ("nonexistent", "nonexistent"),
            ("span", "span"),
        ]);

        let lines = to_json_lines_projected(&particles, &fields).unwrap();
        // An omitted span and an unknown name both project as null, and the keys
        // follow the projection's own order.
        assert_eq!(
            String::from_utf8(lines).unwrap(),
            "{\"kind\":\"sample\",\
             \"id\":\"0198c0de-0000-7000-8000-000000000001\",\
             \"nonexistent\":null,\"span\":null}\n"
        );

        let rendered = to_csv_lines_projected(&particles, &fields, true).unwrap();
        assert_eq!(
            rendered,
            "kind,id,nonexistent,span\n\
             sample,0198c0de-0000-7000-8000-000000000001,,\n"
        );
    }

    #[test]
    fn projections_render_structured_cells_as_json() {
        let mut data = Map::new();
        data.insert("b".to_string(), Value::from(2.5));
        data.insert("a".to_string(), Value::from(1));

        let particles = vec![Particle {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            kind: "sample".to_string(),
            data,
            span: Some((3, 17)),
        }];
        let fields = pairs(&[("data", "data"), ("span", "span")]);

        let lines = to_json_lines_projected(&particles, &fields).unwrap();
        assert_eq!(
            String::from_utf8(lines).unwrap(),
            "{\"data\":{\"b\":2.5,\"a\":1},\"span\":[3,17]}\n"
        );

        let rendered = to_csv_lines_projected(&particles, &fields, true).unwrap();
        assert_eq!(
            rendered,
            "data,span\n\"{\"\"b\"\":2.5,\"\"a\"\":1}\",\"[3,17]\"\n"
        );
    }

    #[test]
    fn empty_sequences_still_render_the_csv_header() {
        let none: Vec<Message> = Vec::new();
        assert_eq!(
            to_csv_lines(&none, true).unwrap(),
            "id,address,timestamp,connection,direction,data\n"
        );
        assert_eq!(
            to_csv_lines_projected(&none, &pairs(&[("id", "id"), ("data", "raw")]), true).unwrap(),
            "id,raw\n"
        );
    }

    #[test]
    fn suppressed_headers_leave_only_the_rows() {
        let entries = vec![LogEntry {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            level: Level::Info,
            content: "hello".to_string(),
        }];
        assert_eq!(
            to_csv_lines(&entries, false).unwrap(),
            "0198c0de-0000-7000-8000-000000000001,@sensor.temp,\
             2026-07-29T12:30:45.123456Z,info,hello\n"
        );
        assert_eq!(
            to_csv_lines_projected(&entries, &pairs(&[("content", "text")]), false).unwrap(),
            "hello\n"
        );

        let none: Vec<LogEntry> = Vec::new();
        assert_eq!(to_csv_lines(&none, false).unwrap(), "");
        assert_eq!(
            to_csv_lines_projected(&none, &pairs(&[("id", "id")]), false).unwrap(),
            ""
        );
    }

    #[test]
    fn a_repeated_alias_collapses_onto_its_first_position() {
        let entries = vec![LogEntry {
            id: id(),
            address: address(),
            timestamp: timestamp(),
            level: Level::Info,
            content: "hello".to_string(),
        }];
        let fields = pairs(&[("level", "value"), ("content", "value"), ("id", "id")]);

        let lines = to_json_lines_projected(&entries, &fields).unwrap();
        assert_eq!(
            String::from_utf8(lines).unwrap(),
            "{\"value\":\"hello\",\"id\":\"0198c0de-0000-7000-8000-000000000001\"}\n"
        );

        let rendered = to_csv_lines_projected(&entries, &fields, true).unwrap();
        assert_eq!(
            rendered,
            "value,id\nhello,0198c0de-0000-7000-8000-000000000001\n"
        );
    }
}
