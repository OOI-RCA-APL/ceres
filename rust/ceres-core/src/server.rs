//! The native HTTP server bridge.
//!
//! Binds `ceres-server` into Python. A `NativeServer` binds eagerly at construction, so
//! the control server's ephemeral port is known before anything serves, and serves on
//! the shared tokio runtime as an awaitable. The engine crosses the boundary the other
//! way through the host object, whose async methods answer the server's `Host` calls
//! with one JSON envelope per result, `{"ok": ...}` carrying a user record or null,
//! `{"error": {"status", "envelope"}}` passing a typed error through verbatim, and
//! `{"response": ...}` describing a body the server produces itself.

use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use ceres_server::axum::Router;
use ceres_server::{
    Answer, AppConfig, AuthSettings, BoundServer, ConsolePaths, Host, HostError, Served, Stopper,
    StreamClose, UserRecord, apply_compression, apply_cors, build_router,
};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use serde_json::Value;
use serde_json::value::RawValue;
use uuid::Uuid;

/// The Python engine as the server's host.
///
/// Host coroutines await on the event loop captured when serving starts, carried here
/// because the server's own tasks run on tokio threads with no ambient loop.
struct PyHost {
    host: Py<PyAny>,
    locals: Arc<OnceLock<pyo3_async_runtimes::TaskLocals>>,
}

impl PyHost {
    /// Await one host method, answering with whatever it returned.
    ///
    /// Host coroutines run on the event loop captured when serving started, because the
    /// server's own tasks run on tokio threads with no ambient loop of their own.
    async fn await_call<A>(&self, method: &str, arguments: A) -> Result<Py<PyAny>, String>
    where
        A: for<'py> pyo3::call::PyCallArgs<'py> + Send,
    {
        let future = Python::attach(|py| {
            let locals = self.locals.get().ok_or_else(|| {
                PyRuntimeError::new_err("the host cannot answer before the server serves")
            })?;
            let coroutine = self.host.bind(py).call_method1(method, arguments)?;
            pyo3_async_runtimes::into_future_with_locals(locals, coroutine)
        })
        .map_err(|error| error.to_string())?;

        future.await.map_err(|error| error.to_string())
    }

    /// Await one host method, answering with the JSON envelope it returned.
    async fn call<A>(&self, method: &str, arguments: A) -> Result<String, String>
    where
        A: for<'py> pyo3::call::PyCallArgs<'py> + Send,
    {
        let result = self.await_call(method, arguments).await?;
        Python::attach(|py| result.extract::<String>(py)).map_err(|error| error.to_string())
    }
}

/// Call one host method returning a user record envelope.
macro_rules! host_call {
    ($self:ident, $method:literal, ($($argument:expr),*)) => {{
        let envelope = $self
            .call($method, ($($argument,)*))
            .await
            .map_err(HostError::Internal)?;
        Envelope::parse(&envelope)
            .map_err(HostError::Internal)?
            .into_user_record()
    }};
}

#[async_trait::async_trait]
impl Host for PyHost {
    async fn user(&self, id: Uuid) -> Result<Option<UserRecord>, HostError> {
        host_call!(self, "user", (id))
    }

    async fn verify_login(
        &self,
        username: String,
        password: String,
    ) -> Result<Option<UserRecord>, HostError> {
        host_call!(self, "verify_login", (username, password))
    }

    async fn change_password(
        &self,
        user: Uuid,
        old_password: String,
        new_password: String,
    ) -> Result<Option<UserRecord>, HostError> {
        host_call!(self, "change_password", (user, old_password, new_password))
    }

    async fn operate(&self, operation: &str, arguments: Value) -> Result<Answer, HostError> {
        let envelope = self
            .call("operate", (operation.to_string(), arguments.to_string()))
            .await
            .map_err(HostError::Internal)?;
        Envelope::parse(&envelope)
            .map_err(HostError::Internal)?
            .into_answer()
    }

    async fn next_chunk(&self, handle: u64) -> Result<Option<Vec<u8>>, HostError> {
        let chunk = self
            .await_call("next_chunk", (handle,))
            .await
            .map_err(HostError::Internal)?;
        Python::attach(|py| chunk.extract::<Option<Vec<u8>>>(py)).map_err(|error| {
            HostError::Internal(format!("the host answered with no chunk. {error}"))
        })
    }

    async fn stream_open(&self, operation: &str, arguments: Value) -> Result<u64, StreamClose> {
        let envelope = self
            .call(
                "stream_open",
                (operation.to_string(), arguments.to_string()),
            )
            .await
            .map_err(StreamClose::internal)?;
        match Envelope::parse(&envelope)
            .map_err(StreamClose::internal)?
            .into_stream_message()?
        {
            StreamMessage::Text(handle) => handle
                .parse()
                .map_err(|_| StreamClose::internal("the host returned no stream handle")),
            StreamMessage::End => Err(StreamClose::internal("the host opened no stream")),
        }
    }

