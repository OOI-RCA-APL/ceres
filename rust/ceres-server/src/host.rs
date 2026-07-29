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

/// The engine-side operations the server calls across the language boundary.
#[async_trait::async_trait]
pub trait Host: Send + Sync + 'static {
    /// Look up a user by ID, `None` when no such user exists.
    async fn user(&self, id: Uuid) -> Result<Option<UserRecord>, HostError>;
}

/// A host for applications that never cross the boundary, tests and stubs.
pub struct NoHost;

#[async_trait::async_trait]
impl Host for NoHost {
    async fn user(&self, _id: Uuid) -> Result<Option<UserRecord>, HostError> {
        Ok(None)
    }
}
