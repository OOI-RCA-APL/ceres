//! The HTTP server configuration section.

use std::net::IpAddr;
use std::path::PathBuf;

use ceres_macros::kebab_aliases;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::values::{ByteSize, MaybeSequence, TimeDelta};

/// Where `ceres generate certificate` writes the certificate, relative to the project
/// directory.
pub const DEFAULT_TLS_CERT: &str = ".ceres/tls/server.crt";

/// Where `ceres generate certificate` writes the private key, relative to the project
/// directory.
pub const DEFAULT_TLS_KEY: &str = ".ceres/tls/server.key";

/// The lowest TLS version the HTTPS server negotiates.
///
/// Written as the string `"1.2"` or `"1.3"`. YAML reads either unquoted as a number,
/// which is refused.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub enum TlsVersion {
    #[default]
    #[serde(rename = "1.2")]
    Tls12,
    #[serde(rename = "1.3")]
    Tls13,
}

/// The HTTPS listener of the engine's HTTP server.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerHttpsConfig")]
pub struct RawServerHttpsConfig {
    /// Port the HTTPS listener binds, 443 when omitted.
    pub port: Option<u16>,

    /// Path to the PEM certificate chain, `.ceres/tls/server.crt` when omitted.
    pub cert: Option<PathBuf>,

    /// Path to the PEM private key, `.ceres/tls/server.key` when omitted.
    pub key: Option<PathBuf>,

    /// Password for an encrypted private key.
    pub key_password: Option<String>,

    /// Lowest TLS version offered, `"1.2"` or `"1.3"`, `"1.2"` when omitted.
    pub min_version: Option<TlsVersion>,
}

/// Validated HTTPS listener of the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerHttpsConfig {
    pub port: u16,
    pub cert: PathBuf,
    pub key: PathBuf,
    pub key_password: Option<String>,
    pub min_version: TlsVersion,
}

impl Default for ServerHttpsConfig {
    fn default() -> Self {
        Self {
            port: 443,
            cert: DEFAULT_TLS_CERT.into(),
            key: DEFAULT_TLS_KEY.into(),
            key_password: None,
            min_version: TlsVersion::default(),
        }
    }
}

impl TryFrom<RawServerHttpsConfig> for ServerHttpsConfig {
    type Error = Problems;

    fn try_from(raw: RawServerHttpsConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        Ok(Self {
            port: raw.port.unwrap_or(defaults.port),
            cert: raw.cert.unwrap_or(defaults.cert),
            key: raw.key.unwrap_or(defaults.key),
            key_password: raw.key_password,
            min_version: raw.min_version.unwrap_or(defaults.min_version),
        })
    }
}

/// The plain HTTP listener of the engine's HTTP server.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerHttpConfig")]
pub struct RawServerHttpConfig {
    /// Port the plain HTTP listener binds, 80 when omitted.
    pub port: Option<u16>,

    /// Whether the listener answers every request with a temporary redirect to the same path
    /// on the HTTPS listener rather than serving it, needs `https`.
    pub redirect: Option<bool>,
}

/// Validated plain HTTP listener of the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerHttpConfig {
    pub port: u16,
    pub redirect: bool,
}

impl Default for ServerHttpConfig {
    fn default() -> Self {
        Self {
            port: 80,
            redirect: false,
        }
    }
}

impl TryFrom<RawServerHttpConfig> for ServerHttpConfig {
    type Error = Problems;

    fn try_from(raw: RawServerHttpConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        Ok(Self {
            port: raw.port.unwrap_or(defaults.port),
            redirect: raw.redirect.unwrap_or(defaults.redirect),
        })
    }
}

/// Authentication settings for the engine's HTTP server.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
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
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
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
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
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
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerConfig")]
pub struct RawServerConfig {
    /// Address both listeners bind, `0.0.0.0` when omitted.
    pub bind: Option<String>,

    /// HTTPS listener. The server is off when neither `https` nor `http` is set.
    pub https: Option<RawServerHttpsConfig>,

    /// Plain HTTP listener. The server is off when neither `https` nor `http` is set.
    pub http: Option<RawServerHttpConfig>,

