//! Native record batches.
//!
//! Query results for the record entities are parsed straight from database row mappings
//! into the `ceres-entities` structs and held natively. The API's pass-through paths
//! serialize a whole batch to JSON in one call, so no Python entity objects exist for rows
//! that only travel from the database to a response body.

use ceres_config::Level;
use ceres_entities::{Address, Alert, LogEntry, Message, MessageDirection, Particle, Timestamp};
use chrono::{DateTime, NaiveDateTime, Utc};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use serde_json::{Map, Value};
use uuid::Uuid;

/// The records of one batch, all of a single entity type.
enum Records {
    Messages(Vec<Message>),
    Particles(Vec<Particle>),
    Alerts(Vec<Alert>),
    LogEntries(Vec<LogEntry>),
}

/// A batch of records held natively, parsed from database rows.
///
/// Built through `parse` from the raw row mappings a query produces, and serialized with
/// `to_json` as the API's wire format for a record listing.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordBatch {
    records: Records,
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
        match &self.records {
            Records::Messages(records) => records.len(),
            Records::Particles(records) => records.len(),
            Records::Alerts(records) => records.len(),
            Records::LogEntries(records) => records.len(),
        }
    }

    /// Serialize the batch as a JSON array in the API's wire format.
    fn to_json<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let serialized = match &self.records {
            Records::Messages(records) => ceres_entities::to_json_array(records),
            Records::Particles(records) => ceres_entities::to_json_array(records),
            Records::Alerts(records) => ceres_entities::to_json_array(records),
            Records::LogEntries(records) => ceres_entities::to_json_array(records),
        };
        let serialized = serialized.map_err(|error| PyValueError::new_err(error.to_string()))?;
        Ok(PyBytes::new(py, &serialized))
    }
}

fn parse_rows<T>(
    rows: &[Bound<'_, PyAny>],
    parse: fn(&Bound<'_, PyAny>) -> PyResult<T>,
) -> PyResult<Vec<T>> {
    rows.iter().map(parse).collect()
}

fn parse_message(row: &Bound<'_, PyAny>) -> PyResult<Message> {
    Ok(Message {
        id: parse_id(row)?,
        address: parse_address(row)?,
        timestamp: parse_timestamp(row)?,
        connection: row.get_item("connection")?.extract()?,
        direction: match row.get_item("direction")?.extract::<String>()?.as_str() {
            "send" => MessageDirection::Send,
            "receive" => MessageDirection::Receive,
            other => {
                return Err(PyValueError::new_err(format!(
                    "{other:?} is not a message direction"
                )));
            }
        },
        data: row.get_item("data")?.extract()?,
    })
}

fn parse_particle(row: &Bound<'_, PyAny>) -> PyResult<Particle> {
    Ok(Particle {
        id: parse_id(row)?,
        address: parse_address(row)?,
        timestamp: parse_timestamp(row)?,
        kind: row.get_item("type")?.extract()?,
        data: parse_data(row)?,
        // The span is a transient parsing artifact that is never persisted.
        span: None,
    })
}

fn parse_alert(row: &Bound<'_, PyAny>) -> PyResult<Alert> {
    Ok(Alert {
        id: parse_id(row)?,
        address: parse_address(row)?,
        timestamp: parse_timestamp(row)?,
        level: parse_level(row)?,
        kind: row.get_item("type")?.extract()?,
        data: parse_data(row)?,
    })
}

fn parse_log_entry(row: &Bound<'_, PyAny>) -> PyResult<LogEntry> {
    Ok(LogEntry {
        id: parse_id(row)?,
        address: parse_address(row)?,
        timestamp: parse_timestamp(row)?,
        level: parse_level(row)?,
        content: row.get_item("content")?.extract()?,
    })
}

fn parse_id(row: &Bound<'_, PyAny>) -> PyResult<Uuid> {
    row.get_item("id")?.extract()
}

fn parse_address(row: &Bound<'_, PyAny>) -> PyResult<Address> {
    // Address objects are string-backed rather than string-subclassed, so take their text
    // form. Addresses were validated when written, the value is trusted on the way out.
    Ok(Address::trusted(
        row.get_item("address")?.str()?.to_string(),
    ))
}

fn parse_timestamp(row: &Bound<'_, PyAny>) -> PyResult<Timestamp> {
    let value = row.get_item("timestamp")?;
    if let Ok(aware) = value.extract::<DateTime<Utc>>() {
        return Ok(Timestamp(aware));
    }

    // Some drivers hand back naive datetimes, which the database layer defines as UTC.
    let naive: NaiveDateTime = value.extract()?;
    Ok(Timestamp(naive.and_utc()))
}

fn parse_level(row: &Bound<'_, PyAny>) -> PyResult<Level> {
    let text: String = row.get_item("level")?.extract()?;
    Level::parse(&text).map_err(PyValueError::new_err)
}

fn parse_data(row: &Bound<'_, PyAny>) -> PyResult<Map<String, Value>> {
    crate::interop::from_python::<Map<String, Value>>(&row.get_item("data")?)
}
