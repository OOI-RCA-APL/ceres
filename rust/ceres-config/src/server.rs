//! The HTTP server configuration section.

use std::net::IpAddr;
use std::path::PathBuf;

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::values::{ByteSize, MaybeSequence, TimeDelta};

/// The `ssl` protocol constant selecting the server-side TLS protocol.
pub const TLS_SERVER_PROTOCOL: i64 = 17;

/// TLS configuration for the engine's HTTP server.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ServerSslConfig")]
pub struct RawServerSslConfig {
    /// Path to the server private key file.
    pub key: Option<PathBuf>,

    /// Password for an encrypted private key.
    pub key_password: Option<String>,

    /// Path to the server certificate file.
    pub cert: Option<PathBuf>,

    /// `ssl` protocol constant selecting the TLS version.
    pub version: Option<i64>,

    /// Path to a CA bundle used when validating client certificates.
    pub ca_certs: Option<PathBuf>,
}

/// Validated TLS configuration for the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerSslConfig {
    pub key: Option<PathBuf>,
    pub key_password: Option<String>,
    pub cert: Option<PathBuf>,
    pub version: Option<i64>,
    pub ca_certs: Option<PathBuf>,
}

impl Default for ServerSslConfig {
    fn default() -> Self {
        Self {
            key: None,
            key_password: None,
            cert: None,
            version: Some(TLS_SERVER_PROTOCOL),
            ca_certs: None,
        }
    }
}

impl TryFrom<RawServerSslConfig> for ServerSslConfig {
    type Error = Problems;

    fn try_from(raw: RawServerSslConfig) -> Result<Self, Problems> {
        Ok(Self {
            key: raw.key,
            key_password: raw.key_password,
            cert: raw.cert,
            version: raw.version.or(Some(TLS_SERVER_PROTOCOL)),
            ca_certs: raw.ca_certs,
        })
    }
}

/// Authentication settings for the engine's HTTP server.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ServerAuthenticationConfig")]
pub struct RawServerAuthenticationConfig {
    /// Secret used to sign and verify authentication tokens.
    pub secret: Option<String>,

    /// Lifetime of an issued authentication token.
    pub duration: Option<TimeDelta>,

    /// Whether an administrator may take on another user's identity without their password.
    pub allow_impersonate: Option<bool>,
}

/// Validated authentication settings for the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerAuthenticationConfig {
    pub secret: String,
    pub duration: TimeDelta,
    pub allow_impersonate: bool,
}

impl TryFrom<RawServerAuthenticationConfig> for ServerAuthenticationConfig {
    type Error = Problems;

    fn try_from(raw: RawServerAuthenticationConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let secret = problems.require(raw.secret, "secret", str::is_empty, "must not be empty.");

        problems.into_result(Self {
            secret,
            duration: raw.duration.unwrap_or(TimeDelta::from_secs(30 * 60)),
            allow_impersonate: raw.allow_impersonate.unwrap_or(false),
        })
    }
}

/// Cross-origin resource sharing settings for the engine's HTTP server.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ServerCorsConfig")]
pub struct RawServerCorsConfig {
    pub enabled: Option<bool>,
    pub allow_origins: Option<MaybeSequence<String>>,
    pub allow_origin_regex: Option<String>,
    pub allow_methods: Option<MaybeSequence<String>>,
    pub allow_headers: Option<MaybeSequence<String>>,
    pub allow_credentials: Option<bool>,
    pub expose_headers: Option<MaybeSequence<String>>,
    pub max_age: Option<u64>,
}

/// Validated cross-origin resource sharing settings for the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerCorsConfig {
    pub enabled: bool,
    pub allow_origins: MaybeSequence<String>,
    pub allow_origin_regex: Option<String>,
    pub allow_methods: MaybeSequence<String>,
    pub allow_headers: MaybeSequence<String>,
    pub allow_credentials: bool,
    pub expose_headers: MaybeSequence<String>,
    pub max_age: u64,
}

impl Default for ServerCorsConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            allow_origins: MaybeSequence::default(),
            allow_origin_regex: None,
            allow_methods: MaybeSequence::One("*".to_string()),
            allow_headers: MaybeSequence::One("*".to_string()),
            allow_credentials: true,
            expose_headers: MaybeSequence::default(),
            max_age: 600,
        }
    }
}

