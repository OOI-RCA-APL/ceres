//! The native HTTP server.
//!
//! Serves the Ceres API and console through axum. The wire contract, every route,
//! status code, envelope, and header, was set by the FastAPI application this replaced
//! and is preserved byte for byte, because external services consume it. Routing, error
//! envelopes, the console's static files, and the CLI control app's token gate live
//! here, while the operations behind the routes reach the engine through the [`Host`]
//! trait, the permanent seam between the server and whatever hosts it.

mod api;
mod app;
mod auth;
mod body;
mod cookie;
mod error;
mod host;
mod layers;
mod scrub;
mod serve;
mod tls;

pub use api::schema::document as openapi_document;
pub use app::{AppConfig, ConsolePaths, build_router};
pub use auth::AuthSettings;
pub use axum;
pub use host::{Answer, GateUser, Host, HostError, Served, StreamClose, UserRecord};
pub use layers::{apply_compression, apply_cors};
pub use serve::{BoundServer, Stopper};

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::{Request, StatusCode, header};
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use super::*;
    use crate::host::NoHost;

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
            version: "0.0.0".to_string(),
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

    const PASSWORD: &str = "pw12345";

    /// A host holding a fixed set of users sharing one password.
    #[derive(Default)]
    struct TestHost {
        users: Vec<(uuid::Uuid, &'static str, bool)>,
        /// Open streams by handle, each tracking how many messages it has sent.
        streams: std::sync::Mutex<std::collections::HashMap<u64, (String, u32)>>,
    }

    impl TestHost {
        fn record(&self, id: uuid::Uuid, username: &str, admin: bool) -> UserRecord {
            UserRecord {
                id,
                admin,
                disabled: false,
                payload: serde_json::json!({"id": id.to_string(), "username": username}),
            }
        }
    }

    #[async_trait::async_trait]
    impl Host for TestHost {
        async fn user(&self, id: uuid::Uuid) -> Result<Option<UserRecord>, HostError> {
            Ok(self
                .users
                .iter()
                .find(|(candidate, _, _)| *candidate == id)
                .map(|(id, username, admin)| self.record(*id, username, *admin)))
        }

        async fn verify_login(
            &self,
            username: String,
            password: String,
        ) -> Result<Option<UserRecord>, HostError> {
            Ok(self
                .users
                .iter()
                .find(|(_, candidate, _)| *candidate == username && password == PASSWORD)
                .map(|(id, username, admin)| self.record(*id, username, *admin)))
        }

        async fn change_password(
            &self,
            user: uuid::Uuid,
            old_password: String,
            _new_password: String,
        ) -> Result<Option<UserRecord>, HostError> {
            if old_password != PASSWORD {
                return Ok(None);
            }

            self.user(user).await
        }

        async fn stream_open(
            &self,
            operation: &str,
            _arguments: serde_json::Value,
        ) -> Result<u64, StreamClose> {
            if operation == "queries.subscribe" {
                return Err(StreamClose {
                    code: 1008,
                    reason: r#"{"__error__":true,"type":"not-permitted-error"}"#.to_string(),
                });
            }

            let mut streams = self.streams.lock().unwrap();
            let handle = streams.len() as u64 + 1;
            streams.insert(handle, (operation.to_string(), 0));
            Ok(handle)
        }

        async fn stream_next(&self, handle: u64) -> Result<Option<String>, StreamClose> {
            let mut streams = self.streams.lock().unwrap();
            let Some((operation, sent)) = streams.get_mut(&handle) else {
                return Ok(None);
            };
            if *sent >= 2 {
                return Ok(None);
            }

            *sent += 1;
            Ok(Some(format!(
                r#"{{"stream":"{operation}","index":{sent}}}"#
            )))
        }

        async fn stream_close(&self, handle: u64) {
            self.streams.lock().unwrap().remove(&handle);
        }

        async fn operate(
            &self,
            operation: &str,
            _arguments: serde_json::Value,
        ) -> Result<Answer, HostError> {
            let payload = serde_json::json!({
                "section": operation,
                "authentication": {"secret": "the-signing-secret", "duration": 1800},
            });
            Ok(Answer::Payload(payload.to_string()))
        }
    }

    fn settings(allow_impersonate: bool) -> AuthSettings {
        AuthSettings::new(
            "an-adequately-long-test-signing-secret",
            chrono::TimeDelta::minutes(30),
            allow_impersonate,
        )
    }

    fn two_user_app(
        admin: uuid::Uuid,
        viewer: uuid::Uuid,
        allow_impersonate: bool,
    ) -> axum::Router {
        build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: Some(settings(allow_impersonate)),
            host: std::sync::Arc::new(TestHost {
                users: vec![(admin, "admin", true), (viewer, "viewer", false)],
                ..TestHost::default()
            }),
            version: "0.0.0".to_string(),
        })
    }

    fn authenticated_app(user: uuid::Uuid, allow_impersonate: bool) -> axum::Router {
        build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: Some(settings(allow_impersonate)),
            host: std::sync::Arc::new(TestHost {
                users: vec![(user, "u", false)],
                ..TestHost::default()
            }),
            version: "0.0.0".to_string(),
        })
    }

    /// Send one request with a JSON body through a router.
    macro_rules! request_json {
        ($app:expr, $method:ident $path:expr, $body:expr $(, $name:expr => $value:expr)*) => {{
            let request = Request::$method($path)
                .header(header::CONTENT_TYPE, "application/json")
                $(.header($name, $value))*
                .body(Body::from(serde_json::to_vec(&$body).unwrap()))
                .unwrap();
            $app.clone().oneshot(request).await.unwrap()
        }};
    }

    async fn json_of(response: axum::response::Response) -> serde_json::Value {
        let body = response.into_body().collect().await.unwrap().to_bytes();
        serde_json::from_slice(&body).unwrap()
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

        let minted = settings(false).mint(user, None).unwrap();
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
        let minted = settings(false).mint(uuid::Uuid::new_v4(), None).unwrap();
        assert_response!(
            request!(app, get "/api/auth/me", header::AUTHORIZATION => format!("Bearer {}", minted.token)),
            UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn login_issues_identities_and_assigns_cookies() {
        let user = uuid::Uuid::new_v4();
        let app = authenticated_app(user, false);

        // Body problems refuse before anything else runs.
        let response =
            request_json!(app, post "/api/auth/login", serde_json::json!({"password": 5}));
        let response = assert_response!(response, UNPROCESSABLE_ENTITY);
        let body = json_of(response).await;
        assert_eq!(body["type"], "validation-failed-error");
        assert_eq!(body["problems"][0]["location"][1], "username");

        let response = request_json!(
            app, post "/api/auth/login",
            serde_json::json!({"username": "u", "password": PASSWORD, "cookie": "insecure"})
        );
        let response = assert_response!(response, OK);
        let cookie = response
            .headers()
            .get(header::SET_COOKIE)
            .unwrap()
            .to_str()
            .unwrap()
            .to_string();
        assert!(cookie.starts_with("Authorization=\"Bearer "));
        assert!(cookie.ends_with("; Path=/; SameSite=lax"));
        let body = json_of(response).await;
        assert_eq!(body["user"]["id"], user.to_string());
        assert_eq!(body["impersonated_by"], serde_json::Value::Null);

        // Login with authentication unconfigured refuses as disabled.
        let disabled = build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: None,
            host: std::sync::Arc::new(NoHost),
            version: "0.0.0".to_string(),
        });
        let response = request_json!(
            disabled, post "/api/auth/login",
            serde_json::json!({"username": "u", "password": PASSWORD})
        );
        assert_response!(
            response,
            FORBIDDEN,
            br#"{"__error__":true,"type":"authentication-disabled-error"}"#
        );
    }

    #[tokio::test]
    async fn wrong_credentials_stall_and_refuse() {
        let app = authenticated_app(uuid::Uuid::new_v4(), false);
        let started = std::time::Instant::now();
        let response = request_json!(
            app, post "/api/auth/login",
            serde_json::json!({"username": "u", "password": "wrong"})
        );
        assert!(started.elapsed() >= std::time::Duration::from_millis(2500));
        assert_response!(
            response,
            UNAUTHORIZED,
            br#"{"__error__":true,"type":"bad-credentials-error"}"#
        );
    }

    #[tokio::test]
    async fn refresh_reissues_without_the_impersonation_marker() {
        let admin = uuid::Uuid::new_v4();
        let viewer = uuid::Uuid::new_v4();
        let app = two_user_app(admin, viewer, true);

        // The refreshed identity is the viewer's own even when the presented token was
        // impersonated.
        let impersonated = settings(true).mint(viewer, Some(admin)).unwrap();
        let response = request_json!(
            app, post "/api/auth/refresh", serde_json::json!({}),
            header::AUTHORIZATION => format!("Bearer {}", impersonated.token)
        );
        let response = assert_response!(response, OK);
        let body = json_of(response).await;
        assert_eq!(body["user"]["id"], viewer.to_string());
        assert_eq!(body["impersonated_by"], serde_json::Value::Null);

        let response = request_json!(app, post "/api/auth/refresh", serde_json::json!({}));
        assert_response!(response, UNAUTHORIZED);
    }

    #[tokio::test]
    async fn logout_deletes_the_cookie_and_returns_the_identity() {
        let user = uuid::Uuid::new_v4();
        let app = authenticated_app(user, false);
        let minted = settings(false).mint(user, None).unwrap();

        let response = request_json!(
            app, post "/api/auth/logout", serde_json::json!({}),
            header::AUTHORIZATION => format!("Bearer {}", minted.token)
        );
        let response = assert_response!(response, OK);
        let cookie = response
            .headers()
            .get(header::SET_COOKIE)
            .unwrap()
            .to_str()
            .unwrap()
            .to_string();
        assert!(cookie.starts_with("Authorization=\"\"; expires="));
        assert!(cookie.contains("Max-Age=0"));

        let response = request_json!(app, post "/api/auth/logout", serde_json::json!({}));
        assert_response!(
            response,
            UNAUTHORIZED,
            br#"{"__error__":true,"type":"not-authenticated-error"}"#
        );
    }

    #[tokio::test]
    async fn impersonation_gates_run_in_order() {
        let admin = uuid::Uuid::new_v4();
        let viewer = uuid::Uuid::new_v4();
        let admin_token = settings(true).mint(admin, None).unwrap().token;
        let viewer_token = settings(true).mint(viewer, None).unwrap().token;
        let body = serde_json::json!({"user_id": viewer.to_string()});

        // Off means absent, the route reports itself missing rather than forbidden.
        let hidden = two_user_app(admin, viewer, false);
        let response = request_json!(
            hidden, post "/api/auth/impersonate", body,
            header::AUTHORIZATION => format!("Bearer {admin_token}")
        );
        assert_response!(
            response,
            NOT_FOUND,
            br#"{"__error__":true,"type":"not-found-error"}"#
        );

        let app = two_user_app(admin, viewer, true);
        let response = request_json!(app, post "/api/auth/impersonate", body);
        assert_response!(response, UNAUTHORIZED);

        let response = request_json!(
            app, post "/api/auth/impersonate", body,
            header::AUTHORIZATION => format!("Bearer {viewer_token}")
        );
        assert_response!(
            response,
            FORBIDDEN,
            br#"{"__error__":true,"type":"not-permitted-error"}"#
        );

        let response = request_json!(
            app, post "/api/auth/impersonate", body,
            header::AUTHORIZATION => format!("Bearer {admin_token}")
        );
        let response = assert_response!(response, OK);
        let issued = json_of(response).await;
        assert_eq!(issued["user"]["id"], viewer.to_string());
        assert_eq!(issued["impersonated_by"], admin.to_string());

        // The marker survives the round trip through the issued token itself.
        let response = request_json!(
            app, get "/api/auth/me", serde_json::json!({}),
            header::AUTHORIZATION => format!("Bearer {}", issued["token"].as_str().unwrap())
        );
        let me = json_of(assert_response!(response, OK)).await;
        assert_eq!(me["impersonated_by"], admin.to_string());

        // A missing target is not found.
        let response = request_json!(
            app, post "/api/auth/impersonate",
            serde_json::json!({"user_id": uuid::Uuid::new_v4().to_string()}),
            header::AUTHORIZATION => format!("Bearer {admin_token}")
        );
        assert_response!(response, NOT_FOUND);
    }

    #[tokio::test]
    async fn password_changes_gate_then_verify() {
        let user = uuid::Uuid::new_v4();
        let app = authenticated_app(user, false);
        let token = settings(false).mint(user, None).unwrap().token;

        let response = request_json!(
            app, post "/api/auth/change-password",
            serde_json::json!({"old_password": PASSWORD, "new_password": "long enough phrase"}),
            header::AUTHORIZATION => format!("Bearer {token}")
        );
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["id"], user.to_string());

        // Anonymous callers refuse at the authenticated gate, in the typed shape.
        let response = request_json!(
            app, post "/api/auth/change-password",
            serde_json::json!({"old_password": "a", "new_password": "b"})
        );
        assert_response!(
            response,
            UNAUTHORIZED,
            br#"{"__error__":true,"type":"not-authenticated-error"}"#
        );

        // An unrestricted caller with no concrete user gets the bare envelope instead.
        let unrestricted = build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: None,
            host: std::sync::Arc::new(NoHost),
            version: "0.0.0".to_string(),
        });
        let response = request_json!(
            unrestricted, post "/api/auth/change-password",
            serde_json::json!({"old_password": "a", "new_password": "b"})
        );
        assert_response!(
            response,
            UNAUTHORIZED,
            br#"{"__error__":true,"type":"http-error","status":401}"#
        );
    }

    #[tokio::test]
    async fn config_sections_gate_by_admin_and_scrub() {
        let admin = uuid::Uuid::new_v4();
        let viewer = uuid::Uuid::new_v4();
        let app = two_user_app(admin, viewer, false);
        let admin_token = settings(false).mint(admin, None).unwrap().token;
        let viewer_token = settings(false).mint(viewer, None).unwrap().token;

        assert_response!(request!(app, get "/api/config"), UNAUTHORIZED);
        assert_response!(
            request!(app, get "/api/config", header::AUTHORIZATION => format!("Bearer {viewer_token}")),
            FORBIDDEN
        );

        for path in [
            "/api/config",
            "/api/config/service",
            "/api/config/server",
            "/api/config/database",
        ] {
            let response =
                request!(app, get path, header::AUTHORIZATION => format!("Bearer {admin_token}"));
            let body = json_of(assert_response!(response, OK)).await;
            assert_eq!(
                body["authentication"],
                serde_json::json!({"duration": 1800})
            );
        }

        // The console section is open and carries the operation it asked the host for.
        let response = request!(app, get "/api/config/console");
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["section"], "config.console");
    }

    #[tokio::test]
    async fn reloading_scrubs_the_configuration_it_answers_with() {
        // Reloading answers with the whole configuration, so it drops credentials the way
        // the configuration routes do.
        let admin = uuid::Uuid::new_v4();
        let viewer = uuid::Uuid::new_v4();
        let app = two_user_app(admin, viewer, false);
        let token = settings(false).mint(admin, None).unwrap().token;

        assert_response!(request!(app, post "/api/reload"), UNAUTHORIZED);

        let response = request!(
            app, post "/api/reload",
            header::AUTHORIZATION => format!("Bearer {token}")
        );
        let body = json_of(assert_response!(response, OK)).await;

        assert_eq!(body["section"], "engine.reload");
        assert_eq!(body["authentication"]["duration"], 1800);
        assert!(body["authentication"].get("secret").is_none());
    }

    #[tokio::test]
    async fn record_routes_gate_and_dispatch() {
        let user = uuid::Uuid::new_v4();
        let app = authenticated_app(user, false);
        let token = settings(false).mint(user, None).unwrap().token;

        assert_response!(request!(app, get "/api/particles"), UNAUTHORIZED);

        let response = request!(
            app, get "/api/particles?type=sample&limit=5",
            header::AUTHORIZATION => format!("Bearer {token}")
        );
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["section"], "records.list");

        let response = request!(
            app, get "/api/particles/count",
            header::AUTHORIZATION => format!("Bearer {token}")
        );
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["section"], "records.count");

        // A non-UUID path segment never matched the route, so it stays a plain 404.
        assert_response!(
            request!(
                app, get "/api/particles/not-a-uuid",
                header::AUTHORIZATION => format!("Bearer {token}")
            ),
            NOT_FOUND,
            br#"{"__error__":true,"type":"not-found-error"}"#
        );
    }

    #[tokio::test]
    async fn dispatched_routes_gate_and_forward() {
        let admin = uuid::Uuid::new_v4();
        let viewer = uuid::Uuid::new_v4();
        let app = two_user_app(admin, viewer, false);
        let admin_token = settings(false).mint(admin, None).unwrap().token;
        let viewer_token = settings(false).mint(viewer, None).unwrap().token;

        // Reloading requires an administrator.
        assert_response!(request!(app, post "/api/reload"), UNAUTHORIZED);
        assert_response!(
            request!(app, post "/api/reload", header::AUTHORIZATION => format!("Bearer {viewer_token}")),
            FORBIDDEN
        );
        let response = request!(
            app, post "/api/reload",
            header::AUTHORIZATION => format!("Bearer {admin_token}")
        );
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["section"], "engine.reload");

        // Creating a user answers 201, the API's one non-default status.
        let response = request_json!(
            app, post "/api/users", serde_json::json!({"username": "new"}),
            header::AUTHORIZATION => format!("Bearer {admin_token}")
        );
        assert_response!(response, CREATED);

        // A malformed UUID capture means the route never matched.
        assert_response!(
            request!(
                app, get "/api/users/not-a-uuid",
                header::AUTHORIZATION => format!("Bearer {admin_token}")
            ),
            NOT_FOUND,
            br#"{"__error__":true,"type":"not-found-error"}"#
        );

        // Self-or-admin admits the named user and refuses everyone else.
        assert_response!(
            request!(
                app, get format!("/api/permissions/user/{viewer}").as_str(),
                header::AUTHORIZATION => format!("Bearer {viewer_token}")
            ),
            OK
        );
        assert_response!(
            request!(
                app, get format!("/api/permissions/user/{admin}").as_str(),
                header::AUTHORIZATION => format!("Bearer {viewer_token}")
            ),
            FORBIDDEN
        );

        // Open routes dispatch without credentials, the operation applying its own rules.
        let response = request_json!(
            app, post "/api/components/@probe/queries/ping/call",
            serde_json::json!({"text": "hi"})
        );
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["section"], "queries.call");

        // A wildcard capture carries the whole remaining path.
        let response = request!(
            app, get format!("/api/permissions/effective/{admin}/@sensor.temp").as_str(),
            header::AUTHORIZATION => format!("Bearer {admin_token}")
        );
        let body = json_of(assert_response!(response, OK)).await;
        assert_eq!(body["section"], "permissions.effective_at");
    }

    /// Serve an app on a loopback port for the duration of a socket test.
    async fn served(app: axum::Router) -> (u16, serve::Stopper, tokio::task::JoinHandle<()>) {
        let server = BoundServer::bind("127.0.0.1", 0).unwrap();
        let port = server.port();
        let stopper = server.stopper();
        let serving = tokio::spawn(async move {
            let _ = server.serve(app).await;
        });
        (port, stopper, serving)
    }

    #[tokio::test]
    async fn record_streams_share_their_listing_paths() {
        let user = uuid::Uuid::new_v4();
        let token = settings(false).mint(user, None).unwrap().token;
        let (port, stopper, serving) = served(authenticated_app(user, false)).await;

        // The same path serves a listing without an upgrade.
        let listing = reqwest_get(port, "/api/particles", &token).await;
        assert_eq!(listing["section"], "records.list");

        // With an upgrade it streams, and the messages arrive as the host rendered them.
        let messages = read_socket(port, "/api/particles", Some(&token)).await;
        assert_eq!(
            messages,
            vec![
                r#"{"stream":"records.stream","index":1}"#,
                r#"{"stream":"records.stream","index":2}"#,
            ]
        );

        stopper.stop(std::time::Duration::from_millis(50));
        let _ = serving.await;
    }

    #[tokio::test]
    async fn status_and_procedure_streams_serve() {
        let user = uuid::Uuid::new_v4();
        let token = settings(false).mint(user, None).unwrap().token;
        let (port, stopper, serving) = served(authenticated_app(user, false)).await;

        let messages = read_socket(port, "/api/statuses", Some(&token)).await;
        assert_eq!(messages.len(), 2);
        assert!(messages[0].contains("statuses.stream"));

        // Procedure subscriptions need no credentials, the operation gates them.
        let messages = read_socket(
            port,
            "/api/components/@probe/procedures/ping/subscribe",
            None,
        )
        .await;
        assert!(messages[0].contains("procedures.subscribe"));

        // A refused stream closes with the code and reason the host reported.
        let messages =
            read_socket(port, "/api/components/@probe/queries/ping/subscribe", None).await;
        assert!(messages.is_empty(), "a refused stream sends no messages");

        stopper.stop(std::time::Duration::from_millis(50));
        let _ = serving.await;
    }

    #[tokio::test]
    async fn record_streams_refuse_anonymous_callers() {
        let user = uuid::Uuid::new_v4();
        let (port, stopper, serving) = served(authenticated_app(user, false)).await;

        // The gate runs before the upgrade, so the handshake itself fails and the
        // caller never holds an accepted socket.
        let attempt =
            tokio_tungstenite::connect_async(format!("ws://127.0.0.1:{port}/api/particles")).await;
        assert!(attempt.is_err(), "an anonymous caller must not upgrade");

        stopper.stop(std::time::Duration::from_millis(50));
        let _ = serving.await;
    }

    /// Fetch one JSON body over HTTP.
    async fn reqwest_get(port: u16, path: &str, token: &str) -> serde_json::Value {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .unwrap();
        let request = format!(
            "GET {path} HTTP/1.1\r\nhost: localhost\r\nauthorization: Bearer {token}\r\n\
             connection: close\r\n\r\n"
        );
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).await.unwrap();
        let body = response.rsplit("\r\n\r\n").next().unwrap();
        serde_json::from_str(body).unwrap()
    }

    /// Open a socket and collect its text messages until it closes.
    async fn read_socket(port: u16, path: &str, token: Option<&str>) -> Vec<String> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::client::IntoClientRequest;

        let mut request = format!("ws://127.0.0.1:{port}{path}")
            .into_client_request()
            .unwrap();
        if let Some(token) = token {
            request
                .headers_mut()
                .insert("authorization", format!("Bearer {token}").parse().unwrap());
        }

        let (mut socket, _) = tokio_tungstenite::connect_async(request).await.unwrap();
        let mut messages = Vec::new();
        while let Some(Ok(message)) = socket.next().await {
            match message {
                tokio_tungstenite::tungstenite::Message::Text(text) => {
                    messages.push(text.to_string());
                }
                tokio_tungstenite::tungstenite::Message::Close(_) => break,
                _ => continue,
            }
        }

        messages
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
            version: "0.0.0".to_string(),
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
