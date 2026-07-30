//! Router assembly.
//!
//! The same application serves two roles, matching the Python layer. The web app carries
//! the console's static files and favicons. The CLI control app carries neither and
//! instead requires its per-run token on every request, granting whoever holds it
//! unrestricted access.

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Redirect, Response};
use axum::routing::{get, post};
use subtle::ConstantTimeEq;
use tower::ServiceExt;
use tower_http::services::{ServeDir, ServeFile};

use crate::auth::{self, AuthSettings};
use crate::error::ApiError;
use crate::host::Host;

/// What an application instance serves.
pub struct AppConfig {
    /// The console's static files, absent on the CLI control app.
    pub console: Option<ConsolePaths>,
    /// The token every request must carry, set on the CLI control app.
    pub cli_token: Option<String>,
    /// The authentication settings, `None` when authentication is disabled.
    pub auth: Option<AuthSettings>,
    /// The engine on the other side of the language boundary.
    pub host: Arc<dyn Host>,
}

/// Where the console's assets live.
pub struct ConsolePaths {
    /// Directory of built console assets, served at the root with an index fallback.
    pub directory: PathBuf,
    /// Favicon files by suffix, already resolved against any configured override.
    pub favicon_ico: PathBuf,
    pub favicon_png: PathBuf,
    pub favicon_svg: PathBuf,
}

pub(crate) struct AppState {
    console: Option<ConsolePaths>,
    pub(crate) auth: Option<AuthSettings>,
    pub(crate) host: Arc<dyn Host>,
    cli: bool,
}

impl AppState {
    /// Resolve the identity a request presents, anonymous on any failure.
    pub(crate) async fn identity(
        &self,
        headers: &HeaderMap,
    ) -> Result<Option<auth::Identity>, crate::host::HostError> {
        auth::current_identity(self.auth.as_ref(), self.host.as_ref(), headers).await
    }

    /// Resolve the actor a request comes from.
    pub(crate) async fn actor(
        &self,
        headers: &HeaderMap,
    ) -> Result<auth::Actor, crate::host::HostError> {
        auth::current_actor(self.auth.as_ref(), self.cli, self.host.as_ref(), headers).await
    }
}

/// Respond with a JSON value.
pub(crate) fn json_response(value: serde_json::Value) -> Response {
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/json")],
        value.to_string(),
    )
        .into_response()
}

/// Generate a favicon handler per suffix, serving the resolved file with its media type.
macro_rules! favicons {
    ($($name:ident: $field:ident => $media:literal;)*) => {
        $(async fn $name(State(state): State<Arc<AppState>>) -> Response {
            favicon(&state, |console| &console.$field, $media)
        })*
    };
}

favicons! {
    serve_favicon_ico: favicon_ico => "image/x-icon";
    serve_favicon_png: favicon_png => "image/png";
    serve_favicon_svg: favicon_svg => "image/svg+xml";
}

/// Build the application router.
pub fn build_router(config: AppConfig) -> Router {
    let state = Arc::new(AppState {
        console: config.console,
        auth: config.auth,
        host: config.host,
        cli: config.cli_token.is_some(),
    });

    // The API catch-all handles GET only, like the Python layer's. A matched path with
    // the wrong method answers 405 in the bare envelope, and everything else falls
    // through to the console files or, without them, a bare 404.
    let mut router = Router::new()
        .route("/api/alive", get(alive))
        .route("/api", get(redirect_to_openapi))
        .route("/api/auth/me", get(crate::api::auth::me))
        .route("/api/auth/features", get(crate::api::auth::features))
        .route("/api/auth/login", post(crate::api::auth::login))
        .route("/api/auth/refresh", post(crate::api::auth::refresh))
        .route("/api/auth/logout", post(crate::api::auth::logout))
        .route("/api/auth/impersonate", post(crate::api::auth::impersonate))
        .route(
            "/api/auth/change-password",
            post(crate::api::auth::change_password),
        )
        .route("/api/config", get(crate::api::config::full))
        .route("/api/config/service", get(crate::api::config::service))
        .route("/api/config/server", get(crate::api::config::server))
        .route("/api/config/database", get(crate::api::config::database))
        .route("/api/config/console", get(crate::api::config::console))
        .route("/api/{*path}", get(api_not_found));
    router = record_routes(router);
    router = crate::api::dispatch::register(router);

    if state.console.is_some() {
        router = router
            .route("/favicon.ico", get(serve_favicon_ico))
            .route("/favicon.png", get(serve_favicon_png))
            .route("/favicon.svg", get(serve_favicon_svg))
            .fallback(serve_console);
    } else {
        router = router.fallback(plain_not_found);
    }

    let mut router = router
        .method_not_allowed_fallback(method_not_allowed)
        .with_state(state);

    if let Some(token) = config.cli_token {
        let token: Arc<str> = token.into();
        router = router.layer(middleware::from_fn(move |request: Request, next: Next| {
            let token = token.clone();
            async move { require_cli_token(&token, request, next).await }
        }));
    }

    router
}

