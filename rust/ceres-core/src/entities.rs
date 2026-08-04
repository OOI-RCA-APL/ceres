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
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pyclass_enum, gen_stub_pymethods};
use serde_json::{Map, Value};
use uuid::Uuid;

/// A batch of records held natively, parsed from database rows.
///
/// Built through `parse` from the raw row mappings a query produces, and serialized with
/// `to_json` as the API's wire format for a record listing.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
pub struct RecordBatch {
    pub(crate) records: Records,
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordBatch {
    /// Parse database row mappings into a native batch.
    ///
    /// Row values arrive through the database layer's column mappers, so they are trusted
    /// rather than revalidated here.
    #[staticmethod]
    fn parse(table: RecordTable, rows: Vec<Bound<'_, PyAny>>) -> PyResult<Self> {
        let records = match table {
            RecordTable::Messages => Records::Messages(parse_rows(&rows, parse_message)?),
            RecordTable::Particles => Records::Particles(parse_rows(&rows, parse_particle)?),
            RecordTable::Alerts => Records::Alerts(parse_rows(&rows, parse_alert)?),
            RecordTable::Logs => Records::LogEntries(parse_rows(&rows, parse_log_entry)?),
        };

        Ok(Self { records })
    }

    /// Serialize one live record entity as JSON in the API's wire format.
    ///
    /// Reads the entity object's attributes rather than row values, so streamed records
    /// serialize natively too. Raises `ValueError` for payload values richer than JSON,
    /// which the caller serializes through Pydantic instead.
    #[staticmethod]
    fn record_to_json<'py>(
        py: Python<'py>,
        table: RecordTable,
        record: &Bound<'_, PyAny>,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let source = Source::Entity(record);
        let serialized = match table {
            RecordTable::Messages => serde_json::to_vec(&parse_message(&source)?),
            RecordTable::Particles => serde_json::to_vec(&parse_particle(&source)?),
            RecordTable::Alerts => serde_json::to_vec(&parse_alert(&source)?),
            RecordTable::Logs => serde_json::to_vec(&parse_log_entry(&source)?),
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

/// One of the record tables, the selector native record operations dispatch on.
#[gen_stub_pyclass_enum]
#[pyclass(
    module = "ceres.__internal__.core",
    eq,
    frozen,
    hash,
    rename_all = "UPPERCASE"
)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum RecordTable {
    Messages,
    Particles,
    Alerts,
    Logs,
}

impl From<RecordTable> for ceres_database::RecordTable {
    fn from(table: RecordTable) -> Self {
        match table {
            RecordTable::Messages => Self::Messages,
            RecordTable::Particles => Self::Particles,
            RecordTable::Alerts => Self::Alerts,
            RecordTable::Logs => Self::Logs,
        }
    }
}

/// One of the non-record entity tables the entity commands manage.
#[gen_stub_pyclass_enum]
#[pyclass(
    module = "ceres.__internal__.core",
    eq,
    frozen,
    hash,
    rename_all = "UPPERCASE"
)]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum EntityTable {
    Users,
    Variables,
    Settings,
    Workspaces,
    WorkspaceEdits,
    Groups,
    GroupMemberships,
    UserPermissions,
    GroupPermissions,
}

impl From<EntityTable> for ceres_database::EntityTable {
    fn from(table: EntityTable) -> Self {
        match table {
            EntityTable::Users => Self::Users,
            EntityTable::Variables => Self::Variables,
            EntityTable::Settings => Self::Settings,
            EntityTable::Workspaces => Self::Workspaces,
            EntityTable::WorkspaceEdits => Self::WorkspaceEdits,
            EntityTable::Groups => Self::Groups,
            EntityTable::GroupMemberships => Self::GroupMemberships,
            EntityTable::UserPermissions => Self::UserPermissions,
            EntityTable::GroupPermissions => Self::GroupPermissions,
        }
    }
}

/// Parse live entity objects into natively-held records, for the write path.
pub(crate) fn records_from_entities(
    table: RecordTable,
    entities: &[Bound<'_, PyAny>],
) -> PyResult<Records> {
    fn parse_all<T>(
        entities: &[Bound<'_, PyAny>],
        parse: fn(&Source<'_, '_>) -> PyResult<T>,
    ) -> PyResult<Vec<T>> {
        entities
            .iter()
            .map(|entity| parse(&Source::Entity(entity)))
            .collect()
    }

    match table {
        RecordTable::Messages => Ok(Records::Messages(parse_all(entities, parse_message)?)),
        RecordTable::Particles => Ok(Records::Particles(parse_all(entities, parse_particle)?)),
        RecordTable::Alerts => Ok(Records::Alerts(parse_all(entities, parse_alert)?)),
        RecordTable::Logs => Ok(Records::LogEntries(parse_all(entities, parse_log_entry)?)),
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
