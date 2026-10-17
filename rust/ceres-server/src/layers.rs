//! Cross-cutting layers built from the server configuration.
//!
//! CORS expands a `*` in the method list to the full method set and mirrors the request for
//! a `*` header or origin list. An origin passes when it appears in the list or matches the
//! configured pattern.
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

/// The methods a `*` in the allowed methods expands to.
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
    // matching the configured pattern.
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

/// The media types a codec or an archive already compressed. Another pass finds nothing left to
/// take out of them, and spends the CPU a live video at 10 Mbit/s keeps busy for nothing.
const COMPRESSED_ALREADY: [&str; 12] = [
    "video/",
    "audio/",
    // WOFF and WOFF2 both, which a font wraps to compress itself.
    "font/woff",
    "application/zip",
    "application/gzip",
    "application/x-gzip",
    "application/zstd",
    "application/x-xz",
    "application/x-bzip2",
    "application/x-7z-compressed",
    "application/vnd.rar",
    "application/x-rar-compressed",
];

/// Leaves a response alone whose media type is already compressed.
#[derive(Clone, Copy)]
struct NotCompressedAlready;

impl Predicate for NotCompressedAlready {
    fn should_compress<B>(&self, response: &axum::http::Response<B>) -> bool
    where
        B: axum::body::HttpBody,
    {
        let Some(media) = response
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
        else {
            return true;
        };
        let media = media.trim_start().to_ascii_lowercase();
        !COMPRESSED_ALREADY
            .iter()
            .any(|prefix| media.starts_with(prefix))
    }
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

    // Text compresses many times over, which a slow link needs, and a streamed body still leaves
    // chunk by chunk, since the encoder flushes whenever the stream waits on its source.
    let minimum = SizeAbove::new(config.min_size.bytes())
        .and(NotForContentType::IMAGES)
        .and(NotForContentType::SSE)
        .and(NotCompressedAlready);

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

    /// Whether a 2000-byte response of `media` goes out compressed.
    async fn compresses(media: &'static str) -> bool {
        let app = apply_compression(
            Router::new().route(
                "/body",
                get(move || async move { ([(header::CONTENT_TYPE, media)], "x".repeat(2000)) }),
            ),
            None,
        );
        let response = app
            .oneshot(
                Request::get("/body")
                    .header(header::ACCEPT_ENCODING, "gzip, br, zstd")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        response.headers().get(header::CONTENT_ENCODING).is_some()
    }

    #[tokio::test]
    async fn media_a_codec_or_archive_compressed_goes_out_as_it_is() {
        for media in [
            "video/mp4",
            "Video/MP4",
            "audio/ogg",
            "font/woff2",
            "application/zip",
            "application/gzip",
            "application/zstd",
        ] {
            assert!(!compresses(media).await, "{media}");
        }
    }

    #[tokio::test]
    async fn text_and_uncompressed_fonts_still_compress() {
        for media in [
            "text/csv",
            "application/json",
            "application/x-ndjson",
            "font/ttf",
            "image/svg+xml",
        ] {
            assert!(compresses(media).await, "{media}");
        }
    }

    // A slow link needs a streamed text body compressed, and a live one needs each chunk to leave
    // as it comes rather than once the encoder's buffer fills.
    #[tokio::test]
    async fn a_compressed_stream_sends_each_chunk_while_the_stream_stays_open() {
        use http_body_util::BodyExt;

        let (send, receive) = tokio::sync::mpsc::channel::<String>(4);
        let receive = std::sync::Arc::new(tokio::sync::Mutex::new(Some(receive)));
        let app = apply_compression(
            Router::new().route(
                "/stream",
                get(move || {
                    let receive = receive.clone();
                    async move {
                        let receive = receive.lock().await.take().unwrap();
                        let stream = futures_util::stream::unfold(receive, |mut receive| async {
                            let chunk = receive.recv().await?;
                            Some((Ok::<_, std::io::Error>(chunk), receive))
                        });
                        (
                            [(header::CONTENT_TYPE, "text/csv")],
                            Body::from_stream(stream),
                        )
                    }
                }),
            ),
            None,
        );
        let response = app
            .oneshot(
                Request::get("/stream")
                    .header(header::ACCEPT_ENCODING, "gzip")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.headers()[header::CONTENT_ENCODING], "gzip");

        let mut body = response.into_body();
        send.send("a,b\n".repeat(500)).await.unwrap();
        let frame = tokio::time::timeout(Duration::from_secs(1), body.frame())
            .await
            .expect("the first chunk waited for the stream to end")
            .unwrap()
            .unwrap();
        assert!(!frame.into_data().unwrap().is_empty());
        drop(send);
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
