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
use serde_json::json;

use crate::api::{attempt, query_pairs};
use crate::app::AppState;
use crate::host::StreamClose;

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

impl AppState {
    /// Upgrade and stream one engine operation.
    pub(crate) fn stream(
        self: &Arc<Self>,
        upgrade: WebSocketUpgrade,
        operation: &'static str,
        arguments: serde_json::Value,
    ) -> Response {
        let state = self.clone();
        upgrade.on_upgrade(move |socket| state.pump(socket, operation, arguments))
    }

    /// Forward a stream's messages until the client leaves or the stream ends.
    async fn pump(
        self: Arc<Self>,
        mut socket: WebSocket,
        operation: &str,
        arguments: serde_json::Value,
    ) {
        let handle = match self.host.stream_open(operation, arguments).await {
            Ok(handle) => handle,
            Err(close) => {
                close.send(&mut socket).await;
                return;
            }
        };

        loop {
            tokio::select! {
                // A client that leaves ends the stream, which is how a socket in
                // send-only use notices the peer is gone.
                incoming = socket.recv() => match incoming {
                    None | Some(Err(_)) | Some(Ok(Message::Close(_))) => break,
                    Some(Ok(_)) => continue,
                },
                message = self.host.stream_next(handle) => match message {
                    Ok(Some(text)) => {
                        if socket.send(Message::Text(text.into())).await.is_err() {
                            break;
                        }
                    }
                    Ok(None) => break,
                    Err(close) => {
                        close.send(&mut socket).await;
                        break;
                    }
                },
            }
        }

        self.host.stream_close(handle).await;
    }
}

impl StreamClose {
    /// Close a socket with the code and reason the engine reported.
    async fn send(self, socket: &mut WebSocket) {
        let _ = socket
            .send(Message::Close(Some(CloseFrame {
                code: self.code,
                reason: self.reason.into(),
            })))
            .await;
    }
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

        /// Describe every socket-only route for the OpenAPI document.
        pub(crate) fn documented() -> Vec<crate::api::schema::Documented> {
            vec![$(crate::api::schema::Documented {
                method: utoipa::openapi::HttpMethod::Get,
                path: $path,
                summary: $operation,
                parameters: &[$(stringify!($field)),+],
                secured: false,
                tag: $operation.split('.').next().unwrap_or($operation),
            }),*]
        }

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
                    state.stream(upgrade, $operation, arguments)
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
    attempt!(actor.require_authenticated());

    let query = parts.uri.query().map(str::to_string);
    let arguments = json!({"query": query_pairs(query)});
    match requested_upgrade(&mut parts, &state).await {
        Some(upgrade) => state.stream(upgrade, "statuses.stream", arguments),
        None => match state.host.payload("statuses.list", arguments).await {
            Ok(payload) => crate::app::json_response(payload),
            Err(error) => error.into_response(),
        },
    }
}
