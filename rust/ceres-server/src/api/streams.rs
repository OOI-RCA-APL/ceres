//! The streaming routes.
//!
//! A stream gates before upgrading, so a refused caller sees an HTTP error rather than
//! an accepted socket, then pumps the engine's messages out as text frames until the
//! client leaves or the stream ends. Messages arrive already serialized, so a record the
//! engine rendered crosses the boundary once and forwards untouched.
//!
//! Record streams share their paths with the listings, a socket being a GET that asks to
//! upgrade, so those handlers take the upgrade optionally and branch on it.

use std::sync::Arc;

use axum::extract::ws::{CloseFrame, Message, WebSocket, WebSocketUpgrade};
use axum::extract::{FromRequestParts, RawQuery, Request, State};
use axum::http::request::Parts;
use axum::response::{IntoResponse, Response};
use axum_extra::routing::{RouterExt, TypedPath};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::api::attempt;
use crate::app::AppState;
use crate::auth::require_authenticated;
use crate::host::StreamClose;

/// Collect a raw query string into ordered pairs, percent-decoded.
pub(crate) fn query_pairs(query: Option<String>) -> Vec<(String, String)> {
    let Some(query) = query else {
        return Vec::new();
    };

    form_urlencoded::parse(query.as_bytes())
        .map(|(name, value)| (name.into_owned(), value.into_owned()))
        .collect()
}

/// Take the upgrade a request asks for, or `None` when it is a plain request.
///
/// Listings and streams share their paths, a socket being a GET that asks to upgrade,
/// so the handlers on those paths extract the upgrade themselves and branch on it
/// rather than declaring it as a required argument.
pub(crate) async fn requested_upgrade(
    parts: &mut Parts,
    state: &Arc<AppState>,
) -> Option<WebSocketUpgrade> {
    WebSocketUpgrade::from_request_parts(parts, state)
        .await
        .ok()
}

/// Upgrade and stream one engine operation.
pub(crate) fn stream(
    state: &Arc<AppState>,
    upgrade: WebSocketUpgrade,
    operation: &'static str,
    arguments: Value,
) -> Response {
    let state = state.clone();
    upgrade.on_upgrade(move |socket| pump(state, socket, operation, arguments))
}

/// Forward a stream's messages until the client leaves or the stream ends.
async fn pump(state: Arc<AppState>, mut socket: WebSocket, operation: &str, arguments: Value) {
    let handle = match state.host.stream_open(operation, arguments).await {
        Ok(handle) => handle,
        Err(close) => {
            send_close(&mut socket, close).await;
            return;
        }
    };

    loop {
        tokio::select! {
            // A client that leaves ends the stream, which is how a socket in send-only
            // use notices the peer is gone.
            incoming = socket.recv() => match incoming {
                None | Some(Err(_)) | Some(Ok(Message::Close(_))) => break,
                Some(Ok(_)) => continue,
            },
            message = state.host.stream_next(handle) => match message {
                Ok(Some(text)) => {
                    if socket.send(Message::Text(text.into())).await.is_err() {
                        break;
                    }
                }
                Ok(None) => break,
                Err(close) => {
                    send_close(&mut socket, close).await;
                    break;
                }
            },
        }
    }

    state.host.stream_close(handle).await;
}

/// Close a socket with the code and reason the engine reported.
async fn send_close(socket: &mut WebSocket, close: StreamClose) {
    let _ = socket
        .send(Message::Close(Some(CloseFrame {
            code: close.code,
            reason: close.reason.into(),
        })))
        .await;
}

/// Declare the socket-only streaming routes.
macro_rules! socket_routes {
    ($(
        $(#[$doc:meta])*
        $name:ident: $path:literal => $operation:literal, params($($field:ident => $host:literal),+);
    )*) => {
        $(
            $(#[$doc])*
            #[derive(TypedPath, Deserialize)]
            #[typed_path($path)]
            pub(crate) struct $name {
                $($field: String,)+
            }
        )*

        /// Register every socket-only route.
        pub(crate) fn register(router: axum::Router<Arc<AppState>>) -> axum::Router<Arc<AppState>> {
            $(let router = router.typed_get(
                |path: $name,
                 State(state): State<Arc<AppState>>,
                 RawQuery(query): RawQuery,
                 upgrade: WebSocketUpgrade| async move {
                    let arguments = json!({
                        "path": json!({$($host: path.$field),+}),
                        "query": query_pairs(query),
                    });
                    stream(&state, upgrade, $operation, arguments)
                },
            );)*

            router
        }
    };
}

socket_routes! {
    /// Stream one procedure's outputs, access checked by the operation.
    ProcedureSubscription: "/api/components/{address}/procedures/{name}/subscribe" =>
        "procedures.subscribe", params(address => "address", name => "name");
    /// Stream one query's outputs, access checked by the operation.
    QuerySubscription: "/api/components/{address}/queries/{name}/subscribe" =>
        "queries.subscribe", params(address => "address", name => "name");
}

/// Serve component statuses, as a listing or as a stream of snapshots.
pub(crate) async fn statuses(State(state): State<Arc<AppState>>, request: Request) -> Response {
    let (mut parts, _) = request.into_parts();
    let actor = attempt!(state.actor(&parts.headers).await);
    attempt!(require_authenticated(&actor));

    let query = parts.uri.query().map(str::to_string);
    let arguments = json!({"query": query_pairs(query)});
    match requested_upgrade(&mut parts, &state).await {
        Some(upgrade) => stream(&state, upgrade, "statuses.stream", arguments),
        None => match state.host.operate("statuses.list", arguments).await {
            Ok(payload) => crate::app::json_response(payload),
            Err(error) => error.into_response(),
        },
    }
}
