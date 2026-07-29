//! Cross-cutting layers built from the server configuration.
//!
//! CORS reproduces Starlette's semantics for the same settings. A `*` in the method list
//! expands to the full method set, a `*` header or origin list mirrors the request, and
//! an origin passes when it appears in the list or matches the configured pattern.
//! Compression negotiates zstd over brotli over gzip, each at its own configured level,
//! by stacking one single-algorithm layer per codec with the preferred codec innermost.

use std::time::Duration;

use axum::Router;
use axum::http::{HeaderValue, Method, header};
use ceres_config::{MaybeSequence, ServerCompressionConfig, ServerCorsConfig};
use tower_http::CompressionLevel;
use tower_http::compression::CompressionLayer;
use tower_http::compression::predicate::{NotForContentType, Predicate, SizeAbove};
use tower_http::cors::{AllowHeaders, AllowMethods, AllowOrigin, CorsLayer, ExposeHeaders};

/// Every method Starlette's `*` expands to.
const ALL_METHODS: [Method; 7] = [
    Method::DELETE,
    Method::GET,
    Method::HEAD,
    Method::OPTIONS,
    Method::PATCH,
    Method::POST,
    Method::PUT,
];

/// Collect a config list, reporting whether it was the `*` wildcard.
fn wildcard_or_list(values: &MaybeSequence<String>) -> (bool, Vec<String>) {
    let values: Vec<String> = values.as_slice().to_vec();
    if values.iter().any(|value| value == "*") {
        (true, Vec::new())
    } else {
        (false, values)
    }
}

/// Apply the CORS layer when the section is present and enabled.
pub fn apply_cors(router: Router, config: Option<&ServerCorsConfig>) -> Router {
    let Some(config) = config.filter(|config| config.enabled) else {
        return router;
    };

    let mut layer = CorsLayer::new()
        .allow_credentials(config.allow_credentials)
        .max_age(Duration::from_secs(config.max_age));

    let (any_method, methods) = wildcard_or_list(&config.allow_methods);
    layer = layer.allow_methods(if any_method {
        AllowMethods::list(ALL_METHODS)
    } else {
        AllowMethods::list(
            methods
                .iter()
                .filter_map(|method| method.parse::<Method>().ok()),
        )
    });

    let (any_header, headers) = wildcard_or_list(&config.allow_headers);
    layer = layer.allow_headers(if any_header {
        AllowHeaders::mirror_request()
    } else {
        AllowHeaders::list(
            headers
                .iter()
                .filter_map(|name| name.parse::<header::HeaderName>().ok()),
        )
    });

    // An origin passes as the `*` wildcard, by exact membership in the list, or by
    // matching the configured pattern, mirroring Starlette's checks.
    let (any_origin, origins) = wildcard_or_list(&config.allow_origins);
    let pattern = config
        .allow_origin_regex
        .as_deref()
        .and_then(|pattern| fancy_regex::Regex::new(pattern).ok());
    layer = layer.allow_origin(if any_origin {
        AllowOrigin::mirror_request()
    } else {
        AllowOrigin::predicate(move |origin: &HeaderValue, _| {
            let Ok(origin) = origin.to_str() else {
                return false;
            };

            origins.iter().any(|allowed| allowed == origin)
                || pattern
                    .as_ref()
                    .is_some_and(|pattern| pattern.is_match(origin).unwrap_or(false))
        })
    });

    let (_, exposed) = wildcard_or_list(&config.expose_headers);
    if !exposed.is_empty() {
        layer = layer.expose_headers(ExposeHeaders::list(
            exposed
                .iter()
                .filter_map(|name| name.parse::<header::HeaderName>().ok()),
        ));
    }

    router.layer(layer)
}

/// Generate the stack of single-codec compression layers.
///
/// Codecs a client also accepts win by being closer to the response, so the first codec
/// listed here is the most preferred and sits innermost.
macro_rules! compression_codecs {
    ($router:ident, $config:ident, $minimum:ident, $($codec:ident: $enabled:ident => $level:ident;)*) => {
        $(if $config.$enabled {
            $router = $router.layer(
                CompressionLayer::new()
                    .no_gzip()
                    .no_br()
                    .no_zstd()
                    .no_deflate()
                    .$codec(true)
                    .quality(CompressionLevel::Precise(i32::try_from($config.$level).unwrap_or(1)))
                    .compress_when($minimum.clone()),
            );
        })*
    };
}

