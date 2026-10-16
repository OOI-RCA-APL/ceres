//! Bindings for the logging configuration section, and the bridge carrying the native crates'
//! log records to the engine's log.
//!
//! This module writes the configuration bindings by hand rather than through `python_config!`,
//! because the section resolves defaults at access time and merges by explicitly-set fields,
//! which the macro's direct field mapping cannot express.

use std::sync::{Arc, Mutex, OnceLock, PoisonError};

use ceres_config::{Level, LogToggle, RawLoggingConfig};
use log::LevelFilter;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3_async_runtimes::TaskLocals;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use pyo3_stub_gen::{PyStubType, TypeInfo};

use crate::interop::{problems_to_error, to_python};

/// Writes messages to the engine's log, anything with `debug`, `info`, `warning`, and `error`
/// methods taking the message.
///
/// Before serving starts, a message goes to the log on the thread writing it. Once serving, it
/// goes to the event loop serving started on, since tokio threads write most of them.
pub(crate) struct LogSink {
    log: Py<PyAny>,
    locals: Arc<OnceLock<TaskLocals>>,
}

impl LogSink {
    pub(crate) fn new(log: Py<PyAny>, locals: Arc<OnceLock<TaskLocals>>) -> Self {
        Self { log, locals }
    }

    /// Writes `message` with the log's method named `level`.
    pub(crate) fn write(&self, level: &str, message: String) {
        Python::attach(|py| {
            let logged = match self.locals.get() {
                Some(locals) => self.log.getattr(py, level).and_then(|method| {
                    locals
                        .event_loop(py)
                        .call_method1("call_soon_threadsafe", (method, message))
                        .map(drop)
                }),
                None => self.log.bind(py).call_method1(level, (message,)).map(drop),
            };
            if let Err(error) = logged {
                error.write_unraisable(py, None);
            }
        });
    }
}

/// The sink the native crates' records go to, and how many listeners hold it.
struct Sinks {
    sink: Option<Arc<LogSink>>,
    holders: usize,
}

/// Carries the `log` records of the crates named `ceres_*` to the engine's log while a web
/// listener holds a sink, and drops every record otherwise.
///
/// Dropping a record without a sink keeps a tokio thread from attaching to an interpreter
/// shutting down, which can deadlock, or from scheduling onto a closed event loop.
struct EngineLogger {
    sinks: Mutex<Sinks>,
}

static LOGGER: EngineLogger = EngineLogger {
    sinks: Mutex::new(Sinks {
        sink: None,
        holders: 0,
    }),
};

/// Installs the bridge as the process's logger, which drops every record until a listener
/// holds a sink.
pub(crate) fn install_logger() {
    // The module initializes once a process, and nothing else in it sets a logger.
    let _ = log::set_logger(&LOGGER);
    log::set_max_level(LevelFilter::Off);
}

/// Sends the native crates' records at `level` and above to `sink`, replacing the sink an
/// earlier listener holds, until every holder lets go with `release_log_sink`.
pub(crate) fn hold_log_sink(sink: Arc<LogSink>, level: Level) {
    let mut sinks = LOGGER.sinks.lock().unwrap_or_else(PoisonError::into_inner);
    sinks.sink = Some(sink);
    sinks.holders += 1;
    log::set_max_level(level_filter(level));
}

/// Lets go of a sink `hold_log_sink` handed over, dropping every record once the last holder
/// lets go.
pub(crate) fn release_log_sink() {
    let mut sinks = LOGGER.sinks.lock().unwrap_or_else(PoisonError::into_inner);
    sinks.holders = sinks.holders.saturating_sub(1);
    if sinks.holders == 0 {
        sinks.sink = None;
        log::set_max_level(LevelFilter::Off);
    }
}

/// The `log` filter letting through the records the engine's log keeps at `level`.
fn level_filter(level: Level) -> LevelFilter {
    match level {
        Level::Debug => LevelFilter::Debug,
        Level::Info => LevelFilter::Info,
        Level::Warning => LevelFilter::Warn,
        Level::Error | Level::Critical => LevelFilter::Error,
    }
}

/// The engine log method a record at `level` goes to.
fn method(level: log::Level) -> &'static str {
    match level {
        log::Level::Error => "error",
        log::Level::Warn => "warning",
        log::Level::Info => "info",
        log::Level::Debug | log::Level::Trace => "debug",
    }
}

/// Whether a record from `target` at `level` reaches an engine log keeping `max` and above.
///
/// Only the crates of this workspace, since str0m and the other dependencies log at a volume
/// and in terms meant for their own developers.
fn forwards(target: &str, level: log::Level, max: LevelFilter) -> bool {
    target.starts_with("ceres_") && level <= max
}

impl log::Log for EngineLogger {
    fn enabled(&self, metadata: &log::Metadata<'_>) -> bool {
        forwards(metadata.target(), metadata.level(), log::max_level())
    }

    fn log(&self, record: &log::Record<'_>) {
        if !self.enabled(record.metadata()) {
            return;
        }
        // Cloned out, so the record waits to attach without holding the lock.
        let sink = self
            .sinks
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .sink
            .clone();
        if let Some(sink) = sink {
            sink.write(method(record.level()), record.args().to_string());
        }
    }

    fn flush(&self) {}
}

/// A level constructor argument, accepting a level name.
pub struct LevelInput(pub(crate) Level);

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

    /// Return the explicitly-set fields as a plain dictionary.
    ///
    /// Supports rebuilding an equivalent configuration without turning resolved defaults
    /// into explicit settings, and overlaying one configuration onto another as a plain
    /// dictionary union.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_engine_log_gets_records_from_this_workspace_at_its_level() {
        assert!(forwards(
            "ceres_webrtc::session",
            log::Level::Info,
            LevelFilter::Info
        ));
        assert!(forwards("ceres_media", log::Level::Warn, LevelFilter::Info));
        assert!(!forwards(
            "ceres_media",
            log::Level::Debug,
            LevelFilter::Info
        ));
        assert!(forwards(
            "ceres_media",
            log::Level::Debug,
            LevelFilter::Debug
        ));
        assert!(!forwards(
            "ceres_webrtc",
            log::Level::Error,
            LevelFilter::Off
        ));
    }

    #[test]
    fn the_engine_log_never_gets_records_from_dependencies() {
        assert!(!forwards(
            "str0m::rtp",
            log::Level::Error,
            LevelFilter::Debug
        ));
        assert!(!forwards("hyper", log::Level::Warn, LevelFilter::Debug));
    }

    #[test]
    fn a_record_goes_to_the_engine_log_method_of_its_level() {
        assert_eq!(method(log::Level::Error), "error");
        assert_eq!(method(log::Level::Warn), "warning");
        assert_eq!(method(log::Level::Info), "info");
        assert_eq!(method(log::Level::Trace), "debug");
        assert_eq!(level_filter(Level::Warning), LevelFilter::Warn);
        assert_eq!(level_filter(Level::Critical), LevelFilter::Error);
    }
}
