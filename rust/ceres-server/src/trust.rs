//! The certificate authority a managed HTTPS certificate is signed by, offered for download
//! so clients can trust it.
//!
//! `/ca.crt` answers on every web listener and on the redirecting one, which is how a
//! client reaches it before it trusts the HTTPS listener. It never needs authentication.
//! The file is read per request, so it answers what is on disk once startup has created it.

use std::path::PathBuf;

use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use ceres_config::ServerHttpsConfig;

/// The authority signing a managed HTTPS certificate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Authority {
    /// Path of the authority's certificate.
    pub path: PathBuf,
    /// The file name a download is saved as.
    pub filename: String,
}

impl Authority {
    /// The authority of `https`'s certificate, `None` unless Ceres manages it.
    pub fn of(https: &ServerHttpsConfig) -> Option<Self> {
        let auto = https.certificate.auto.as_ref()?;
        let filename = match crate::tls::hostname() {
            Some(host) => format!("ceres-{}-ca.crt", host.to_ascii_lowercase()),
            None => "ceres-ca.crt".into(),
        };
        Some(Self {
            path: auto.authority().path,
            filename,
        })
    }

    /// The authority certificate's SHA-256 fingerprint, `None` when it cannot be read.
    pub(crate) fn fingerprint(&self) -> Option<String> {
        crate::tls::authority_certificate(&self.path)
            .ok()
            .map(|(_, fingerprint)| fingerprint)
    }

    /// Answer the authority certificate as a download.
    pub(crate) fn download(&self) -> Response {
        match crate::tls::authority_certificate(&self.path) {
            Ok((pem, _)) => (
                StatusCode::OK,
                [
                    (
                        header::CONTENT_TYPE,
                        "application/x-x509-ca-cert".to_string(),
                    ),
                    (
                        header::CONTENT_DISPOSITION,
                        format!("attachment; filename=\"{}\"", self.filename),
                    ),
                    (header::CACHE_CONTROL, "no-cache".to_string()),
                ],
                pem,
            )
                .into_response(),
            Err(_) => StatusCode::NOT_FOUND.into_response(),
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use axum::Router;
    use axum::body::Body;
    use axum::http::{HeaderMap, Request};
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    use super::*;
    use crate::{AppConfig, ConsolePaths, build_router, redirect_router};

    /// A managed `https` section with its authority created under `directory`.
    fn managed(directory: &std::path::Path) -> (ServerHttpsConfig, Authority) {
        let https = crate::tls::tests::managed(directory);
        let authority = Authority::of(&https).unwrap();
        (https, authority)
    }

    /// The web app, its console under `directory`, offering `authority`.
    fn web_app(directory: &std::path::Path, authority: Option<Authority>) -> Router {
        std::fs::write(directory.join("index.html"), b"<html>console</html>").unwrap();
        build_router(AppConfig {
            authority,
            console: Some(ConsolePaths {
                directory: directory.to_path_buf(),
                favicon_ico: directory.join("favicon.ico"),
                favicon_png: directory.join("favicon.png"),
                favicon_svg: directory.join("favicon.svg"),
            }),
            cli_token: None,
            auth: None,
            host: Arc::new(crate::host::NoHost),
            version: "0.0.0".to_string(),
        })
    }

    async fn get(router: &Router, path: &str) -> (StatusCode, HeaderMap, String) {
        let request = Request::get(path)
            .header(header::HOST, "studio.local:8080")
            .body(Body::empty())
            .unwrap();
        let response = router.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let headers = response.headers().clone();
        let body = response.into_body().collect().await.unwrap().to_bytes();
        (status, headers, String::from_utf8(body.to_vec()).unwrap())
    }

    /// The authority certificate as written, its first PEM block.
    fn written(authority: &Authority) -> String {
        let text = std::fs::read_to_string(&authority.path).unwrap();
        let end = "-----END CERTIFICATE-----";
        text[..text.find(end).unwrap() + end.len()].to_string()
    }

    #[tokio::test]
    async fn managed_listeners_offer_their_authority_for_download() {
        let directory = tempfile::tempdir().unwrap();
        let (_, authority) = managed(directory.path());
        let app = web_app(directory.path(), Some(authority.clone()));

        let (status, headers, body) = get(&app, "/ca.crt").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers[header::CONTENT_TYPE], "application/x-x509-ca-cert");
        assert_eq!(
            headers[header::CONTENT_DISPOSITION],
            format!("attachment; filename=\"{}\"", authority.filename)
        );
        assert_eq!(body.trim(), written(&authority).trim());
        assert!(!body.contains("PRIVATE KEY"));

        let (status, _, features) = get(&app, "/api/auth/features").await;
        assert_eq!(status, StatusCode::OK);
        let features: serde_json::Value = serde_json::from_str(&features).unwrap();
        let fingerprint = crate::tls::authority_certificate(&authority.path)
            .unwrap()
            .1;
        assert_eq!(features["authority"]["fingerprint"], fingerprint.as_str());
    }

    #[tokio::test]
    async fn listeners_without_a_managed_certificate_offer_nothing() {
        let directory = tempfile::tempdir().unwrap();
        let app = web_app(directory.path(), None);
        let (status, _, _) = get(&app, "/ca.crt").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        let (_, _, features) = get(&app, "/api/auth/features").await;
        let features: serde_json::Value = serde_json::from_str(&features).unwrap();
        assert_eq!(features["authority"], serde_json::Value::Null);

        let plain = crate::tls::tests::https(directory.path(), None, |key| key);
        assert_eq!(Authority::of(&plain), None);
    }

    #[tokio::test]
    async fn the_redirecting_listener_serves_the_authority_in_place() {
        let directory = tempfile::tempdir().unwrap();
        let (_, authority) = managed(directory.path());
        let redirecting = redirect_router(8443, Some(authority.clone()));
        let (status, headers, body) = get(&redirecting, "/ca.crt").await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(headers[header::CONTENT_TYPE], "application/x-x509-ca-cert");
        assert_eq!(body.trim(), written(&authority).trim());

        // Everything else still redirects.
        let (status, headers, _) = get(&redirecting, "/login").await;
        assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
        assert_eq!(headers[header::LOCATION], "https://studio.local:8443/login");

        let (status, _, _) = get(&redirect_router(8443, None), "/ca.crt").await;
        assert_eq!(status, StatusCode::TEMPORARY_REDIRECT);
    }

    #[tokio::test]
    async fn an_authority_not_created_yet_is_not_found() {
        let directory = tempfile::tempdir().unwrap();
        let authority = Authority {
            path: directory.path().join("ca.crt"),
            filename: "ceres-ca.crt".into(),
        };
        let (status, _, _) = get(
            &web_app(directory.path(), Some(authority.clone())),
            "/ca.crt",
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        let (status, _, _) = get(&redirect_router(8443, Some(authority)), "/ca.crt").await;
        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[test]
    fn downloads_are_named_for_the_machine() {
        let directory = tempfile::tempdir().unwrap();
        let (_, authority) = managed(directory.path());
        let expected = match crate::tls::hostname() {
            Some(host) => format!("ceres-{}-ca.crt", host.to_ascii_lowercase()),
            None => "ceres-ca.crt".into(),
        };
        assert_eq!(authority.filename, expected);
    }
}