    async fn stream_next(&self, handle: u64) -> Result<Option<String>, StreamClose> {
        let envelope = self
            .call("stream_next", (handle,))
            .await
            .map_err(StreamClose::internal)?;
        match Envelope::parse(&envelope)
            .map_err(StreamClose::internal)?
            .into_stream_message()?
        {
            StreamMessage::Text(message) => Ok(Some(message)),
            StreamMessage::End => Ok(None),
        }
    }

    async fn stream_close(&self, handle: u64) {
        let _ = self.call("stream_close", (handle,)).await;
    }
}

/// A host result envelope, its payloads borrowed verbatim from the serialized text.
///
/// One shape covers every host method. Operations answer with `ok`, `error`, or
/// `response`, and streams answer with `ok`, `message`, `end`, or `close`. Payload
/// slices stay raw, so a record dump the engine already serialized crosses into the
/// response body without ever parsing into a value tree here.
#[derive(serde::Deserialize)]
struct Envelope<'a> {
    #[serde(borrow)]
    ok: Option<&'a RawValue>,
    error: Option<TypedError<'a>>,
    response: Option<Described>,
    close: Option<Close>,
    end: Option<bool>,
    message: Option<String>,
}

/// The `error` member, a typed refusal's status and verbatim envelope.
#[derive(serde::Deserialize)]
struct TypedError<'a> {
    status: Option<u16>,
    #[serde(borrow)]
    envelope: Option<&'a RawValue>,
}

/// The `response` member, a body the server produces itself.
#[derive(serde::Deserialize)]
struct Described {
    status: Option<u16>,
    #[serde(default)]
    headers: Vec<(String, String)>,
    file: Option<std::path::PathBuf>,
    handle: u64,
}

/// The `close` member, why a stream refused to open or stopped early.
#[derive(serde::Deserialize)]
struct Close {
    code: Option<u16>,
    reason: Option<String>,
}

/// The `ok` member of a user lookup.
#[derive(serde::Deserialize)]
struct RecordFields {
    id: Uuid,
    #[serde(default)]
    admin: bool,
    #[serde(default)]
    disabled: bool,
    #[serde(default)]
    payload: Value,
}

/// What a stream envelope carried.
enum StreamMessage {
    Text(String),
    End,
}

impl<'a> Envelope<'a> {
    fn parse(envelope: &'a str) -> Result<Self, String> {
        serde_json::from_str(envelope)
            .map_err(|error| format!("unparseable host envelope. {error}"))
    }

    /// The typed error the envelope reports, when it reports one.
    fn typed_error(&self) -> Option<HostError> {
        let error = self.error.as_ref()?;
        Some(HostError::Typed {
            status: error.status.unwrap_or(500),
            envelope: error
                .envelope
                .map(|envelope| envelope.get().to_string())
                .unwrap_or_else(|| "null".to_string()),
        })
    }

    /// The answer an operation envelope carries.
    fn into_answer(self) -> Result<Answer, HostError> {
        if let Some(error) = self.typed_error() {
            return Err(error);
        }

        // A described response arrives in its own envelope member rather than inside
        // the payload, so data an operation returns can never be mistaken for one.
        if let Some(described) = self.response {
            return Ok(Answer::Served(Served {
                status: described.status.unwrap_or(200),
                headers: described.headers,
                file: described.file,
                handle: described.handle,
            }));
        }

        Ok(Answer::Payload(
            self.ok
                .map(|payload| payload.get().to_string())
                .unwrap_or_else(|| "null".to_string()),
        ))
    }

    /// The user record a lookup envelope carries, `None` when it names nobody.
    fn into_user_record(self) -> Result<Option<UserRecord>, HostError> {
        if let Some(error) = self.typed_error() {
            return Err(error);
        }

        let Some(record) = self.ok.filter(|record| record.get() != "null") else {
            return Ok(None);
        };
        let fields: RecordFields = serde_json::from_str(record.get())
            .map_err(|error| HostError::Internal(format!("malformed user record. {error}")))?;

        Ok(Some(UserRecord {
            id: fields.id,
            admin: fields.admin,
            disabled: fields.disabled,
            payload: fields.payload,
        }))
    }

    /// The message a stream envelope carries, its end, or the close it reported.
    fn into_stream_message(self) -> Result<StreamMessage, StreamClose> {
        if let Some(close) = self.close {
            return Err(StreamClose {
                code: close.code.unwrap_or(1011),
                reason: close.reason.unwrap_or_default(),
            });
        }

        if self.end.is_some() {
            return Ok(StreamMessage::End);
        }

        if let Some(message) = self.message {
            return Ok(StreamMessage::Text(message));
        }

        match self.ok {
            Some(payload) => Ok(StreamMessage::Text(payload.get().to_string())),
            None => Ok(StreamMessage::End),
        }
    }
}

