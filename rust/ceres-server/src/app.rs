//! Router assembly.
//!
//! The same application serves two roles. The web app carries
//! the console's static files and favicons. The CLI control app carries neither and
//! instead requires its per-run token on every request, granting whoever holds it
//! unrestricted access.
//!
//! Everything a request needs repeatedly is prepared once at build time and held on the
//! state, the OpenAPI document's JSON, the favicon bytes, and the console file service
//! so serving them is a lookup rather than work.

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;
use axum::body::Bytes;
use axum::extract::{Request, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Redirect, Response};
use axum::routing::{get, post};
use serde_json::Value;
use subtle::ConstantTimeEq;
use tower::ServiceExt;
use tower_http::services::{ServeDir, ServeFile};

use crate::auth::{Actor, AuthSettings, Gate, Identity};
use crate::error::ApiError;
use crate::host::{Host, HostError, UserRecord};

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
    /// The package version the OpenAPI document reports.
    pub version: String,
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

/// The console, its file service and favicons prepared once.
struct Console {
    /// The static file service, the index answering for the single-page app's routes.
    files: ServeDir<ServeFile>,
    /// Favicon bytes by suffix, `None` when a file was unreadable at startup.
    ico: Option<Bytes>,
    png: Option<Bytes>,
    svg: Option<Bytes>,
}

impl Console {
    fn load(paths: ConsolePaths) -> Self {
        let read = |path: &PathBuf| std::fs::read(path).ok().map(Bytes::from);
        Self {
            ico: read(&paths.favicon_ico),
            png: read(&paths.favicon_png),
            svg: read(&paths.favicon_svg),
            files: ServeDir::new(&paths.directory)
                .fallback(ServeFile::new(paths.directory.join("index.html"))),
        }
    }
}

pub(crate) struct AppState {
    console: Option<Console>,
    /// The OpenAPI document's JSON, rendered once at build.
    openapi: String,
    pub(crate) auth: Option<AuthSettings>,
    pub(crate) host: Arc<dyn Host>,
    cli: bool,
}

impl AppState {
    /// Resolve the identity a request presents, anonymous on any failure.
    pub(crate) async fn identity(
        &self,
        headers: &HeaderMap,
    ) -> Result<Option<Identity>, HostError> {
        let Some(settings) = self.auth.as_ref() else {
            return Ok(None);
        };
        let Some(token) = crate::auth::bearer_token(headers) else {
            return Ok(None);
        };
        let Some(parsed) = settings.parse(&token) else {
            return Ok(None);
        };
        let Some(user) = self.host.user(parsed.user_id).await? else {
            return Ok(None);
        };

        Ok(Some(Identity {
            token: parsed.token,
            expires: parsed.expires,
            user,
            impersonated_by: parsed.impersonated_by,
        }))
    }

    /// Resolve the actor a request comes from.
    ///
    /// The CLI control app and deployments with authentication unconfigured are
    /// unrestricted, every permission gate short-circuits for them. A standing
    /// resolution needs only the user's standing so a host with a native store answers
    /// without crossing into Python, the user's wire payload left null, and a host
    /// without one falls back to the full resolution.
    pub(crate) async fn actor(
        &self,
        headers: &HeaderMap,
        resolution: Resolution,
    ) -> Result<Actor, HostError> {
        let unrestricted = self.cli || self.auth.is_none();

        if resolution == Resolution::Standing {
            let parsed = self.auth.as_ref().and_then(|settings| {
                crate::auth::bearer_token(headers).and_then(|token| settings.parse(&token))
            });
            let Some(parsed) = parsed else {
                return Ok(Actor {
                    user: None,
                    unrestricted,
                });
            };

            if let Some(found) = self.host.native_gate_user(parsed.user_id).await {
                return Ok(Actor {
                    user: found.map(|gate| UserRecord {
                        id: gate.id,
                        admin: gate.admin,
                        disabled: gate.disabled,
                        payload: Value::Null,
                    }),
                    unrestricted,
                });
            }
            // No native store so the full resolution answers.
        }

        let identity = self.identity(headers).await?;
        Ok(Actor {
            user: identity.map(|identity| identity.user),
            unrestricted,
        })
    }

