//! The plain HTTP listener that sends every request to the HTTPS origin.

use std::fmt::Write;

use axum::Router;
use axum::extract::State;
use axum::http::uri::Authority;
use axum::http::{HeaderMap, StatusCode, Uri, header};
use axum::response::{IntoResponse, Redirect, Response};

/// Builds a router answering every request with a permanent redirect to the same path and
/// query on the HTTPS origin, which listens on `https_port` at the host the client named.
pub fn redirect_router(https_port: u16) -> Router {
    Router::new().fallback(redirect).with_state(https_port)
}

async fn redirect(State(https_port): State<u16>, headers: HeaderMap, uri: Uri) -> Response {
    // The client's own `Host` keeps a bookmark working whichever name or address it used,
    // and the configured bind address may be a wildcard that cannot be dialed.
    let host = headers
        .get(header::HOST)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<Authority>().ok());
    let Some(host) = host else {
        return (StatusCode::BAD_REQUEST, "missing or invalid Host header").into_response();
    };
    let mut target = format!("https://{}", host.host());
    if https_port != 443 {
        write!(target, ":{https_port}").expect("writing to a String cannot fail");
    }
    target.push_str(uri.path_and_query().map_or("/", |value| value.as_str()));
    Redirect::permanent(&target).into_response()
}

#[cfg(test)]
mod tests {
    use axum::body::Body;
    use axum::http::Request;
    use tower::ServiceExt;

    use super::*;

    /// Send one request with a `Host` header through the redirect router and return the
    /// `Location` it answers with.
    async fn location(https_port: u16, host: &str, path: &str) -> String {
        let request = Request::get(path)
            .header(header::HOST, host)
            .body(Body::empty())
            .unwrap();
        let response = redirect_router(https_port).oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::PERMANENT_REDIRECT);
        response.headers()[header::LOCATION]
            .to_str()
            .unwrap()
            .to_string()
    }

    #[tokio::test]
    async fn redirects_keep_host_path_and_query() {
        assert_eq!(
            location(8443, "10.0.0.5:8080", "/console/a?b=c").await,
            "https://10.0.0.5:8443/console/a?b=c"
        );
        assert_eq!(
            location(443, "example.test", "/").await,
            "https://example.test/"
        );
        assert_eq!(
            location(8443, "[::1]:80", "/x").await,
            "https://[::1]:8443/x"
        );
    }

    #[tokio::test]
    async fn requests_without_a_host_are_refused() {
        let request = Request::post("/").body(Body::empty()).unwrap();
        let response = redirect_router(8443).oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }
}
