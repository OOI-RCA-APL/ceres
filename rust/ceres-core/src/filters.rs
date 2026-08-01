//! Python bindings for the native filter compiler.
//!
//! The compiler is the single authority on the filter language. The Python query layer
//! parses its filters here and runs the compiled statement on the native store, and live
//! record streams test membership through the same parsed filter, so the wire paths, the
//! programmatic API, and stream matching cannot diverge.
//!
//! One class serves both halves of the table split. The record tables and the entity
//! tables compile from different schemas, but a caller holding a filter wants the same
//! things from it either way, so the table it names decides which schema parses it and
//! nothing above here has to know which half it fell in.

use pyo3::IntoPyObjectExt;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use ceres_database::{Refusal, SqlDialect, Table};

/// A filter parsed against one table's schema.
enum Parsed {
    Record(ceres_database::RecordFilter),
    Entity(ceres_database::EntityFilter),
}

/// Delegate a method to whichever half parsed the filter.
///
/// Both halves carry the same surface, so every one of these is the same call against a
/// different schema, and writing them out would say nothing the table name does not.
macro_rules! delegate {
    ($self:ident, $method:ident($($argument:expr),* $(,)?)) => {
        match &$self.filter {
            Parsed::Record(filter) => filter.$method($($argument),*),
            Parsed::Entity(filter) => filter.$method($($argument),*),
        }
    };
}

/// A parsed filter, held natively and reused across calls.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct NativeFilter {
    filter: Parsed,
}

/// Convert a refusal into the error the Python caller raises.
///
/// An invalid value carries the wire message. The one construct with no native form,
/// a particle's `class`, reports as unsupported so callers resolve it before parsing.
fn refusal_error(refusal: Refusal) -> PyErr {
    match refusal {
        Refusal::Invalid(message) => PyValueError::new_err(message),
        Refusal::Delegated => {
            PyValueError::new_err("the filter holds a construct with no native form")
        }
    }
}

/// The dialect a compile targets, by the database type's name.
fn dialect_of(name: &str) -> PyResult<SqlDialect> {
    match name {
        "sqlite" | "turso" => Ok(SqlDialect::SqliteText),
        "postgres" => Ok(SqlDialect::Postgres),
        other => Err(PyValueError::new_err(format!("unknown dialect {other:?}"))),
    }
}

/// The table a filter names, refusing one no table answers to.
fn table_of(name: &str) -> PyResult<Table> {
    Table::parse(name).ok_or_else(|| PyValueError::new_err(format!("no table is named {name:?}")))
}

#[gen_stub_pymethods]
#[pymethods]
impl NativeFilter {
    /// Parse a filter from ordered wire query pairs.
    #[staticmethod]
    fn from_pairs(table: &str, pairs: Vec<(String, String)>) -> PyResult<Self> {
        let filter = match table_of(table)? {
            Table::Record(table) => Parsed::Record(
                ceres_database::RecordFilter::parse(table, &pairs).map_err(refusal_error)?,
            ),
            Table::Entity(table) => Parsed::Entity(
                ceres_database::EntityFilter::parse(table, &pairs).map_err(refusal_error)?,
            ),
        };
        Ok(Self { filter })
    }

    /// Parse a filter from its serialized JSON form, the filter model's dump.
    #[staticmethod]
    fn from_json(table: &str, json: &str) -> PyResult<Self> {
        let filter = match table_of(table)? {
            Table::Record(table) => Parsed::Record(
                ceres_database::RecordFilter::from_json(table, json).map_err(refusal_error)?,
            ),
            Table::Entity(table) => Parsed::Entity(
                ceres_database::EntityFilter::from_json(table, json).map_err(refusal_error)?,
            ),
        };
        Ok(Self { filter })
    }

    /// The filter's limit, `None` when unbounded.
    #[getter]
    fn limit(&self) -> Option<u64> {
        delegate!(self, limit())
    }

    /// The filter's offset, `None` when unset.
    #[getter]
    fn offset(&self) -> Option<u64> {
        delegate!(self, offset())
    }

    /// The `WHERE` conditions as inline SQL for a dialect, `None` when the filter is
    /// unconditional.
    ///
    /// The text embeds into a statement the caller builds, so values render as literals
    /// rather than binds. The caller's clock decides age-relative conditions, so a
    /// session under a faked or frozen time stays authoritative.
    #[pyo3(signature = (dialect, now = None))]
    fn where_sql(
        &self,
        dialect: &str,
        now: Option<chrono::DateTime<chrono::Utc>>,
    ) -> PyResult<Option<String>> {
        let dialect = dialect_of(dialect)?;
        let now = now.map(|now| now.naive_utc());
        Ok(delegate!(self, where_sql(dialect, now)))
    }

