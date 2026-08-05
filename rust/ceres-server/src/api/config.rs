//! The configuration routes.
//!
//! Sections serve through the host's generic operation call, which hands back the
//! section's serialized form, and credentials scrub natively before anything leaves.
//! The console section is deliberately open, the console reads it before login, while
//! everything else requires an administrator.

use std::sync::Arc;

use axum::extract::State;
use axum::http::HeaderMap;
use axum::response::Response;
use serde_json::json;

use crate::app::{AppState, Resolution, json_response};
use crate::auth::Gate;
use crate::error::ApiError;
use crate::scrub::scrub_json;

/// Serve one configuration section through the host, scrubbed.
async fn serve_section(state: &AppState, operation: &str) -> Result<Response, ApiError> {
    let payload = state.host.payload(operation, json!({})).await?;
    Ok(json_response(scrub_json(&payload)))
}

/// Generate the admin-gated section handlers.
macro_rules! sections {
    ($($name:ident => $operation:literal;)*) => {
        $(pub(crate) async fn $name(
            State(state): State<Arc<AppState>>,
            headers: HeaderMap,
        ) -> Result<Response, ApiError> {
            state.admit(&headers, Gate::Admin, Resolution::Full).await?;
            serve_section(&state, $operation).await
        })*
    };
}

sections! {
    full => "config";
    service => "config.service";
    server => "config.server";
    database => "config.database";
}

/// Serve the console section, which needs no credentials and no authentication.
pub(crate) async fn console(State(state): State<Arc<AppState>>) -> Result<Response, ApiError> {
    serve_section(&state, "config.console").await
}
