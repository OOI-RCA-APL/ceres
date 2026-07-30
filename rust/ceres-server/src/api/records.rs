//! The record routes.
//!
//! Listings, counts, and single records serve through the host's record operations,
//! which validate the filter, execute through the engine's native fetch path, and hand
//! back the serialized payload. The route names, limits, and filter semantics all live
//! with the host, so every construct keeps its exact behavior.

use std::sync::Arc;

use axum::extract::{Path, RawQuery, Request, State};
use axum::http::HeaderMap;
use axum::response::{IntoResponse, Response};
use serde_json::{Value, json};

use crate::api::attempt;
use crate::app::{AppState, json_response};
use crate::auth::require_authenticated;
use crate::error::ApiError;

/// Serve a record listing, or stream live records when the caller upgrades.
///
/// The listing and the stream share this path, a socket being a GET that asks to
/// upgrade, exactly as they shared it in the Python application.
async fn list(state: &Arc<AppState>, table: &str, request: Request) -> Response {
    let (mut parts, _) = request.into_parts();
    let actor = attempt!(state.actor(&parts.headers).await);
    attempt!(require_authenticated(&actor));

    let query = parts.uri.query().map(str::to_string);
    let arguments = json!({"table": table, "query": crate::api::streams::query_pairs(query)});
    if let Some(upgrade) = crate::api::streams::requested_upgrade(&mut parts, state).await {
        return crate::api::streams::stream(state, upgrade, "records.stream", arguments);
    }

    match state.host.payload("records.list", arguments).await {
        Ok(payload) => json_response(payload),
        Err(error) => error.into_response(),
    }
}

/// Serve a record count.
async fn count(
    state: &AppState,
    headers: &HeaderMap,
    table: &str,
    query: Option<String>,
) -> Response {
    let actor = attempt!(state.actor(headers).await);
    attempt!(require_authenticated(&actor));

    let arguments = json!({"table": table, "query": crate::api::streams::query_pairs(query)});
    match state.host.payload("records.count", arguments).await {
        Ok(payload) => json_response(payload),
        Err(error) => error.into_response(),
    }
}

/// Serve one record by ID.
///
/// A path segment that does not parse as a UUID never matched the route in the Python
/// application, falling through to its catch-all, so it answers the same not-found.
async fn get(state: &AppState, headers: &HeaderMap, table: &str, id: &str) -> Response {
    if id.parse::<uuid::Uuid>().is_err() {
        return ApiError::not_found().into_response();
    }

    let actor = attempt!(state.actor(headers).await);
    attempt!(require_authenticated(&actor));

    match state
        .host
        .payload("records.get", json!({"table": table, "id": id}))
        .await
    {
        Ok(Value::Null) => ApiError::not_found().into_response(),
        Ok(payload) => json_response(payload),
        Err(error) => error.into_response(),
    }
}

/// Generate the three handlers for one record table.
macro_rules! record_routes {
    ($($module:ident => $table:literal;)*) => {
        $(pub(crate) mod $module {
            use super::*;

            pub(crate) async fn list(
                State(state): State<Arc<AppState>>,
                request: Request,
            ) -> Response {
                super::list(&state, $table, request).await
            }

            pub(crate) async fn count(
                State(state): State<Arc<AppState>>,
                headers: HeaderMap,
                RawQuery(query): RawQuery,
            ) -> Response {
                super::count(&state, &headers, $table, query).await
            }

            pub(crate) async fn get(
                State(state): State<Arc<AppState>>,
                headers: HeaderMap,
                Path(id): Path<String>,
            ) -> Response {
                super::get(&state, &headers, $table, &id).await
            }
        })*
    };
}

record_routes! {
    messages => "messages";
    particles => "particles";
    alerts => "alerts";
    logs => "logs";
}
