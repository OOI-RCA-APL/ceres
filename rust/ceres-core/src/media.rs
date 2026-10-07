//! Live camera streams remuxed by `ceres-media`, read from Python in chunks.

use std::sync::Arc;
use std::time::Duration;

use ceres_media::{RemuxOptions, RemuxStream, RtspSource, StreamItem, StreamNotice};
use pyo3::exceptions::{PyConnectionError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};

use crate::interop::to_value_error;

/// Something an `RtspStream` reports besides its bytes.
#[gen_stub_pyclass]
#[pyclass(module = "ceres.__internal__.core", frozen, get_all)]
pub struct RtspNotice {
    /// `"lost"`, `"retrying"`, `"reconnected"`, or `"ended"`.
    kind: &'static str,
    /// Why the camera was lost or the stream ended, if known.
    reason: Option<String>,
    /// Seconds until the first attempt to reach a lost camera again, for `"retrying"`.
    delay: Option<f64>,
    /// How many connections the outage took, for `"reconnected"`.
    attempts: Option<u32>,
    /// Seconds the outage lasted, for `"reconnected"`.
    outage: Option<f64>,
}

impl From<StreamNotice> for RtspNotice {
    fn from(notice: StreamNotice) -> Self {
        let blank = Self {
            kind: "",
            reason: None,
            delay: None,
            attempts: None,
            outage: None,
        };
        match notice {
            StreamNotice::Lost { reason } => Self {
                kind: "lost",
                reason,
                ..blank
            },
            StreamNotice::Retrying { delay } => Self {
                kind: "retrying",
                delay: Some(delay.as_secs_f64()),
                ..blank
            },
            StreamNotice::Reconnected { attempts, outage } => Self {
                kind: "reconnected",
                attempts: Some(attempts),
                outage: Some(outage.as_secs_f64()),
                ..blank
            },
            StreamNotice::Ended { reason } => Self {
                kind: "ended",
                reason: Some(reason),
                ..blank
            },
        }
    }
}

/// An RTSP camera remuxed into a fragmented MP4 stream.
///
/// Streams of one camera with the same `transport`, `copy`, and `stall_timeout` share its
/// connection, so a camera allowing few sessions serves any number of them.
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
    /// Without `copy` the video is re-encoded as H.264. `transport` is `"tcp"` or `"udp"`.
    /// Durations are in seconds, and a `stall_timeout` of `None` waits on a silent camera
    /// forever.
    #[new]
    #[pyo3(signature = (url, *, copy, transport, fragment_duration, dash, reconnect, stall_timeout))]
    fn new(
        url: String,
        copy: bool,
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
            copy,
            fragment_duration: seconds("fragment_duration", fragment_duration)?,
            dash,
            reconnect,
            stall_timeout: stall_timeout
                .map(|timeout| seconds("stall_timeout", timeout))
                .transpose()?,
            ..RemuxOptions::default()
        };
        let key = format!("{transport} {copy} {stall_timeout:?} {url}");
        let source = || RtspSource { url, transport };
        Ok(Self {
            stream: Arc::new(RemuxStream::shared(key, source, options)),
        })
    }

    /// The next chunk of the MP4 stream as `bytes`, or an `RtspNotice`, `None` once the stream
    /// ends.
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
                Some(Ok(StreamItem::Chunk(bytes))) => Ok(Some(Python::attach(|py| {
                    PyBytes::new(py, &bytes).into_any().unbind()
                }))),
                Some(Ok(StreamItem::Notice(notice))) => Ok(Some(Python::attach(|py| {
                    Ok::<_, PyErr>(Py::new(py, RtspNotice::from(notice))?.into_any())
                })?)),
                Some(Err(error)) => Err(PyConnectionError::new_err(error.to_string())),
            }
        })
    }

    /// Stops the stream, closing the connection and ending `next` after any buffered chunks.
    fn close(&self) {
        self.stream.stop();
    }
}

/// A pending `next` holds its own reference to the stream, so a stream collected without
/// `close` stops here, or that read waits on a silent camera forever.
impl Drop for RtspStream {
    fn drop(&mut self) {
        self.stream.stop();
    }
}

/// A duration argument in seconds, refusing a negative or non-finite value.
fn seconds(name: &str, value: f64) -> PyResult<Duration> {
    Duration::try_from_secs_f64(value)
        .map_err(|_| PyValueError::new_err(format!("{name} must be a finite non-negative number")))
}