impl TryFrom<RawServerCorsConfig> for ServerCorsConfig {
    type Error = Problems;

    fn try_from(raw: RawServerCorsConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        let mut problems = Problems::default();

        let allow_origin_regex =
            raw.allow_origin_regex
                .filter(|pattern| match fancy_regex::Regex::new(pattern) {
                    Ok(_) => true,
                    Err(error) => {
                        problems.push(Problem::new(
                            "allow_origin_regex",
                            format!("invalid pattern. {error}"),
                        ));
                        false
                    }
                });

        let max_age = raw.max_age.unwrap_or(defaults.max_age);
        if max_age == 0 {
            problems.push(Problem::new("max_age", "must be greater than zero."));
        }

        problems.into_result(Self {
            enabled: raw.enabled.unwrap_or(defaults.enabled),
            allow_origins: raw.allow_origins.unwrap_or(defaults.allow_origins),
            allow_origin_regex,
            allow_methods: raw.allow_methods.unwrap_or(defaults.allow_methods),
            allow_headers: raw.allow_headers.unwrap_or(defaults.allow_headers),
            allow_credentials: raw.allow_credentials.unwrap_or(defaults.allow_credentials),
            expose_headers: raw.expose_headers.unwrap_or(defaults.expose_headers),
            max_age,
        })
    }
}

/// Response compression settings for the engine's HTTP server.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ServerCompressionConfig")]
pub struct RawServerCompressionConfig {
    pub enabled: Option<bool>,

    /// Minimum response size in bytes before compression is applied.
    pub min_size: Option<ByteSize>,

    pub zstd: Option<bool>,
    pub zstd_level: Option<i64>,
    pub brotli: Option<bool>,
    pub brotli_quality: Option<i64>,
    pub gzip: Option<bool>,
    pub gzip_level: Option<i64>,
}

/// Validated response compression settings for the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerCompressionConfig {
    pub enabled: bool,
    pub min_size: ByteSize,
    pub zstd: bool,
    pub zstd_level: i64,
    pub brotli: bool,
    pub brotli_quality: i64,
    pub gzip: bool,
    pub gzip_level: i64,
}

impl Default for ServerCompressionConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            min_size: ByteSize::new(500),
            zstd: true,
            zstd_level: 1,
            brotli: true,
            brotli_quality: 4,
            gzip: true,
            gzip_level: 1,
        }
    }
}

/// Validate a compression level against its codec's range.
fn validate_level(
    value: Option<i64>,
    default: i64,
    field: &str,
    range: std::ops::RangeInclusive<i64>,
    problems: &mut Problems,
) -> i64 {
    let value = value.unwrap_or(default);
    if !range.contains(&value) {
        problems.push(Problem::new(
            field,
            format!("must be between {} and {}.", range.start(), range.end()),
        ));
    }

    value
}

impl TryFrom<RawServerCompressionConfig> for ServerCompressionConfig {
    type Error = Problems;

    fn try_from(raw: RawServerCompressionConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        let mut problems = Problems::default();

        let zstd_level = validate_level(
            raw.zstd_level,
            defaults.zstd_level,
            "zstd_level",
            1..=22,
            &mut problems,
        );
        let brotli_quality = validate_level(
            raw.brotli_quality,
            defaults.brotli_quality,
            "brotli_quality",
            0..=11,
            &mut problems,
        );
        let gzip_level = validate_level(
            raw.gzip_level,
            defaults.gzip_level,
            "gzip_level",
            0..=9,
            &mut problems,
        );

        problems.into_result(Self {
            enabled: raw.enabled.unwrap_or(defaults.enabled),
            min_size: raw.min_size.unwrap_or(defaults.min_size),
            zstd: raw.zstd.unwrap_or(defaults.zstd),
            zstd_level,
            brotli: raw.brotli.unwrap_or(defaults.brotli),
            brotli_quality,
            gzip: raw.gzip.unwrap_or(defaults.gzip),
            gzip_level,
        })
    }
}

/// Configuration for the engine's HTTP server.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ServerConfig")]
pub struct RawServerConfig {
    /// Address the server binds to.
    pub host: Option<String>,