/// Apply response compression when the section enables it.
pub fn apply_compression(router: Router, config: Option<&ServerCompressionConfig>) -> Router {
    let default = ServerCompressionConfig::default();
    let config = config.unwrap_or(&default);
    if !config.enabled {
        return router;
    }

    let minimum = SizeAbove::new(config.min_size.bytes())
        .and(NotForContentType::IMAGES)
        .and(NotForContentType::SSE);

    let mut router = router;
    compression_codecs! {
        router, config, minimum,
        zstd: zstd => zstd_level;
        br: brotli => brotli_quality;
        gzip: gzip => gzip_level;
    }

    router
}

#[cfg(test)]
mod tests {
    use axum::Router;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use axum::routing::get;
    use tower::ServiceExt;

    use super::*;

    fn app() -> Router {
        Router::new().route("/big", get(|| async { "x".repeat(2000) }))
    }

    #[tokio::test]
    async fn compression_prefers_zstd_and_respects_the_minimum_size() {
        let app = apply_compression(
            Router::new()
                .route("/big", get(|| async { "x".repeat(2000) }))
                .route("/small", get(|| async { "tiny" })),
            None,
        );

        let response = app
            .clone()
            .oneshot(
                Request::get("/big")
                    .header(header::ACCEPT_ENCODING, "gzip, zstd")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(
            response.headers().get(header::CONTENT_ENCODING).unwrap(),
            "zstd"
        );

        let response = app
            .clone()
            .oneshot(
                Request::get("/big")
                    .header(header::ACCEPT_ENCODING, "gzip")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(
            response.headers().get(header::CONTENT_ENCODING).unwrap(),
            "gzip"
        );

        let response = app
            .oneshot(
                Request::get("/small")
                    .header(header::ACCEPT_ENCODING, "gzip, zstd")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert!(response.headers().get(header::CONTENT_ENCODING).is_none());
    }

    #[tokio::test]
    async fn cors_lists_and_patterns_admit_origins() {
        let config = ServerCorsConfig {
            allow_origins: MaybeSequence::Many(vec!["https://listed.example".to_string()]),
            allow_origin_regex: Some(r"https://.*\.pattern\.example".to_string()),
            ..ServerCorsConfig::default()
        };
        let app = apply_cors(app(), Some(&config));

        for (origin, allowed) in [
            ("https://listed.example", true),
            ("https://sub.pattern.example", true),
            ("https://other.example", false),
        ] {
            let response = app
                .clone()
                .oneshot(
                    Request::options("/big")
                        .header(header::ORIGIN, origin)
                        .header(header::ACCESS_CONTROL_REQUEST_METHOD, "GET")
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::OK);
            let header = response
                .headers()
                .get(header::ACCESS_CONTROL_ALLOW_ORIGIN)
                .map(|value| value.to_str().unwrap().to_string());
            assert_eq!(header, allowed.then(|| origin.to_string()), "{origin}");
        }
    }

    #[tokio::test]
    async fn wildcard_methods_expand_and_wildcard_origins_mirror() {
        let config = ServerCorsConfig {
            allow_origins: MaybeSequence::One("*".to_string()),
            ..ServerCorsConfig::default()
        };
        let app = apply_cors(app(), Some(&config));

        let response = app
            .oneshot(
                Request::options("/big")
                    .header(header::ORIGIN, "https://anywhere.example")
                    .header(header::ACCESS_CONTROL_REQUEST_METHOD, "PATCH")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response
                .headers()
                .get(header::ACCESS_CONTROL_ALLOW_ORIGIN)
                .unwrap(),
            "https://anywhere.example"
        );
        let methods = response
            .headers()
            .get(header::ACCESS_CONTROL_ALLOW_METHODS)
            .unwrap()
            .to_str()
            .unwrap();
        assert!(methods.contains("PATCH") && methods.contains("DELETE"));
    }
}
