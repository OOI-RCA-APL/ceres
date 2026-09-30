//! Live camera streams remuxed by `ceres-media`, read from Python in chunks.

use std::sync::Arc;
use std::time::Duration;

use ceres_media::{RemuxOptions, RemuxStream, RtspSource};
use pyo3::exceptions::{PyConnectionError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::interop::to_value_error;

/// An RTSP camera remuxed into one fragmented MP4 stream on a thread of its own.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen)]
pub struct RtspStream {
    stream: Arc<RemuxStream>,
}

#[gen_stub_pymethods]
#[pymethods]
impl RtspStream {
    /// Connects to `url` and starts remuxing, reconnecting a lost camera when `reconnect`.
    ///
    /// `transport` is `"tcp"` or `"udp"`. Durations are in seconds, and a `stall_timeout`
    /// of `None` waits on a silent camera forever.
    #[new]
    #[pyo3(signature = (url, *, transport, fragment_duration, dash, reconnect, stall_timeout))]
    fn new(
        url: String,
        transport: String,
        fragment_duration: f64,
        dash: bool,
        reconnect: bool,
        stall_timeout: Option<f64>,
    ) -> PyResult<Self> {
        if !matches!(transport.as_str(), "tcp" | "udp") {
            return Err(PyValueError::new_err(format!(
                "transport must be \"tcp\" or \"udp\", not {transport:?}"
            )));
        }
        let options = RemuxOptions {
            fragment_duration: seconds("fragment_duration", fragment_duration)?,
            dash,
            reconnect,
            stall_timeout: stall_timeout
                .map(|timeout| seconds("stall_timeout", timeout))
                .transpose()?,
            ..RemuxOptions::default()
        };
        let source = RtspSource { url, transport };
        Ok(Self {
            stream: Arc::new(RemuxStream::start(source, options)),
        })
    }

    /// The next chunk of the MP4 stream as `bytes`, `None` once the stream ends.
    ///
    /// Waiting blocks a thread of its own so a quiet camera leaves the event loop free.
    fn next<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = Arc::clone(&self.stream);
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let chunk = pyo3_async_runtimes::tokio::get_runtime()
                .spawn_blocking(move || stream.next())
                .await
                .map_err(to_value_error)?;
            match chunk {
                None => Ok(None),
                Some(Ok(bytes)) => Ok(Some(Python::attach(|py| PyBytes::new(py, &bytes).unbind()))),
                Some(Err(error)) => Err(PyConnectionError::new_err(error.to_string())),
            }
        })
    }

    /// Stops the stream, closing the connection and ending `next` after any buffered chunks.
    fn close(&self) {
        self.stream.stop();
    }
}

/// A duration argument in seconds, refusing a negative or non-finite value.
fn seconds(name: &str, value: f64) -> PyResult<Duration> {
    Duration::try_from_secs_f64(value)
        .map_err(|_| PyValueError::new_err(format!("{name} must be a finite non-negative number")))
}
