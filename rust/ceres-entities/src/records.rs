//! The record entities, the high-volume rows components produce and the API streams.
//!
//! Every record carries an ID, an address, and a timestamp, followed by its own fields.
//! Serialization order matches that layout, and each type's serialized form is the API's
//! wire format for it.

use ceres_config::Level;
use ceres_macros::{FilterValues, Filterable};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::address::Address;
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

/// Serialize a sequence of records as one JSON array.
pub fn to_json_array<T: Serialize>(records: &[T]) -> serde_json::Result<Vec<u8>> {
    serde_json::to_vec(records)
}

/// Serialize a sequence's first record, `null` when the sequence is empty.
pub fn to_json_first<T: Serialize>(records: &[T]) -> serde_json::Result<Vec<u8>> {
    match records.first() {
        Some(record) => serde_json::to_vec(record),
        None => Ok(b"null".to_vec()),
    }
}

/// Serialize a sequence of records as JSON lines, one record per line.
pub fn to_json_lines<T: Serialize>(records: &[T]) -> serde_json::Result<Vec<u8>> {
    let mut lines = Vec::new();
    for record in records {
        serde_json::to_writer(&mut lines, record)?;
        lines.push(b'\n');
    }

    Ok(lines)
}

/// The records of one query result, all of a single entity type.
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
        match self {
            Self::Messages(records) => records.len(),
            Self::Particles(records) => records.len(),
            Self::Alerts(records) => records.len(),
            Self::LogEntries(records) => records.len(),
        }
    }

    /// Whether no records are held.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Serialize the first record in the wire format, `null` when none matched.
    pub fn to_json_first(&self) -> serde_json::Result<Vec<u8>> {
        match self {
            Self::Messages(records) => to_json_first(records),
            Self::Particles(records) => to_json_first(records),
            Self::Alerts(records) => to_json_first(records),
            Self::LogEntries(records) => to_json_first(records),
        }
    }

    /// Serialize the records as JSON lines in the wire format, one record per line.
    pub fn to_json_lines(&self) -> serde_json::Result<Vec<u8>> {
        match self {
            Self::Messages(records) => to_json_lines(records),
            Self::Particles(records) => to_json_lines(records),
            Self::Alerts(records) => to_json_lines(records),
            Self::LogEntries(records) => to_json_lines(records),
        }
    }

    /// Serialize the records as one JSON array in the API's wire format.
    pub fn to_json_array(&self) -> serde_json::Result<Vec<u8>> {
        match self {
            Self::Messages(records) => to_json_array(records),
            Self::Particles(records) => to_json_array(records),
            Self::Alerts(records) => to_json_array(records),
            Self::LogEntries(records) => to_json_array(records),
        }
    }
}

#[cfg(test)]
mod tests {
    use chrono::TimeZone;
    use chrono::Utc;

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
    fn latin1_round_trips_bytes_and_drops_wide_characters() {
        let bytes: Vec<u8> = (0..=255).collect();
        assert_eq!(latin1::encode(&latin1::decode(&bytes)), bytes);
        assert_eq!(latin1::encode("A\u{2603}B"), b"AB");
    }
}
