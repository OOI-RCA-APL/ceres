//! The host interface.
//!
//! The server owns HTTP, but the engine it serves lives on the other side of this
//! trait: user lookup and credentials now, component operations and entity access as
//! the port grows. The production host is the Python engine reached through the
//! extension module's bridge, tests use stubs, and the boundary is exactly the seam a
//! future non-Python host would implement.

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde_json::Value;
use uuid::Uuid;

use crate::error::ApiError;

/// A user as the host reports it, enough for the actor gates plus its wire form.
pub struct UserRecord {
    pub id: Uuid,
    pub admin: bool,
    pub disabled: bool,
    /// The user's serialized wire form, password fields already excluded.
    pub payload: Value,
}

/// A failure crossing the host boundary.
///
/// A typed failure carries the status and envelope the host produced, anything else
/// serves as a bare internal error like an unhandled exception always has.
#[derive(Debug, thiserror::Error)]
pub enum HostError {
    #[error("the host reported a typed error")]
    Typed { status: u16, envelope: Value },
    #[error("{0}")]
    Internal(String),
}

impl IntoResponse for HostError {
    fn into_response(self) -> Response {
        match self {
            Self::Typed { status, envelope } => {
                let status =
                    StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
                (
                    status,
                    [(axum::http::header::CONTENT_TYPE, "application/json")],
                    envelope.to_string(),
                )
                    .into_response()
            }
            Self::Internal(_) => {
                ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "error").into_response()
            }
        }
    }
}

/// Why a stream refused to open or stopped early.
#[derive(Debug)]
pub struct StreamClose {
    /// The WebSocket close code the socket reports.
    pub code: u16,
    /// The close reason, a serialized error for the codes that carry one.
    pub reason: String,
}

impl StreamClose {
    /// A refusal the engine did not attribute, reported as an internal error.
    pub fn internal(reason: impl Into<String>) -> Self {
        Self {
            code: 1011,
            reason: reason.into(),
        }
    }
}

/// The engine-side operations the server calls across the language boundary.
#[async_trait::async_trait]
pub trait Host: Send + Sync + 'static {
    /// Look up a user by ID, `None` when no such user exists.
    async fn user(&self, id: Uuid) -> Result<Option<UserRecord>, HostError>;

    /// Check a username and password, returning the user when they match.
    async fn verify_login(
        &self,
        username: String,
        password: String,
    ) -> Result<Option<UserRecord>, HostError>;

    /// Change a user's password, `None` when the old password does not match.
    ///
    /// The host validates the new password's shape, reporting refusals as typed
    /// errors.
    async fn change_password(
        &self,
        user: Uuid,
        old_password: String,
        new_password: String,
    ) -> Result<Option<UserRecord>, HostError>;

    /// Open a stream, answering with the handle its messages arrive under.
    ///
    /// A refusal carries the close code the socket reports, so the policy for which
    /// failure closes with which code stays with the engine.
    async fn stream_open(&self, operation: &str, arguments: Value) -> Result<u64, StreamClose> {
        let _ = arguments;
        Err(StreamClose::internal(format!(
            "this host does not stream {operation:?}"
        )))
    }

    /// Await the next message on a stream, `None` once it ends.
    ///
    /// Messages arrive pre-serialized, so a record the engine already rendered crosses
    /// the boundary once as text.
    async fn stream_next(&self, handle: u64) -> Result<Option<String>, StreamClose> {
        let _ = handle;
        Ok(None)
    }

    /// Release a stream's resources, whatever ended it.
    async fn stream_close(&self, handle: u64) {
        let _ = handle;
    }

    /// Run a named engine operation, the generic channel most route families ride.
    ///
    /// The operation names and argument shapes form the contract between the server and
    /// its host, one name per route behavior, and the result is the payload the route
    /// serves.
    async fn operate(&self, operation: &str, arguments: Value) -> Result<Value, HostError> {
        let _ = arguments;
        Err(HostError::Internal(format!(
            "this host does not support the {operation:?} operation"
        )))
    }
}

/// A host for applications that never cross the boundary, tests and stubs.
pub struct NoHost;

#[async_trait::async_trait]
impl Host for NoHost {
    async fn user(&self, _id: Uuid) -> Result<Option<UserRecord>, HostError> {
        Ok(None)
    }

    async fn verify_login(
        &self,
        _username: String,
        _password: String,
    ) -> Result<Option<UserRecord>, HostError> {
        Ok(None)
    }

    async fn change_password(
        &self,
        _user: Uuid,
        _old_password: String,
        _new_password: String,
    ) -> Result<Option<UserRecord>, HostError> {
        Ok(None)
    }
}
