//! The host interface.
//!
//! The server owns HTTP, but the engine it serves lives on the other side of this
//! trait: user lookup and credentials now, component operations and entity access as
//! the port grows. The production host is the Python engine reached through the
//! extension module's bridge, tests use stubs, and the boundary is exactly the seam a
//! future non-Python host would implement.

use std::path::PathBuf;

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
/// A typed failure carries the status and serialized envelope the host produced, served
/// verbatim, anything else serves as a bare internal error like an unhandled exception
/// always has.
#[derive(Debug, thiserror::Error)]
pub enum HostError {
    #[error("the host reported a typed error")]
    Typed { status: u16, envelope: String },
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
                    envelope,
                )
                    .into_response()
            }
            Self::Internal(_) => {
                ApiError::new(StatusCode::INTERNAL_SERVER_ERROR, "error").into_response()
            }
        }
    }
}

/// A response the host described rather than serialized, whose body the server produces.
///
/// A procedure declaring a media type answers with one of these. The host decided every
/// header, including the content type and length, so the server sends them as they
/// arrive and only has to find the bytes.
pub struct Served {
    pub status: u16,
    /// The headers to send, in order, each name already lowercased by the host.
    pub headers: Vec<(String, String)>,
    /// The file to stream, or `None` when the body is the handle's chunks.
    pub file: Option<PathBuf>,
    /// The handle to release once the body ends, which runs the output's exit hook.
    pub handle: u64,
}

/// What an operation answered with.
pub enum Answer {
    /// A payload's verbatim JSON, which nearly every operation returns.
    ///
    /// The host already serialized it, so it flows into the response body untouched,
    /// a record dump never parses into a value tree on this side of the boundary.
    Payload(String),
    /// A body the server produces itself, which only a media output answers with.
    Served(Served),
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

/// A user's standing as the native gate reads it, no wire payload attached.
#[derive(Clone, Copy, Debug)]
pub struct GateUser {
    pub id: Uuid,
    pub admin: bool,
    pub disabled: bool,
}

/// The engine-side operations the server calls across the language boundary.
#[async_trait::async_trait]
pub trait Host: Send + Sync + 'static {
    /// Look up a user by ID, `None` when no such user exists.
    async fn user(&self, id: Uuid) -> Result<Option<UserRecord>, HostError>;

    /// Read a user's standing natively for an authentication gate.
    ///
    /// The outer `None` means this host has no native store and the caller falls back
    /// to the full `user` lookup. The inner `None` means no user carries the ID, which
    /// resolves to anonymous like every other token problem.
    async fn native_gate_user(&self, id: Uuid) -> Option<Option<GateUser>> {
        let _ = id;
        None
    }

    /// Serve a record listing natively from filter query pairs, as its response body.
    ///
    /// `None` delegates to the host operation, for an invalid filter whose canonical
    /// validation envelope the operation renders, a particle `class` filter, a host
    /// without a native store, or any native failure.
    async fn native_records(&self, table: &str, pairs: &[(String, String)]) -> Option<String> {
        let _ = (table, pairs);
        None
    }

    /// Count records natively from filter query pairs, as the count's JSON text.
    async fn native_record_count(&self, table: &str, pairs: &[(String, String)]) -> Option<String> {
        let _ = (table, pairs);
        None
    }

    /// Serve one record natively by ID, as its response body, `null` when absent.
    async fn native_record(&self, table: &str, id: Uuid) -> Option<String> {
        let _ = (table, id);
        None
    }

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

    /// Await the next chunk of a described response's body, `None` once it ends.
    ///
    /// Chunks arrive as raw bytes, so a body the host produces crosses without an
    /// encoding step of its own.
    async fn next_chunk(&self, handle: u64) -> Result<Option<Vec<u8>>, HostError> {
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
    /// its host, one name per route behavior, and the answer is what the route serves.
    async fn operate(&self, operation: &str, arguments: Value) -> Result<Answer, HostError> {
        let _ = arguments;
        Err(HostError::Internal(format!(
            "this host does not support the {operation:?} operation"
        )))
    }

    /// Run an operation that answers with a payload.
    ///
    /// Only the procedure call routes reach an operation that can describe a response,
    /// so every other route asks for the payload and treats a description as a failure
    /// of the host rather than carrying a branch that cannot be taken.
    async fn payload(&self, operation: &str, arguments: Value) -> Result<String, HostError> {
        match self.operate(operation, arguments).await? {
            Answer::Payload(payload) => Ok(payload),
            Answer::Served(_) => Err(HostError::Internal(format!(
                "the {operation:?} operation answered with a body of its own"
            ))),
        }
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
