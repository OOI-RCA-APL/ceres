//! Python bindings for the native record filter compiler.
//!
//! The compiler is the single authority on the record filter language. The Python
//! query layer parses its filters here and executes the compiled SQL on its own
//! session, and live record streams test membership through the same parsed filter,
//! so the wire paths, the programmatic API, and stream matching cannot diverge.

use pyo3::IntoPyObjectExt;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pyfunction, gen_stub_pymethods};

use ceres_database::{Refusal, SqlDialect};

use crate::entities::RecordTable;

/// A parsed record filter, held natively and reused across calls.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct RecordFilter {
    filter: ceres_database::RecordFilter,
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

/// Parse a record filter from ordered wire query pairs.
#[gen_stub_pyfunction]
#[pyfunction]
pub fn parse_record_filter(
    table: RecordTable,
    pairs: Vec<(String, String)>,
) -> PyResult<RecordFilter> {
    let filter =
        ceres_database::RecordFilter::parse(table.into(), &pairs).map_err(refusal_error)?;
    Ok(RecordFilter { filter })
}

/// Parse a record filter from its serialized JSON form, the filter model's dump.
#[gen_stub_pyfunction]
#[pyfunction]
pub fn record_filter_from_json(table: RecordTable, json: &str) -> PyResult<RecordFilter> {
    let filter =
        ceres_database::RecordFilter::from_json(table.into(), json).map_err(refusal_error)?;
    Ok(RecordFilter { filter })
}

#[gen_stub_pymethods]
#[pymethods]
impl RecordFilter {
    /// The filter's limit, `None` when unbounded.
    #[getter]
    fn limit(&self) -> Option<u64> {
        self.filter.limit()
    }

    /// Compile to SQL and its parameters for a dialect, a listing statement or a
    /// count.
    ///
    /// The parameters arrive in placeholder order for a driver-level execute, `?`
    /// style for the SQLite family and `$n` for PostgreSQL.
    #[pyo3(signature = (dialect, *, count = false))]
    fn compiled<'py>(
        &self,
        py: Python<'py>,
        dialect: &str,
        count: bool,
    ) -> PyResult<(String, Vec<Bound<'py, PyAny>>)> {
        let (sql, values) = self.filter.compiled(dialect_of(dialect)?, count);
        let parameters = values
            .into_iter()
            .map(|value| bind_value(py, value))
            .collect::<PyResult<Vec<_>>>()?;
        Ok((sql, parameters))
    }

    /// Whether one serialized record matches this filter.
    ///
    /// Query controls and subsampling do not participate, this reads a single record
    /// the way live stream filtering does.
    fn matches(&self, record_json: &str) -> PyResult<bool> {
        self.filter
            .matches(record_json)
            .map_err(PyValueError::new_err)
    }
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
        Value::Uuid(value) => value.map(|value| *value).into_bound_py_any(py)?,
        other => {
            return Err(PyValueError::new_err(format!(
                "{other:?} is not a value the compiler binds"
            )));
        }
    };
    Ok(object)
}
