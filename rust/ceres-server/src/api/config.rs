//! The configuration routes.
//!
//! Sections serve through the host's generic operation call, which hands back the
//! section's serialized form, and credentials scrub natively before anything leaves.
//! The console section is deliberately open, the console reads it before login, while
//! everything else requires an administrator.

use std::sync::Arc;

use axum::extract::State;
use axum::http::HeaderMap;
use axum::response::{IntoResponse, Response};
use serde_json::json;

use crate::api::attempt;
use crate::app::{AppState, json_response};
use crate::scrub::scrub_json;

/// Serve one configuration section through the host, scrubbed.
async fn serve_section(state: &AppState, operation: &str) -> Response {
    match state.host.payload(operation, json!({})).await {
        Ok(payload) => json_response(scrub_json(&payload)),
        Err(error) => error.into_response(),
    }
}

/// Generate the admin-gated section handlers.
macro_rules! sections {
    ($($name:ident => $operation:literal;)*) => {
        $(pub(crate) async fn $name(
            State(state): State<Arc<AppState>>,
            headers: HeaderMap,
        ) -> Response {
            let actor = attempt!(state.actor(&headers).await);
            attempt!(actor.require_admin());
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
pub(crate) async fn console(State(state): State<Arc<AppState>>) -> Response {
    serve_section(&state, "config.console").await
}
