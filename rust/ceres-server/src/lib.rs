//! The native HTTP server.
//!
//! Serves the Ceres API and console through axum, reproducing the Python application's
//! wire behavior exactly. Assembly starts from the edge inward: routing, error
//! envelopes, the console's static files, and the CLI control app's token gate live
//! here, while route families still served by the Python application reach it through a
//! fallback bridge until each is ported.

mod app;
mod auth;
mod error;
mod host;
mod layers;
mod serve;
mod tls;

pub use app::{AppConfig, ConsolePaths, build_router};
pub use auth::{
    Actor, AuthSettings, Identity, MintedToken, current_actor, current_identity, mint, parse,
    require_admin, require_authenticated, require_self_or_admin,
};
pub use error::ApiError;
pub use host::{Host, HostError, NoHost, UserRecord};
pub use layers::{apply_compression, apply_cors};
pub use serve::{BoundServer, Error as ServeError, Stopper};

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{Request, StatusCode, header};
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use super::*;

    /// Send one request through a router and return the response.
    macro_rules! request {
        ($app:expr, $method:ident $path:expr $(, $name:expr => $value:expr)*) => {{
            let request = Request::$method($path)
                $(.header($name, $value))*
                .body(Body::empty())
                .unwrap();
            $app.clone().oneshot(request).await.unwrap()
        }};
    }

    /// Assert a response's status and, when given, its exact body bytes.
    macro_rules! assert_response {
        ($response:expr, $status:ident) => {{
            let response = $response;
            assert_eq!(response.status(), StatusCode::$status);
            response
        }};
        ($response:expr, $status:ident, $body:expr) => {{
            let response = $response;
            assert_eq!(response.status(), StatusCode::$status);
            let body = response.into_body().collect().await.unwrap().to_bytes();
            assert_eq!(body.as_ref(), &$body[..]);
        }};
    }

    fn web_app(directory: &std::path::Path) -> axum::Router {
        std::fs::write(directory.join("index.html"), b"<html>console</html>").unwrap();
        std::fs::write(directory.join("app.js"), b"application code").unwrap();
        std::fs::write(directory.join("favicon.ico"), b"icon bytes").unwrap();
        build_router(AppConfig {
            console: Some(ConsolePaths {
                directory: directory.to_path_buf(),
                favicon_ico: directory.join("favicon.ico"),
                favicon_png: directory.join("favicon.png"),
                favicon_svg: directory.join("favicon.svg"),
            }),
            cli_token: None,
            auth: None,
            host: std::sync::Arc::new(NoHost),
        })
    }

    #[tokio::test]
    async fn alive_responds_empty() {
        let directory = tempfile::tempdir().unwrap();
        let app = web_app(directory.path());
        assert_response!(request!(app, get "/api/alive"), OK, b"");
    }

    #[tokio::test]
    async fn the_api_root_redirects_to_the_openapi_document() {
        let directory = tempfile::tempdir().unwrap();
        let app = web_app(directory.path());
        let response = assert_response!(request!(app, get "/api"), TEMPORARY_REDIRECT);
        assert_eq!(
            response.headers().get(header::LOCATION).unwrap(),
            "/api/openapi.json"
        );
    }

    #[tokio::test]
    async fn unknown_api_paths_return_the_error_envelope() {
        let directory = tempfile::tempdir().unwrap();
        let app = web_app(directory.path());

        assert_response!(
            request!(app, get "/api/does-not-exist"),
            NOT_FOUND,
            br#"{"__error__":true,"type":"not-found-error"}"#
        );

        // A matched path with the wrong method refuses the method instead.
        assert_response!(
            request!(app, post "/api/does-not-exist"),
            METHOD_NOT_ALLOWED,
            br#"{"__error__":true,"type":"http-error","status":405}"#
        );
        assert_response!(
            request!(app, post "/api/alive"),
            METHOD_NOT_ALLOWED,
            br#"{"__error__":true,"type":"http-error","status":405}"#
        );
    }

    #[tokio::test]
    async fn the_console_serves_files_and_falls_back_to_the_index() {
        let directory = tempfile::tempdir().unwrap();
        let app = web_app(directory.path());

        assert_response!(request!(app, get "/app.js"), OK, b"application code");
        assert_response!(request!(app, get "/"), OK, b"<html>console</html>");
        assert_response!(
            request!(app, get "/some/console/route"),
            OK,
            b"<html>console</html>"
        );
    }

    #[tokio::test]
    async fn favicons_serve_with_their_media_types() {
        let directory = tempfile::tempdir().unwrap();
        let app = web_app(directory.path());

        let response = assert_response!(request!(app, get "/favicon.ico"), OK);
        assert_eq!(
            response.headers().get(header::CONTENT_TYPE).unwrap(),
            "image/x-icon"
        );

        // A favicon whose file is missing reports itself absent rather than erroring.
        assert_response!(
            request!(app, get "/favicon.png"),
            NOT_FOUND,
            br#"{"__error__":true,"type":"http-error","status":404}"#
        );
    }

    /// A host holding exactly one user.
    struct OneUserHost {
        id: uuid::Uuid,
        admin: bool,
    }

    #[async_trait::async_trait]
    impl Host for OneUserHost {
        async fn user(&self, id: uuid::Uuid) -> Result<Option<UserRecord>, HostError> {
            Ok((id == self.id).then(|| UserRecord {
                id: self.id,
                admin: self.admin,
                disabled: false,
                payload: serde_json::json!({"id": self.id.to_string(), "username": "u"}),
            }))
        }
    }

    fn authenticated_app(user: uuid::Uuid, allow_impersonate: bool) -> axum::Router {
        build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: Some(AuthSettings {
                secret: "an-adequately-long-test-signing-secret".to_string(),
                duration: chrono::TimeDelta::minutes(30),
                allow_impersonate,
            }),
            host: std::sync::Arc::new(OneUserHost {
                id: user,
                admin: false,
            }),
        })
    }

    #[tokio::test]
    async fn me_round_trips_a_minted_token() {
        let user = uuid::Uuid::new_v4();
        let app = authenticated_app(user, false);

        assert_response!(
            request!(app, get "/api/auth/me"),
            UNAUTHORIZED,
            br#"{"__error__":true,"type":"not-authenticated-error"}"#
        );

        let settings = AuthSettings {
            secret: "an-adequately-long-test-signing-secret".to_string(),
            duration: chrono::TimeDelta::minutes(30),
            allow_impersonate: false,
        };
        let minted = mint(user, None, &settings).unwrap();
        let response = assert_response!(
            request!(app, get "/api/auth/me", header::AUTHORIZATION => format!("Bearer {}", minted.token)),
            OK
        );
        let body = response.into_body().collect().await.unwrap().to_bytes();
        let body: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(body["token"], minted.token.as_str());
        assert_eq!(body["user"]["username"], "u");
        assert_eq!(body["impersonated_by"], serde_json::Value::Null);

        // A token naming an unknown user resolves to anonymous.
        let minted = mint(uuid::Uuid::new_v4(), None, &settings).unwrap();
        assert_response!(
            request!(app, get "/api/auth/me", header::AUTHORIZATION => format!("Bearer {}", minted.token)),
            UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn features_report_impersonation() {
        let user = uuid::Uuid::new_v4();
        assert_response!(
            request!(authenticated_app(user, true), get "/api/auth/features"),
            OK,
            br#"{"impersonate":true}"#
        );
        assert_response!(
            request!(authenticated_app(user, false), get "/api/auth/features"),
            OK,
            br#"{"impersonate":false}"#
        );
    }

    #[tokio::test]
    async fn the_cli_app_requires_its_token_and_carries_no_console() {
        let app = build_router(AppConfig {
            console: None,
            cli_token: Some("cli-test-token".to_string()),
            auth: None,
            host: std::sync::Arc::new(NoHost),
        });

        assert_response!(
            request!(app, get "/api/alive"),
            UNAUTHORIZED,
            br#"{"__error__":true,"type":"not-authenticated-error"}"#
        );
        assert_response!(
            request!(app, get "/api/alive", header::AUTHORIZATION => "wrong"),
            UNAUTHORIZED
        );
        assert_response!(
            request!(app, get "/api/alive", header::AUTHORIZATION => "cli-test-token"),
            OK,
            b""
        );

        // No console mount, so unrouted paths answer with the bare envelope.
        assert_response!(
            request!(app, get "/favicon.ico", header::AUTHORIZATION => "cli-test-token"),
            NOT_FOUND,
            br#"{"__error__":true,"type":"http-error","status":404}"#
        );
    }
}