/// Serve the OpenAPI document describing the API, as JSON text.
#[pyo3_stub_gen::derive::gen_stub_pyfunction]
#[pyfunction]
pub fn openapi_schema(version: &str) -> PyResult<String> {
    ceres_server::openapi_document(version)
        .to_json()
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

/// A natively-served HTTP application.
///
/// Binds at construction, so the real port is known immediately, and serves as an
/// awaitable until stopped. The web form carries the console and terminates TLS, the
/// CLI form binds loopback on an ephemeral port and requires its token instead.
#[gen_stub_pyclass]
#[pyclass(module = "ceres_core", frozen)]
pub struct NativeServer {
    state: Mutex<Option<(BoundServer, Router)>>,
    stopper: Stopper,
    port: u16,
    locals: Arc<OnceLock<pyo3_async_runtimes::TaskLocals>>,
}

impl NativeServer {
    fn build(
        host: Py<PyAny>,
        config: &ceres_config::ServerConfig,
        bind: &str,
        port: u16,
        console: Option<ConsolePaths>,
        cli_token: Option<String>,
        with_tls: bool,
    ) -> PyResult<Self> {
        let auth = config
            .authentication
            .as_ref()
            .map(|authentication| -> PyResult<AuthSettings> {
                let duration = chrono::TimeDelta::from_std(authentication.duration.duration())
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
                Ok(AuthSettings::new(
                    &authentication.secret,
                    duration,
                    authentication.allow_impersonate,
                ))
            })
            .transpose()?;

        let locals = Arc::new(OnceLock::new());
        let router = build_router(AppConfig {
            console,
            cli_token,
            version: env!("CARGO_PKG_VERSION").to_string(),
            auth,
            host: Arc::new(PyHost {
                host,
                locals: locals.clone(),
            }),
        });

        // The layer added last sits outermost, so compression applies first to put the
        // cross-origin headers outside it, the order the Python application used.
        let router = apply_compression(router, config.compression.as_ref());
        let router = apply_cors(router, config.cors.as_ref());

        let mut server = BoundServer::bind(bind, port)
            .map_err(|error| PyValueError::new_err(error.to_string()))?;
        if with_tls && let Some(ssl) = config.ssl.as_ref() {
            server = server
                .with_tls(ssl)
                .map_err(|error| PyValueError::new_err(error.to_string()))?;
        }

        let stopper = server.stopper();
        let port = server.port();
        Ok(Self {
            state: Mutex::new(Some((server, router))),
            stopper,
            port,
            locals,
        })
    }
}

#[gen_stub_pymethods]
#[pymethods]
impl NativeServer {
    /// Bind the web application, serving the console and API on the configured address.
    #[staticmethod]
    #[pyo3(signature = (host, config, console_directory, favicon_ico, favicon_png, favicon_svg))]
    fn web(
        #[gen_stub(override_type(type_repr = "typing.Any"))] host: Py<PyAny>,
        config: &crate::ServerConfig,
        console_directory: std::path::PathBuf,
        favicon_ico: std::path::PathBuf,
        favicon_png: std::path::PathBuf,
        favicon_svg: std::path::PathBuf,
    ) -> PyResult<Self> {
        let config = &config.inner;
        let port = config
            .port
            .ok_or_else(|| PyValueError::new_err("the server port is not configured"))?;
        Self::build(
            host,
            config,
            &config.host,
            port,
            Some(ConsolePaths {
                directory: console_directory,
                favicon_ico,
                favicon_png,
                favicon_svg,
            }),
            None,
            true,
        )
    }

    /// Bind the CLI control application on an ephemeral loopback port.
    #[staticmethod]
    fn cli(
        #[gen_stub(override_type(type_repr = "typing.Any"))] host: Py<PyAny>,
        config: &crate::ServerConfig,
        token: String,
    ) -> PyResult<Self> {
        Self::build(
            host,
            &config.inner,
            "127.0.0.1",
            0,
            None,
            Some(token),
            false,
        )
    }

    /// The port the server actually bound.
    #[getter]
    fn port(&self) -> u16 {
        self.port
    }

    /// Serve until stopped, as an awaitable.
    fn serve<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        // The host's coroutines run on the loop this call arrives on.
        let _ = self
            .locals
            .set(pyo3_async_runtimes::tokio::get_current_locals(py)?);
        let (server, router) = self
            .state
            .lock()
            .expect("the server state mutex cannot poison")
            .take()
            .ok_or_else(|| PyRuntimeError::new_err("the server is already serving"))?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            server
                .serve(router)
                .await
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))
        })
    }

    /// Stop the server, letting in-flight requests finish within the grace period.
    #[pyo3(signature = (grace = 5.0))]
    fn stop(&self, grace: f64) {
        self.stopper.stop(Duration::from_secs_f64(grace));
    }
}
