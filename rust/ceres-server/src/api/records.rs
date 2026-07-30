//! The record routes.
//!
//! Listings, counts, and single records serve through the host's record operations,
//! which validate the filter, execute through the engine's native fetch path, and hand
//! back the serialized payload. The route names, limits, and filter semantics all live
//! with the host, so every construct keeps its exact behavior.

use std::sync::Arc;

use axum::extract::{Path, RawQuery, State};
use axum::http::HeaderMap;
use axum::response::{IntoResponse, Response};
use serde_json::{Value, json};

use crate::api::attempt;
use crate::app::{AppState, json_response};
use crate::auth::require_authenticated;
use crate::error::ApiError;

/// Split a raw query string into ordered pairs, percent-decoded.
///
/// Order and repetition both matter to filter validation, so the pairs pass through as
/// a list rather than a map.
fn query_pairs(query: Option<String>) -> Vec<(String, String)> {
    let Some(query) = query else {
        return Vec::new();
    };

    form_urlencoded::parse(query.as_bytes())
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect()
}

/// Serve a record listing.
async fn list(
    state: &AppState,
    headers: &HeaderMap,
    table: &str,
    query: Option<String>,
) -> Response {
    let actor = attempt!(state.actor(headers).await);
    attempt!(require_authenticated(&actor));

    let arguments = json!({"table": table, "query": query_pairs(query)});
    match state.host.operate("records.list", arguments).await {
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

    let arguments = json!({"table": table, "query": query_pairs(query)});
    match state.host.operate("records.count", arguments).await {
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
        .operate("records.get", json!({"table": table, "id": id}))
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
                headers: HeaderMap,
                RawQuery(query): RawQuery,
            ) -> Response {
                super::list(&state, &headers, $table, query).await
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
