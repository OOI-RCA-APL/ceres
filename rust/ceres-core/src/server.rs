//! The native HTTP server bridge.
//!
//! Binds `ceres-server` into Python. A `NativeServer` binds eagerly at construction, so
//! the control server's ephemeral port is known before anything serves, and serves on
//! the shared tokio runtime as an awaitable. The engine crosses the boundary the other
//! way through the host object, whose async methods answer the server's `Host` calls
//! with one JSON envelope per result, `{"ok": ...}` carrying a user record or null, and
//! `{"error": {"status", "envelope"}}` passing a typed error through verbatim.

use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use ceres_server::axum::Router;
use ceres_server::{
    AppConfig, AuthSettings, BoundServer, ConsolePaths, Host, HostError, Stopper, UserRecord,
    apply_compression, apply_cors, build_router,
};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3_stub_gen::derive::{gen_stub_pyclass, gen_stub_pymethods};
use serde_json::Value;
use uuid::Uuid;

/// The Python engine as the server's host.
///
/// Host coroutines await on the event loop captured when serving starts, carried here
/// because the server's own tasks run on tokio threads with no ambient loop.
struct PyHost {
    host: Py<PyAny>,
    locals: Arc<OnceLock<pyo3_async_runtimes::TaskLocals>>,
}

/// Call one host method with the given arguments, awaiting its JSON envelope.
macro_rules! host_call {
    ($self:ident, $method:literal, ($($argument:expr),*)) => {{
        let future = Python::attach(|py| {
            let locals = $self.locals.get().ok_or_else(|| {
                PyRuntimeError::new_err("the host cannot answer before the server serves")
            })?;
            let coroutine = $self
                .host
                .bind(py)
                .call_method1($method, ($($argument,)*))?;
            pyo3_async_runtimes::into_future_with_locals(locals, coroutine)
        })
        .map_err(|error| HostError::Internal(error.to_string()))?;

        let result = future
            .await
            .map_err(|error| HostError::Internal(error.to_string()))?;
        let envelope: String = Python::attach(|py| result.extract::<String>(py))
            .map_err(|error| HostError::Internal(error.to_string()))?;
        parse_envelope(&envelope)
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

    async fn operate(&self, operation: &str, arguments: Value) -> Result<Value, HostError> {
        let arguments = arguments.to_string();
        let future = Python::attach(|py| {
            let locals = self.locals.get().ok_or_else(|| {
                PyRuntimeError::new_err("the host cannot answer before the server serves")
            })?;
            let coroutine = self
                .host
                .bind(py)
                .call_method1("operate", (operation, arguments))?;
            pyo3_async_runtimes::into_future_with_locals(locals, coroutine)
        })
        .map_err(|error| HostError::Internal(error.to_string()))?;

        let result = future
            .await
            .map_err(|error| HostError::Internal(error.to_string()))?;
        let envelope: String = Python::attach(|py| result.extract::<String>(py))
            .map_err(|error| HostError::Internal(error.to_string()))?;
        parse_value_envelope(&envelope)
    }
}

/// Parse a host result envelope into its payload or a typed error.
fn parse_value_envelope(envelope: &str) -> Result<Value, HostError> {
    let value: Value = serde_json::from_str(envelope)
        .map_err(|error| HostError::Internal(format!("unparseable host envelope. {error}")))?;

    if let Some(error) = value.get("error") {
        let status = error.get("status").and_then(Value::as_u64).unwrap_or(500);
        let envelope = error.get("envelope").cloned().unwrap_or(Value::Null);
        return Err(HostError::Typed {
            status: u16::try_from(status).unwrap_or(500),
            envelope,
        });
    }

    Ok(value.get("ok").cloned().unwrap_or(Value::Null))
}

/// Parse a host result envelope into a user record, absence, or a typed error.
fn parse_envelope(envelope: &str) -> Result<Option<UserRecord>, HostError> {
    let value: Value = serde_json::from_str(envelope)
        .map_err(|error| HostError::Internal(format!("unparseable host envelope. {error}")))?;

    if let Some(error) = value.get("error") {
        let status = error.get("status").and_then(Value::as_u64).unwrap_or(500);
        let envelope = error.get("envelope").cloned().unwrap_or(Value::Null);
        return Err(HostError::Typed {
            status: u16::try_from(status).unwrap_or(500),
            envelope,
        });
    }

    match value.get("ok") {
        None | Some(Value::Null) => Ok(None),
        Some(record) => {
            let id = record
                .get("id")
                .and_then(Value::as_str)
                .and_then(|text| text.parse().ok())
                .ok_or_else(|| {
                    HostError::Internal("the host's user record carries no ID".to_string())
                })?;
            Ok(Some(UserRecord {
                id,
                admin: record
                    .get("admin")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                disabled: record
                    .get("disabled")
                    .and_then(Value::as_bool)
                    .unwrap_or(false),
                payload: record.get("payload").cloned().unwrap_or(Value::Null),
            }))
        }
    }
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
                Ok(AuthSettings {
                    secret: authentication.secret.clone(),
                    duration: chrono::TimeDelta::from_std(authentication.duration.duration())
                        .map_err(|error| PyValueError::new_err(error.to_string()))?,
                    allow_impersonate: authentication.allow_impersonate,
                })
            })
            .transpose()?;

        let locals = Arc::new(OnceLock::new());
        let router = build_router(AppConfig {
            console,
            cli_token,
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
