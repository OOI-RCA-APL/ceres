//! Native record batches.
//!
//! Query results for the record entities are parsed straight from database row mappings
//! into the `ceres-entities` structs and held natively. The API's pass-through paths
//! serialize a whole batch to JSON in one call, so no Python entity objects exist for rows
//! that only travel from the database to a response body.

use ceres_config::Level;
use ceres_entities::{
    Address, Alert, LogEntry, Message, MessageDirection, Particle, Records, Timestamp,
};
use chrono::{DateTime, NaiveDateTime, Utc};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use serde_json::{Map, Value};
use uuid::Uuid;

/// A batch of records held natively, parsed from database rows.
///
/// Built through `parse` from the raw row mappings a query produces, and serialized with
/// `to_json` as the API's wire format for a record listing.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordBatch {
    pub(crate) records: Records,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordBatch {
    /// Parse database row mappings into a native batch.
    ///
    /// `table` selects the record type by its table name. Row values arrive through the
    /// database layer's column mappers, so they are trusted rather than revalidated here.
    #[staticmethod]
    fn parse(table: &str, rows: Vec<Bound<'_, PyAny>>) -> PyResult<Self> {
        let records = match table {
            "messages" => Records::Messages(parse_rows(&rows, parse_message)?),
            "particles" => Records::Particles(parse_rows(&rows, parse_particle)?),
            "alerts" => Records::Alerts(parse_rows(&rows, parse_alert)?),
            "logs" => Records::LogEntries(parse_rows(&rows, parse_log_entry)?),
            other => {
                return Err(PyValueError::new_err(format!(
                    "{other:?} is not a record table"
                )));
            }
        };

        Ok(Self { records })
    }

    fn __len__(&self) -> usize {
        self.records.len()
    }

    /// Serialize one live record entity as JSON in the API's wire format.
    ///
    /// Reads the entity object's attributes rather than row values, so streamed records
    /// serialize natively too. Raises `ValueError` for payload values richer than JSON,
    /// which the caller serializes through Pydantic instead.
    #[staticmethod]
    fn record_to_json<'py>(
        py: Python<'py>,
        table: &str,
        record: &Bound<'_, PyAny>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let source = Source::Entity(record);
        let serialized = match table {
            "messages" => serde_json::to_vec(&parse_message(&source)?),
            "particles" => serde_json::to_vec(&parse_particle(&source)?),
            "alerts" => serde_json::to_vec(&parse_alert(&source)?),
            "logs" => serde_json::to_vec(&parse_log_entry(&source)?),
            other => {
                return Err(PyValueError::new_err(format!(
                    "{other:?} is not a record table"
                )));
            }
        };
        let serialized = serialized.map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(PyBytes::new(py, &serialized))
    }

    /// Serialize the batch as a JSON array in the API's wire format.
    fn to_json<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let serialized = self
            .records
            .to_json_array()
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(PyBytes::new(py, &serialized))
    }
}

/// Where a record's field values come from.
///
/// Database rows arrive as mappings keyed by column name, live records arrive as entity
/// objects read by attribute. The two differ in one more way, a row never carries the
/// transient particle span while an entity object does.
enum Source<'a, 'py> {
    Row(&'a Bound<'py, PyAny>),
    Entity(&'a Bound<'py, PyAny>),
}

impl<'py> Source<'_, 'py> {
    fn get(&self, field: &str) -> PyResult<Bound<'py, PyAny>> {
        match self {
            Self::Row(mapping) => mapping.get_item(field),
            Self::Entity(object) => object.getattr(field),
        }
    }

    fn span(&self) -> PyResult<Option<(i64, i64)>> {
        match self {
            Self::Row(_) => Ok(None),
            Self::Entity(object) => object.getattr("span")?.extract(),
        }
    }
}

fn parse_rows<T>(
    rows: &[Bound<'_, PyAny>],
    parse: fn(&Source<'_, '_>) -> PyResult<T>,
) -> PyResult<Vec<T>> {
    rows.iter().map(|row| parse(&Source::Row(row))).collect()
}

fn parse_message(source: &Source<'_, '_>) -> PyResult<Message> {
    Ok(Message {
        id: parse_id(source)?,
        address: parse_address(source)?,
        timestamp: parse_timestamp(source)?,
        connection: source.get("connection")?.extract()?,
        direction: match source.get("direction")?.extract::<String>()?.as_str() {
            "send" => MessageDirection::Send,
            "receive" => MessageDirection::Receive,
            other => {
                return Err(PyValueError::new_err(format!(
                    "{other:?} is not a message direction"
                )));
            }
        },
        data: source.get("data")?.extract()?,
    })
}

fn parse_particle(source: &Source<'_, '_>) -> PyResult<Particle> {
    Ok(Particle {
        id: parse_id(source)?,
        address: parse_address(source)?,
        timestamp: parse_timestamp(source)?,
        kind: source.get("type")?.extract()?,
        data: parse_data(source)?,
        span: source.span()?,
    })
}

fn parse_alert(source: &Source<'_, '_>) -> PyResult<Alert> {
    Ok(Alert {
        id: parse_id(source)?,
        address: parse_address(source)?,
        timestamp: parse_timestamp(source)?,
        level: parse_level(source)?,
        kind: source.get("type")?.extract()?,
        data: parse_data(source)?,
    })
}

fn parse_log_entry(source: &Source<'_, '_>) -> PyResult<LogEntry> {
    Ok(LogEntry {
        id: parse_id(source)?,
        address: parse_address(source)?,
        timestamp: parse_timestamp(source)?,
        level: parse_level(source)?,
        content: source.get("content")?.extract()?,
    })
}

fn parse_id(source: &Source<'_, '_>) -> PyResult<Uuid> {
    source.get("id")?.extract()
}

fn parse_address(source: &Source<'_, '_>) -> PyResult<Address> {
    // Address objects are string-backed rather than string-subclassed, so take their text
    // form. Addresses were validated when written, the value is trusted on the way out.
    Ok(Address::trusted(source.get("address")?.str()?.to_string()))
}

fn parse_timestamp(source: &Source<'_, '_>) -> PyResult<Timestamp> {
    let value = source.get("timestamp")?;
    if let Ok(aware) = value.extract::<DateTime<Utc>>() {
        return Ok(Timestamp(aware));
    }

    // Some drivers hand back naive datetimes, which the database layer defines as UTC.
    let naive: NaiveDateTime = value.extract()?;
    Ok(Timestamp(naive.and_utc()))
}

fn parse_level(source: &Source<'_, '_>) -> PyResult<Level> {
    let text: String = source.get("level")?.extract()?;
    Level::parse(&text).map_err(PyValueError::new_err)
}

fn parse_data(source: &Source<'_, '_>) -> PyResult<Map<String, Value>> {
    let value = source.get("data")?;
    if let Source::Entity(_) = source {
        // A live record may carry a typed payload object whose Pydantic serialization can
        // differ from its mapping view, only plain dictionaries serialize natively.
        value
            .cast_exact::<pyo3::types::PyDict>()
            .map_err(|_| PyValueError::new_err("typed payloads serialize through Pydantic"))?;
    }

    crate::interop::from_python::<Map<String, Value>>(&value)
}
