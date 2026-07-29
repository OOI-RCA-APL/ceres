//! The native HTTP server.
//!
//! Serves the Ceres API and console through axum, reproducing the Python application's
//! wire behavior exactly. Assembly starts from the edge inward: routing, error
//! envelopes, the console's static files, and the CLI control app's token gate live
//! here, while route families still served by the Python application reach it through a
//! fallback bridge until each is ported.

mod app;
mod error;

pub use app::{AppConfig, ConsolePaths, build_router};
pub use error::ApiError;

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

    #[tokio::test]
    async fn the_cli_app_requires_its_token_and_carries_no_console() {
        let app = build_router(AppConfig {
            console: None,
            cli_token: Some("cli-test-token".to_string()),
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