    /// Port the server listens on, omit to disable the server.
    pub port: Option<u16>,

    pub ssl: Option<RawServerSslConfig>,
    pub authentication: Option<RawServerAuthenticationConfig>,
    pub cors: Option<RawServerCorsConfig>,
    pub compression: Option<RawServerCompressionConfig>,
}

/// Validated configuration for the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerConfig {
    pub host: String,
    pub port: Option<u16>,
    pub ssl: Option<ServerSslConfig>,
    pub authentication: Option<ServerAuthenticationConfig>,
    pub cors: Option<ServerCorsConfig>,
    pub compression: Option<ServerCompressionConfig>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: "0.0.0.0".to_string(),
            port: None,
            ssl: None,
            authentication: None,
            cors: None,
            compression: None,
        }
    }
}

/// Validate an optional nested section, nesting its problems under the section name.
fn validate_nested<Raw, Validated>(
    raw: Option<Raw>,
    section: &str,
    problems: &mut Problems,
) -> Option<Validated>
where
    Validated: TryFrom<Raw, Error = Problems>,
{
    let raw = raw?;
    match Validated::try_from(raw) {
        Ok(validated) => Some(validated),
        Err(nested) => {
            problems.absorb(nested, section);
            None
        }
    }
}

impl TryFrom<RawServerConfig> for ServerConfig {
    type Error = Problems;

    fn try_from(raw: RawServerConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();

        let host = raw.host.unwrap_or_else(|| "0.0.0.0".to_string());
        if host.parse::<IpAddr>().is_err() {
            problems.push(Problem::new(
                "host",
                format!("{host:?} is not a valid IPv4 or IPv6 address."),
            ));
        }

        let ssl = validate_nested(raw.ssl, "ssl", &mut problems);
        let authentication = validate_nested(raw.authentication, "authentication", &mut problems);
        let cors = validate_nested(raw.cors, "cors", &mut problems);
        let compression = validate_nested(raw.compression, "compression", &mut problems);

        problems.into_result(Self {
            host,
            port: raw.port,
            ssl,
            authentication,
            cors,
            compression,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_server_sections_validate() {
        let raw: RawServerConfig = yaml_serde::from_str(
            "host: 127.0.0.1\nport: 8080\nauthentication:\n  secret: hunter2\n  duration: PT1H\n\
             cors:\n  allow_origins: '*'\ncompression:\n  min_size: 1KiB\n",
        )
        .unwrap();

        let config = ServerConfig::try_from(raw).unwrap();
        assert_eq!(config.host, "127.0.0.1");
        let authentication = config.authentication.unwrap();
        assert_eq!(authentication.secret, "hunter2");
        assert_eq!(authentication.duration, TimeDelta::from_secs(3600));
        assert_eq!(
            config.cors.unwrap().allow_origins,
            MaybeSequence::One("*".to_string())
        );
        assert_eq!(config.compression.unwrap().min_size.bytes(), 1024);
    }

    #[test]
    fn problems_nest_under_their_sections() {
        let raw: RawServerConfig = yaml_serde::from_str(
            "host: not-an-ip\nauthentication:\n  secret: ''\ncompression:\n  zstd_level: 99\n",
        )
        .unwrap();

        let problems = ServerConfig::try_from(raw).unwrap_err();
        let locations: Vec<&str> = problems
            .0
            .iter()
            .map(|problem| problem.location.as_str())
            .collect();
        assert_eq!(
            locations,
            ["host", "authentication.secret", "compression.zstd_level"]
        );
    }

    #[test]
    fn ssl_versions_default_to_the_tls_server_protocol() {
        let config = ServerSslConfig::try_from(RawServerSslConfig::default()).unwrap();
        assert_eq!(config.version, Some(TLS_SERVER_PROTOCOL));
    }

    #[test]
    fn bad_origin_patterns_are_rejected() {
        let raw: RawServerCorsConfig = yaml_serde::from_str("allow_origin_regex: '('\n").unwrap();
        let problems = ServerCorsConfig::try_from(raw).unwrap_err();
        assert_eq!(problems.0[0].location, "allow_origin_regex");
    }
}