    /// The `ORDER BY` terms as inline SQL for a dialect, including the table's default
    /// ordering.
    fn order_sql(&self, dialect: &str) -> PyResult<Option<String>> {
        let dialect = dialect_of(dialect)?;
        Ok(delegate!(self, order_sql(dialect)))
    }

    /// Compile to SQL and its parameters for a dialect, a listing statement or a count.
    ///
    /// The parameters arrive in placeholder order for a driver-level execute, `?` style
    /// for the SQLite family and `$n` for PostgreSQL. The caller's clock decides
    /// age-relative conditions, and the whole statement resolves it once, so `min_age`
    /// and `max_age` in one filter cannot straddle a tick.
    #[pyo3(signature = (dialect, *, count = false, now = None))]
    fn compiled<'py>(
        &self,
        py: Python<'py>,
        dialect: &str,
        count: bool,
        now: Option<chrono::DateTime<chrono::Utc>>,
    ) -> PyResult<(String, Vec<Bound<'py, PyAny>>)> {
        let dialect = dialect_of(dialect)?;
        let now = now.map(|now| now.naive_utc());
        let (sql, values) = delegate!(self, compiled(dialect, count, now));
        bound(py, sql, values)
    }

    /// Compile the existence check to SQL and its parameters for a dialect.
    ///
    /// The shape an `any` command runs, which stops at the first matching row.
    #[pyo3(signature = (dialect, now = None))]
    fn exists_compiled<'py>(
        &self,
        py: Python<'py>,
        dialect: &str,
        now: Option<chrono::DateTime<chrono::Utc>>,
    ) -> PyResult<(String, Vec<Bound<'py, PyAny>>)> {
        let dialect = dialect_of(dialect)?;
        let now = now.map(|now| now.naive_utc());
        let (sql, values) = delegate!(self, exists_compiled(dialect, now));
        bound(py, sql, values)
    }

    /// Whether one serialized row matches this filter.
    ///
    /// Query controls and subsampling do not participate, this reads a single row the way
    /// live stream filtering does.
    #[pyo3(signature = (record_json, now = None))]
    fn matches(
        &self,
        record_json: &str,
        now: Option<chrono::DateTime<chrono::Utc>>,
    ) -> PyResult<bool> {
        let now = now.map(|now| now.naive_utc());
        delegate!(self, matches(record_json, now)).map_err(PyValueError::new_err)
    }
}

/// A compiled statement with its parameters as the objects their driver binds.
fn bound<'py>(
    py: Python<'py>,
    sql: String,
    values: Vec<ceres_database::BindValue>,
) -> PyResult<(String, Vec<Bound<'py, PyAny>>)> {
    let parameters = values
        .into_iter()
        .map(|value| bind_value(py, value))
        .collect::<PyResult<Vec<_>>>()?;
    Ok((sql, parameters))
}

/// One compiled parameter as the Python object its driver binds.
fn bind_value<'py>(
    py: Python<'py>,
    value: ceres_database::BindValue,
) -> PyResult<Bound<'py, PyAny>> {
    use ceres_database::BindValue as Value;

    let object = match value {
        Value::Bool(value) => value.into_bound_py_any(py)?,
        Value::TinyInt(value) => value.into_bound_py_any(py)?,
        Value::SmallInt(value) => value.into_bound_py_any(py)?,
        Value::Int(value) => value.into_bound_py_any(py)?,
        Value::BigInt(value) => value.into_bound_py_any(py)?,
        Value::TinyUnsigned(value) => value.into_bound_py_any(py)?,
        Value::SmallUnsigned(value) => value.into_bound_py_any(py)?,
        Value::Unsigned(value) => value.into_bound_py_any(py)?,
        Value::BigUnsigned(value) => value.into_bound_py_any(py)?,
        Value::Float(value) => value.into_bound_py_any(py)?,
        Value::Double(value) => value.into_bound_py_any(py)?,
        Value::String(value) => value.map(|value| *value).into_bound_py_any(py)?,
        Value::Bytes(value) => match value {
            Some(bytes) => pyo3::types::PyBytes::new(py, &bytes[..]).into_any(),
            None => py.None().into_bound(py),
        },
        // The Python layer binds aware UTC datetimes, and PostgreSQL's timestamps are
        // timezone-aware columns, so a naive bind would read in the session's zone.
        Value::ChronoDateTime(value) => value.map(|value| value.and_utc()).into_bound_py_any(py)?,
        Value::ChronoDateTimeUtc(value) => value.map(|value| *value).into_bound_py_any(py)?,
        Value::Uuid(value) => value.map(|value| *value).into_bound_py_any(py)?,
        other => {
            return Err(PyValueError::new_err(format!(
                "{other:?} is not a value the compiler binds"
            )));
        }
    };
    Ok(object)
}
