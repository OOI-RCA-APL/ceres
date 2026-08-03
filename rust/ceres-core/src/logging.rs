//! Bindings for the logging configuration section.
//!
//! Written by hand rather than through `python_config!`, because the section resolves
//! defaults at access time and merges by explicitly-set fields, which the macro's direct
//! field mapping cannot express.

use ceres_config::{Level, LogToggle, RawLoggingConfig};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use pyo3_stub_gen::{PyStubType, TypeInfo};

use crate::interop::{problems_to_error, to_python};

/// A level constructor argument, accepting a level name.
pub struct LevelInput(Level);

impl FromPyObject<'_, '_> for LevelInput {
    type Error = PyErr;

    fn extract(value: pyo3::Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        let text: String = value.extract()?;
        Level::parse(&text).map(Self).map_err(PyValueError::new_err)
    }
}

impl PyStubType for LevelInput {
    fn type_output() -> TypeInfo {
        TypeInfo::builtin("str")
    }
}

/// A toggle constructor argument, accepting a boolean or a level name.
pub struct LogToggleInput(LogToggle);

impl FromPyObject<'_, '_> for LogToggleInput {
    type Error = PyErr;

    fn extract(value: pyo3::Borrowed<'_, '_, PyAny>) -> PyResult<Self> {
        if let Ok(enabled) = value.extract::<bool>() {
            return Ok(Self(LogToggle::Enabled(enabled)));
        }

        let text: String = value.extract()?;
        Level::parse(&text)
            .map(|level| Self(LogToggle::Level(level)))
            .map_err(PyValueError::new_err)
    }
}

impl PyStubType for LogToggleInput {
    fn type_output() -> TypeInfo {
        TypeInfo::builtin("bool | str")
    }
}

/// Convert a resolved toggle into its Python form, a boolean or a level name.
fn toggle_to_python(py: Python<'_>, toggle: LogToggle) -> PyResult<Py<PyAny>> {
    to_python(py, &toggle)
}

/// Per-component or per-engine logging configuration.
///
/// `output` and `store` set minimum levels for the streamed and persisted log streams, and
/// the toggle fields enable optional logging of specific record types, accepting either a
/// boolean or a minimum level.
#[gen_stub_pyclass]
#[pyclass(subclass, module = "ceres.__internal__.core")]
#[derive(Debug, Clone)]
pub struct LoggingConfig {
    pub(crate) inner: ceres_config::LoggingConfig,
}

#[gen_stub_pymethods]
#[pymethods]
impl LoggingConfig {
    #[new]
    #[pyo3(signature = (
        *,
        output = None,
        store = None,
        events = None,
        messages = None,
        particles = None,
        alerts = None,
    ))]
    fn new(
        output: Option<LevelInput>,
        store: Option<LevelInput>,
        events: Option<LogToggleInput>,
        messages: Option<LogToggleInput>,
        particles: Option<LogToggleInput>,
        alerts: Option<LogToggleInput>,
    ) -> PyResult<Self> {
        let raw = RawLoggingConfig {
            output: output.map(|input| input.0),
            store: store.map(|input| input.0),
            events: events.map(|input| input.0),
            messages: messages.map(|input| input.0),
            particles: particles.map(|input| input.0),
            alerts: alerts.map(|input| input.0),
        };
        let inner = ceres_config::LoggingConfig::try_from(raw).map_err(problems_to_error)?;
        Ok(Self { inner })
    }

    /// Minimum severity that reaches the engine's streamed log output.
    #[getter]
    fn output(&self) -> &'static str {
        self.inner.output().as_str()
    }

    /// Minimum severity persisted to the engine's log store.
    #[getter]
    fn store(&self) -> &'static str {
        self.inner.store().as_str()
    }

    /// Whether to log events, or the minimum severity to log them at.
    #[getter]
    #[gen_stub(override_return_type(type_repr = "bool | str"))]
    fn events(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        toggle_to_python(py, self.inner.events())
    }

    /// Whether to log raw connection messages, or the minimum severity to log them at.
    #[getter]
    #[gen_stub(override_return_type(type_repr = "bool | str"))]
    fn messages(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        toggle_to_python(py, self.inner.messages())
    }

    /// Whether to log parsed particles, or the minimum severity to log them at.
    #[getter]
    #[gen_stub(override_return_type(type_repr = "bool | str"))]
    fn particles(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        toggle_to_python(py, self.inner.particles())
    }

    /// Whether to log alerts, or the minimum severity to log them at.
    #[getter]
    #[gen_stub(override_return_type(type_repr = "bool | str"))]
    fn alerts(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        toggle_to_python(py, self.inner.alerts())
    }

    /// Overlay another configuration's explicitly-set fields onto this one.
    fn merged(&self, other: &Self) -> Self {
        Self {
            inner: self.inner.merged(&other.inner),
        }
    }

    /// Return the explicitly-set fields as a plain dictionary.
    ///
    /// Supports rebuilding an equivalent configuration without turning resolved defaults
    /// into explicit settings.
    #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
    fn provided(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let inner = &self.inner;
        let mut provided = serde_json::Map::new();
        let mut insert = |name: &str, value: Option<serde_json::Value>| {
            if let Some(value) = value {
                provided.insert(name.to_string(), value);
            }
        };

        insert("output", inner.output.map(|level| level.as_str().into()));
        insert("store", inner.store.map(|level| level.as_str().into()));

        for (name, toggle) in [
            ("events", inner.events),
            ("messages", inner.messages),
            ("particles", inner.particles),
            ("alerts", inner.alerts),
        ] {
            insert(name, toggle.map(|toggle| serde_json::json!(toggle)));
        }

        to_python(py, &provided)
    }

    /// Return the configuration as a plain dictionary of JSON-compatible values.
    ///
    /// Called through `ceres.data.to_dict` rather than directly.
    #[pyo3(name = "__to_dict__")]
    #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
    fn to_dict(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        to_python(py, &self.inner)
    }

    /// Return the JSON Schema describing this configuration section.
    ///
    /// Called through `ceres.data.to_json_schema` rather than directly.
    #[staticmethod]
    #[pyo3(name = "__json_schema__")]
    #[gen_stub(override_return_type(type_repr = "dict[str, typing.Any]"))]
    fn json_schema(py: Python<'_>) -> PyResult<Py<PyAny>> {
        let schema = schemars::schema_for!(RawLoggingConfig);
        to_python(py, &schema)
    }

    fn __eq__(&self, other: &Bound<'_, PyAny>) -> bool {
        match other.cast::<LoggingConfig>() {
            Ok(other) => self.inner == other.borrow().inner,
            Err(_) => false,
        }
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}
