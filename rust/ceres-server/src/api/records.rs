//! The record routes.
//!
//! Listings, counts, and single records serve through the host's record operations,
//! which validate the filter, execute through the engine's native fetch path, and hand
//! back the serialized payload. The route names, limits, and filter semantics all live
//! with the host so every construct keeps its exact behavior.

use std::sync::Arc;

use axum::extract::{Path, RawQuery, Request, State};
use axum::http::HeaderMap;
use axum::response::Response;
use serde_json::json;

use crate::api::query_pairs;
use crate::app::{AppState, Resolution, json_response};
use crate::auth::Gate;
use crate::error::ApiError;

/// Invoke a macro once with every record table, as `module => "name"` rows.
///
/// The one list feeds the handler modules here, the route registrations in the
/// application router, and the documented routes so the tables cannot drift apart.
macro_rules! for_each_record_table {
    ($callback:ident) => {
        $callback! {
            messages => "messages";
            particles => "particles";
            alerts => "alerts";
            logs => "logs";
        }
    };
}

pub(crate) use for_each_record_table;

/// Serve a record listing, or stream live records when the caller upgrades.
///
/// The listing and the stream share this path, a socket being a GET that asks to
/// upgrade, which is the wire contract's shape for them.
async fn list(state: &Arc<AppState>, table: &str, request: Request) -> Result<Response, ApiError> {
    let (mut parts, _) = request.into_parts();
    state
        .admit(&parts.headers, Gate::Authenticated, Resolution::Standing)
        .await?;

    let query = parts.uri.query().map(str::to_string);
    let pairs = query_pairs(query);
    if let Some(upgrade) = crate::api::streams::requested_upgrade(&mut parts, state).await {
        let arguments = json!({"table": table, "query": pairs});
        return Ok(state.stream(upgrade, "records.stream", arguments));
    }

    // The native path serves the filters it proves it can, everything else crosses to
    // the host operation, which answers or produces the canonical error.
    if let Some(payload) = state.host.native_records(table, &pairs).await {
        return Ok(json_response(payload));
    }

    let arguments = json!({"table": table, "query": pairs});
    let payload = state.host.payload("records.list", arguments).await?;
    Ok(json_response(payload))
}

/// Serve a record count.
async fn count(
    state: &AppState,
    headers: &HeaderMap,
    table: &str,
    query: Option<String>,
) -> Result<Response, ApiError> {
    state
        .admit(headers, Gate::Authenticated, Resolution::Standing)
        .await?;

    let pairs = query_pairs(query);
    if let Some(payload) = state.host.native_record_count(table, &pairs).await {
        return Ok(json_response(payload));
    }

    let arguments = json!({"table": table, "query": pairs});
    let payload = state.host.payload("records.count", arguments).await?;
    Ok(json_response(payload))
}

/// Serve one record by ID.
///
/// A path segment that does not parse as a UUID means the route never matched so it
/// answers the contract's plain not-found.
async fn get(
    state: &AppState,
    headers: &HeaderMap,
    table: &str,
    id: &str,
) -> Result<Response, ApiError> {
    let Ok(record) = id.parse::<uuid::Uuid>() else {
        return Err(ApiError::not_found());
    };

    state
        .admit(headers, Gate::Authenticated, Resolution::Standing)
        .await?;

    if let Some(payload) = state.host.native_record(table, record).await {
        if payload == "null" {
            return Err(ApiError::not_found());
        }

        return Ok(json_response(payload));
    }

    let payload = state
        .host
        .payload("records.get", json!({"table": table, "id": id}))
        .await?;
    if payload == "null" {
        return Err(ApiError::not_found());
    }

    Ok(json_response(payload))
}

/// Generate the three handlers for one record table.
macro_rules! record_routes {
    ($($module:ident => $table:literal;)*) => {
        $(pub(crate) mod $module {
            use super::*;

            pub(crate) async fn list(
                State(state): State<Arc<AppState>>,
                request: Request,
            ) -> Result<Response, ApiError> {
                super::list(&state, $table, request).await
            }

            pub(crate) async fn count(
                State(state): State<Arc<AppState>>,
                headers: HeaderMap,
                RawQuery(query): RawQuery,
            ) -> Result<Response, ApiError> {
                super::count(&state, &headers, $table, query).await
            }

            pub(crate) async fn get(
                State(state): State<Arc<AppState>>,
                headers: HeaderMap,
                Path(id): Path<String>,
            ) -> Result<Response, ApiError> {
                super::get(&state, &headers, $table, &id).await
            }
        })*
    };
}

for_each_record_table!(record_routes);