async fn alive() -> StatusCode {
    StatusCode::OK
}

/// Register the three routes of every record table.
fn record_routes(router: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    macro_rules! tables {
        ($router:ident, $($module:ident => $name:literal;)*) => {
            $(let $router = $router
                .route(concat!("/api/", $name), get(crate::api::records::$module::list))
                .route(
                    concat!("/api/", $name, "/count"),
                    get(crate::api::records::$module::count),
                )
                .route(
                    concat!("/api/", $name, "/{id}"),
                    get(crate::api::records::$module::get),
                );)*
            $router
        };
    }

    tables! {
        router,
        messages => "messages";
        particles => "particles";
        alerts => "alerts";
        logs => "logs";
    }
}

async fn redirect_to_openapi() -> Redirect {
    Redirect::temporary("/api/openapi.json")
}

async fn api_not_found() -> ApiError {
    ApiError::not_found()
}

async fn method_not_allowed() -> ApiError {
    ApiError::http(StatusCode::METHOD_NOT_ALLOWED)
}

/// The fallback for paths outside the API on an app with no console, answering with the
/// bare HTTP envelope like an unrouted path always has.
async fn plain_not_found() -> ApiError {
    ApiError::http(StatusCode::NOT_FOUND)
}

/// Require the control app's token on every request, compared in constant time.
async fn require_cli_token(token: &str, request: Request, next: Next) -> Response {
    let provided = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok());
    let valid = provided.is_some_and(|provided| provided.as_bytes().ct_eq(token.as_bytes()).into());
    if !valid {
        return ApiError::not_authenticated().into_response();
    }

    next.run(request).await
}

/// Serve the console's static files, falling back to the index for unmatched paths.
///
/// The index fallback is what lets the single-page console own its routes. Error
/// responses from the file service convert to the bare HTTP envelope, matching how the
/// Python layer translates its static mount's exceptions.
async fn serve_console(State(state): State<Arc<AppState>>, request: Request) -> Response {
    let console = state
        .console
        .as_ref()
        .expect("the console fallback only routes when console paths exist");
    let service = ServeDir::new(&console.directory)
        .fallback(ServeFile::new(console.directory.join("index.html")));

    match service.oneshot(request).await {
        Ok(response) if response.status().is_success() || response.status().is_redirection() => {
            response.into_response()
        }
        Ok(response) => ApiError::http(response.status()).into_response(),
        Err(error) => match error {},
    }
}

fn favicon(
    state: &AppState,
    path: impl Fn(&ConsolePaths) -> &PathBuf,
    media_type: &'static str,
) -> Response {
    let Some(console) = state.console.as_ref() else {
        return ApiError::http(StatusCode::NOT_FOUND).into_response();
    };

    match std::fs::read(path(console)) {
        Ok(bytes) => (StatusCode::OK, [(header::CONTENT_TYPE, media_type)], bytes).into_response(),
        Err(_) => ApiError::http(StatusCode::NOT_FOUND).into_response(),
    }
}