    /// Resolve the actor a request comes from and admit it through a gate.
    ///
    /// The self-or-admin gate reads its target from path parameters, which only the
    /// dispatch table's routes carry so dispatch admits through [`Gate::admit`] itself
    /// and every gate here sees no path values.
    pub(crate) async fn admit(
        &self,
        headers: &HeaderMap,
        gate: Gate,
        resolution: Resolution,
    ) -> Result<Actor, ApiError> {
        let actor = self.actor(headers, resolution).await?;
        gate.admit(&actor, std::iter::empty())?;
        Ok(actor)
    }
}

/// How much of the actor's user a resolution fetches.
#[derive(Clone, Copy, PartialEq)]
pub(crate) enum Resolution {
    /// The full user record, its wire payload included, for routes that serve or
    /// forward it.
    Full,
    /// The user's standing alone, natively when the host can, for routes that only
    /// gate on it.
    Standing,
}

/// Respond with a body of already-serialized JSON.
pub(crate) fn json_response(body: String) -> Response {
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "application/json")],
        body,
    )
        .into_response()
}

/// Generate a favicon handler per suffix, serving the cached bytes with its media type.
macro_rules! favicons {
    ($($name:ident: $field:ident => $media:literal;)*) => {
        $(async fn $name(State(state): State<Arc<AppState>>) -> Response {
            match state.console.as_ref().and_then(|console| console.$field.clone()) {
                Some(bytes) => {
                    (StatusCode::OK, [(header::CONTENT_TYPE, $media)], bytes).into_response()
                }
                None => ApiError::http(StatusCode::NOT_FOUND).into_response(),
            }
        })*
    };
}

favicons! {
    serve_favicon_ico: ico => "image/x-icon";
    serve_favicon_png: png => "image/png";
    serve_favicon_svg: svg => "image/svg+xml";
}

/// Build the application router.
pub fn build_router(config: AppConfig) -> Router {
    let state = Arc::new(AppState {
        console: config.console.map(Console::load),
        openapi: crate::api::schema::document(&config.version)
            .to_json()
            .expect("the OpenAPI document is always serializable"),
        auth: config.auth,
        host: config.host,
        cli: config.cli_token.is_some(),
    });

    // The API catch-all handles GET only, part of the wire contract. A matched path with
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
        .route("/api/openapi.json", get(openapi))
        .route("/api/{*path}", get(api_not_found));
    router = record_routes(router);
    router = crate::api::dispatch::register(router);
    router = crate::api::streams::register(router);
    router = router.route("/api/statuses", get(crate::api::streams::statuses));

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
    /// Chain every table's routes onto the router in scope.
    macro_rules! register {
        ($($module:ident => $name:literal;)*) => {
            router
                $(
                    .route(concat!("/api/", $name), get(crate::api::records::$module::list))
                    .route(
                        concat!("/api/", $name, "/count"),
                        get(crate::api::records::$module::count),
                    )
                    .route(
                        concat!("/api/", $name, "/{id}"),
                        get(crate::api::records::$module::get),
                    )
                )*
        };
    }

    crate::api::records::for_each_record_table!(register)
}

/// Serve the OpenAPI document rendered at build.
async fn openapi(State(state): State<Arc<AppState>>) -> Response {
    json_response(state.openapi.clone())
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

/// The fallback for paths outside the API on an app with no console, answering with
/// the bare HTTP envelope an unrouted path gets.
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
/// The index fallback lets the single-page console own its routes. Error
/// responses from the file service convert to the bare HTTP envelope, the form the wire
/// contract gives every static-file failure.
async fn serve_console(State(state): State<Arc<AppState>>, request: Request) -> Response {
    let console = state
        .console
        .as_ref()
        .expect("the console fallback only routes when console paths exist");

    match console.files.clone().oneshot(request).await {
        Ok(response) if response.status().is_success() || response.status().is_redirection() => {
            response.into_response()
        }
        Ok(response) => ApiError::http(response.status()).into_response(),
        Err(error) => match error {},
    }
}