    pub authentication: Option<RawServerAuthenticationConfig>,
    pub cors: Option<RawServerCorsConfig>,
    pub compression: Option<RawServerCompressionConfig>,
}

/// Validated configuration for the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerConfig {
    pub bind: String,
    pub https: Option<ServerHttpsConfig>,
    pub http: Option<ServerHttpConfig>,
    pub authentication: Option<ServerAuthenticationConfig>,
    pub cors: Option<ServerCorsConfig>,
    pub compression: Option<ServerCompressionConfig>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            bind: "0.0.0.0".to_string(),
            https: None,
            http: None,
            authentication: None,
            cors: None,
            compression: None,
        }
    }
}

impl ServerConfig {
    /// The listener serving the console and API that a browser should open, HTTPS when
    /// configured, `None` when the server is off.
    pub fn console_listener(&self) -> Option<(&'static str, u16)> {
        match (&self.https, &self.http) {
            (Some(https), _) => Some(("https", https.port)),
            (None, Some(http)) => Some(("http", http.port)),
            (None, None) => None,
        }
    }

    /// Whether the plain HTTP listener serves the console and API rather than redirecting.
    pub fn http_serves(&self) -> bool {
        self.http.as_ref().is_some_and(|http| !http.redirect)
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

        let bind = raw.bind.unwrap_or_else(|| "0.0.0.0".to_string());
        if bind.parse::<IpAddr>().is_err() {
            problems.push(Problem::new(
                "bind",
                format!("{bind:?} is not a valid IPv4 or IPv6 address."),
            ));
        }

        let https: Option<ServerHttpsConfig> = validate_nested(raw.https, "https", &mut problems);
        let http: Option<ServerHttpConfig> = validate_nested(raw.http, "http", &mut problems);
        let authentication = validate_nested(raw.authentication, "authentication", &mut problems);
        let cors = validate_nested(raw.cors, "cors", &mut problems);
        let compression = validate_nested(raw.compression, "compression", &mut problems);

        if let Some(http) = &http {
            // A redirect to a plain HTTP origin would loop, so the HTTPS listener must exist.
            if http.redirect && https.is_none() {
                problems.push(Problem::new(
                    "http.redirect",
                    "needs `https`, the redirect target is the HTTPS listener.",
                ));
            }
            // Port 0 asks the OS for a free port, so both listeners may request one.
            if let Some(https) = &https
                && http.port == https.port
                && http.port != 0
            {
                problems.push(Problem::new("http.port", "must differ from `https.port`."));
            }
        }

        problems.into_result(Self {
            bind,
            https,
            http,
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
            "bind: 127.0.0.1\nhttp:\n  port: 8080\nauthentication:\n  secret: hunter2\n  duration: PT1H\n\
             cors:\n  allow_origins: '*'\ncompression:\n  min_size: 1KiB\n",
        )
        .unwrap();

        let config = ServerConfig::try_from(raw).unwrap();
        assert_eq!(config.bind, "127.0.0.1");
        assert_eq!(config.console_listener(), Some(("http", 8080)));
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
    fn multi_word_keys_read_in_either_spelling() {
        // A configuration file is written in kebab-case, and the snake_case spelling
        // stays readable so a file written either way loads.
        let document = |separator: char| {
            let key = |name: &str| name.replace('_', &separator.to_string());
            format!(
                "cors:\n  {}: '*'\n  {}: true\ncompression:\n  {}: 1KiB\n",
                key("allow_origins"),
                key("allow_credentials"),
                key("min_size"),
            )
        };

        for separator in ['-', '_'] {
            let raw: RawServerConfig = yaml_serde::from_str(&document(separator))
                .unwrap_or_else(|error| panic!("the {separator:?} spelling reads: {error}"));
            let config = ServerConfig::try_from(raw).unwrap();
            let cors = config.cors.unwrap();
            assert_eq!(cors.allow_origins, MaybeSequence::One("*".to_string()));
            assert!(cors.allow_credentials);
            assert_eq!(config.compression.unwrap().min_size.bytes(), 1024);
        }
    }

    #[test]
    fn problems_nest_under_their_sections() {
        let raw: RawServerConfig = yaml_serde::from_str(
            "bind: not-an-ip\nauthentication:\n  secret: ''\ncompression:\n  zstd_level: 99\n",
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
            ["bind", "authentication.secret", "compression.zstd_level"]
        );
    }

    /// Read and validate a `server` section.
    fn server(document: &str) -> Result<ServerConfig, Problems> {
        let raw: RawServerConfig = yaml_serde::from_str(document).unwrap();
        ServerConfig::try_from(raw)
    }

    /// The location of the one problem a `server` section has.
    fn problem_location(document: &str) -> String {
        let problems = server(document).unwrap_err();
        assert_eq!(problems.0.len(), 1);
        problems.0[0].location.clone()
    }

    #[test]
    fn empty_listener_sections_take_the_defaults() {
        let config = server("https: {}\nhttp: {}\n").unwrap();
        assert_eq!(config.https, Some(ServerHttpsConfig::default()));
        assert_eq!(config.http, Some(ServerHttpConfig::default()));
        let https = config.https.unwrap();
        assert_eq!(https.port, 443);
        assert_eq!(https.cert, PathBuf::from(".ceres/tls/server.crt"));
        assert_eq!(https.key, PathBuf::from(".ceres/tls/server.key"));
        assert_eq!(https.min_version, TlsVersion::Tls12);
        assert_eq!(config.http.unwrap().port, 80);
    }

    #[test]
    fn the_console_listener_prefers_https() {
        assert_eq!(server("").unwrap().console_listener(), None);
        assert_eq!(
            server("http:\n  port: 8080\n").unwrap().console_listener(),
            Some(("http", 8080))
        );
        let both = server("https:\n  port: 8443\nhttp:\n  port: 8080\n").unwrap();
        assert_eq!(both.console_listener(), Some(("https", 8443)));
        assert!(both.http_serves());
        let redirecting =
            server("https:\n  port: 8443\nhttp:\n  port: 8080\n  redirect: true\n").unwrap();
        assert!(!redirecting.http_serves());
    }

    #[test]
    fn min_versions_are_strings() {
        // Through a parsed document, as configuration loads, where an unquoted `1.3` is
        // already a number.
        let version = |text: &str| {
            let document: yaml_serde::Value =
                yaml_serde::from_str(&format!("https:\n  min-version: {text}\n")).unwrap();
            yaml_serde::from_value::<RawServerConfig>(document)
                .map(|raw| raw.https.unwrap().min_version.unwrap())
                .map_err(|error| error.to_string())
        };
        assert_eq!(version("'1.2'"), Ok(TlsVersion::Tls12));
        assert_eq!(version("\"1.3\""), Ok(TlsVersion::Tls13));
        for refused in ["1.3", "'1.1'"] {
            assert!(version(refused).is_err(), "{refused}");
        }
    }

    #[test]
    fn redirects_need_a_distinct_https_listener() {
        assert_eq!(
            problem_location("http:\n  redirect: true\n"),
            "http.redirect"
        );
        assert_eq!(
            problem_location("https:\n  port: 8443\nhttp:\n  port: 8443\n"),
            "http.port"
        );
        // Zero asks each listener for its own ephemeral port.
        assert!(server("https:\n  port: 0\nhttp:\n  port: 0\n  redirect: true\n").is_ok());
    }

    #[test]
    fn unknown_server_keys_are_rejected() {
        for document in [
            "host: 127.0.0.1\n",
            "port: 8080\n",
            "ssl:\n  key: k\n",
            "https-redirect: true\n",
            "https:\n  ssl-version: 17\n",
        ] {
            let result: Result<RawServerConfig, _> = yaml_serde::from_str(document);
            assert!(result.is_err(), "{document:?} reads");
        }
    }

    #[test]
    fn bad_origin_patterns_are_rejected() {
        let raw: RawServerCorsConfig = yaml_serde::from_str("allow_origin_regex: '('\n").unwrap();
        let problems = ServerCorsConfig::try_from(raw).unwrap_err();
        assert_eq!(problems.0[0].location, "allow_origin_regex");
    }
}
