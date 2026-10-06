//! The HTTP server configuration section.

use std::net::IpAddr;
use std::path::{Component, Path, PathBuf};

use ceres_macros::kebab_aliases;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::values::{ByteSize, MaybeSequence, TimeDelta};

/// Where the HTTPS certificate lives when `certificate.path` is omitted, relative to the
/// project directory.
pub const DEFAULT_TLS_CERT: &str = ".ceres/tls/server.crt";

/// Where the HTTPS private key lives when `certificate.key` is omitted, relative to the
/// project directory.
pub const DEFAULT_TLS_KEY: &str = ".ceres/tls/server.key";

/// Where the certificate authority signing managed certificates lives when `auto.ca` is
/// omitted, relative to the project directory.
pub const DEFAULT_TLS_CA_CERT: &str = ".ceres/tls/ca.crt";

/// Where the certificate authority's private key lives when `auto.ca` is omitted, relative
/// to the project directory.
pub const DEFAULT_TLS_CA_KEY: &str = ".ceres/tls/ca.key";

/// How many days a managed certificate stays valid when `auto.days` is omitted.
pub const DEFAULT_CERTIFICATE_DAYS: u32 = 365;

/// The longest validity in days a managed certificate may have. Apple platforms reject a
/// server certificate valid for longer.
pub const MAX_CERTIFICATE_DAYS: u32 = 825;

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

/// A certificate authority you supply to sign the managed HTTPS certificate.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerCertificateAuthorityConfig")]
pub struct RawServerCertificateAuthorityConfig {
    /// Path to the authority's PEM certificate, `.ceres/tls/ca.crt` when omitted. Ceres never
    /// creates it.
    pub path: Option<PathBuf>,

    /// Path to the authority's PEM private key, `.ceres/tls/ca.key` when omitted.
    pub key: Option<PathBuf>,

    /// Password for an encrypted authority key.
    pub key_password: Option<String>,
}

/// Validated certificate authority signing the managed HTTPS certificate.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerCertificateAuthorityConfig {
    pub path: PathBuf,
    pub key: PathBuf,
    pub key_password: Option<String>,
}

impl Default for ServerCertificateAuthorityConfig {
    fn default() -> Self {
        Self {
            path: DEFAULT_TLS_CA_CERT.into(),
            key: DEFAULT_TLS_CA_KEY.into(),
            key_password: None,
        }
    }
}

impl TryFrom<RawServerCertificateAuthorityConfig> for ServerCertificateAuthorityConfig {
    type Error = Problems;

    fn try_from(raw: RawServerCertificateAuthorityConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        Ok(Self {
            path: raw.path.unwrap_or(defaults.path),
            key: raw.key.unwrap_or(defaults.key),
            key_password: raw.key_password,
        })
    }
}

/// How Ceres issues and renews the HTTPS certificate it manages.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerCertificateAutoConfig")]
pub struct RawServerCertificateAutoConfig {
    /// IP addresses the certificate names. With `dns` also omitted, the certificate names
    /// localhost, 127.0.0.1, ::1, the hostname, and every non-loopback interface address.
    pub ip: Option<Vec<IpAddr>>,

    /// DNS names the certificate names. With `ip` also omitted, the certificate names the
    /// detected ones.
    pub dns: Option<Vec<String>>,

    /// Days each issued certificate stays valid, 365 when omitted and at most 825.
    pub days: Option<u32>,

    /// Certificate authority you supply to sign the certificate, whose files must exist.
    /// When omitted, Ceres creates one at `.ceres/tls/ca.crt` and `.ceres/tls/ca.key`.
    pub ca: Option<RawServerCertificateAuthorityConfig>,
}

/// Validated issuance settings of the managed HTTPS certificate.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerCertificateAutoConfig {
    pub ip: Vec<IpAddr>,
    pub dns: Vec<String>,
    pub days: u32,
    /// The authority you supply, `None` for the one Ceres creates at the default paths.
    pub ca: Option<ServerCertificateAuthorityConfig>,
}

impl Default for ServerCertificateAutoConfig {
    fn default() -> Self {
        Self {
            ip: Vec::new(),
            dns: Vec::new(),
            days: DEFAULT_CERTIFICATE_DAYS,
            ca: None,
        }
    }
}

impl ServerCertificateAutoConfig {
    /// Whether the certificate names the machine's detected names, which it does when
    /// neither `ip` nor `dns` lists any.
    pub fn detects_names(&self) -> bool {
        self.ip.is_empty() && self.dns.is_empty()
    }

    /// The authority signing the certificate, the one Ceres creates when none is supplied.
    pub fn authority(&self) -> ServerCertificateAuthorityConfig {
        self.ca.clone().unwrap_or_default()
    }
}

impl TryFrom<RawServerCertificateAutoConfig> for ServerCertificateAutoConfig {
    type Error = Problems;

    fn try_from(raw: RawServerCertificateAutoConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();

        let dns = raw.dns.unwrap_or_default();
        for name in &dns {
            let valid = !name.is_empty()
                && name.chars().all(|character| {
                    character.is_ascii_alphanumeric() || "-.*".contains(character)
                });
            if !valid {
                problems.push(Problem::new("dns", format!("{name:?} is not a DNS name.")));
            }
        }

        let days = raw.days.unwrap_or(DEFAULT_CERTIFICATE_DAYS);
        if !(1..=MAX_CERTIFICATE_DAYS).contains(&days) {
            problems.push(Problem::new(
                "days",
                format!("must be between 1 and {MAX_CERTIFICATE_DAYS}."),
            ));
        }

        let ca = validate_nested(raw.ca, "ca", &mut problems);
        problems.into_result(Self {
            ip: raw.ip.unwrap_or_default(),
            dns,
            days,
            ca,
        })
    }
}

/// The certificate the HTTPS listener presents.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerCertificateConfig")]
pub struct RawServerCertificateConfig {
    /// Path to the PEM certificate chain, `.ceres/tls/server.crt` when omitted.
    pub path: Option<PathBuf>,

    /// Path to the PEM private key, `.ceres/tls/server.key` when omitted.
    pub key: Option<PathBuf>,

    /// Password for an encrypted private key, not allowed with `auto`.
    pub key_password: Option<String>,

    /// Whether Ceres issues and renews the certificate itself, `true` or the issuance
    /// settings. Ceres then owns both files.
    #[serde(deserialize_with = "auto_or_settings")]
    #[schemars(schema_with = "auto_schema")]
    pub auto: Option<RawServerCertificateAutoConfig>,
}

/// Validated certificate the HTTPS listener presents.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerCertificateConfig {
    pub path: PathBuf,
    pub key: PathBuf,
    pub key_password: Option<String>,
    pub auto: Option<ServerCertificateAutoConfig>,
}

impl Default for ServerCertificateConfig {
    fn default() -> Self {
        Self {
            path: DEFAULT_TLS_CERT.into(),
            key: DEFAULT_TLS_KEY.into(),
            key_password: None,
            auto: None,
        }
    }
}

impl TryFrom<RawServerCertificateConfig> for ServerCertificateConfig {
    type Error = Problems;

    fn try_from(raw: RawServerCertificateConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        let mut problems = Problems::default();

        let auto = validate_nested(raw.auto, "auto", &mut problems);
        if raw.key_password.is_some() && auto.is_some() {
            problems.push(Problem::new(
                "key_password",
                "cannot be combined with `auto`, which writes the key unencrypted.",
            ));
        }

        let path = raw.path.unwrap_or(defaults.path);
        let key = raw.key.unwrap_or(defaults.key);
        // Each file holds one thing, and a managed certificate would overwrite the other.
        let authority = auto.as_ref().map(ServerCertificateAutoConfig::authority);
        let mut files = vec![("path", &path), ("key", &key)];
        if let Some(authority) = &authority {
            files.extend([
                ("auto.ca.path", &authority.path),
                ("auto.ca.key", &authority.key),
            ]);
        }
        for (index, (location, file)) in files.iter().enumerate() {
            let earlier = files[..index]
                .iter()
                .find(|(_, earlier)| lexical(earlier) == lexical(file));
            if let Some((other, _)) = earlier {
                problems.push(Problem::new(
                    *location,
                    format!("is {}, the same file as `{other}`.", file.display()),
                ));
            }
        }

        problems.into_result(Self {
            path,
            key,
            key_password: raw.key_password,
            auto,
        })
    }
}

/// `path` with `.` dropped and `..` folded into the component before it, so spellings of
/// one file compare equal without touching the filesystem.
fn lexical(path: &Path) -> PathBuf {
    let mut lexical = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir
                if matches!(lexical.components().next_back(), Some(Component::Normal(_))) =>
            {
                lexical.pop();
            }
            component => lexical.push(component),
        }
    }

    lexical
}

/// Read `auto` as `true`, `false`, or the issuance settings.
fn auto_or_settings<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<RawServerCertificateAutoConfig>, D::Error> {
    struct Visitor;

    impl<'de> serde::de::Visitor<'de> for Visitor {
        type Value = Option<RawServerCertificateAutoConfig>;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("`true`, `false`, or a mapping of issuance settings")
        }

        fn visit_bool<E: serde::de::Error>(self, enabled: bool) -> Result<Self::Value, E> {
            Ok(enabled.then(RawServerCertificateAutoConfig::default))
        }

        fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
            Ok(None)
        }

        fn visit_none<E: serde::de::Error>(self) -> Result<Self::Value, E> {
            Ok(None)
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(self, map: A) -> Result<Self::Value, A::Error> {
            Deserialize::deserialize(serde::de::value::MapAccessDeserializer::new(map)).map(Some)
        }
    }

    deserializer.deserialize_any(Visitor)
}

fn auto_schema(generator: &mut schemars::SchemaGenerator) -> schemars::Schema {
    let settings = generator.subschema_for::<RawServerCertificateAutoConfig>();
    schemars::json_schema!({ "anyOf": [{ "type": "boolean" }, settings] })
}

/// Read `certificate` as the shorthand `auto` or the certificate settings.
fn certificate_or_auto<'de, D: serde::Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<RawServerCertificateConfig>, D::Error> {
    struct Visitor;

    impl<'de> serde::de::Visitor<'de> for Visitor {
        type Value = Option<RawServerCertificateConfig>;

        fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            formatter.write_str("`auto` or a mapping of certificate settings")
        }

        fn visit_str<E: serde::de::Error>(self, text: &str) -> Result<Self::Value, E> {
            if text != "auto" {
                return Err(E::invalid_value(serde::de::Unexpected::Str(text), &self));
            }

            Ok(Some(RawServerCertificateConfig {
                auto: Some(RawServerCertificateAutoConfig::default()),
                ..RawServerCertificateConfig::default()
            }))
        }

        fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
            Ok(None)
        }

        fn visit_none<E: serde::de::Error>(self) -> Result<Self::Value, E> {
            Ok(None)
        }

        fn visit_map<A: serde::de::MapAccess<'de>>(self, map: A) -> Result<Self::Value, A::Error> {
            Deserialize::deserialize(serde::de::value::MapAccessDeserializer::new(map)).map(Some)
        }
    }

    deserializer.deserialize_any(Visitor)
}

fn certificate_schema(generator: &mut schemars::SchemaGenerator) -> schemars::Schema {
    let settings = generator.subschema_for::<RawServerCertificateConfig>();
    schemars::json_schema!({ "anyOf": [{ "enum": ["auto"] }, settings] })
}

/// The HTTPS listener of the engine's HTTP server.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerHttpsConfig")]
pub struct RawServerHttpsConfig {
    /// Port the HTTPS listener binds, 443 when omitted.
    pub port: Option<u16>,

    /// Certificate the listener presents, read from `.ceres/tls/server.crt` and
    /// `.ceres/tls/server.key` when omitted. `auto` has Ceres issue and renew it.
    #[serde(deserialize_with = "certificate_or_auto")]
    #[schemars(schema_with = "certificate_schema")]
    pub certificate: Option<RawServerCertificateConfig>,

    /// Lowest TLS version offered, `"1.2"` or `"1.3"`, `"1.2"` when omitted.
    pub min_version: Option<TlsVersion>,
}

/// Validated HTTPS listener of the engine's HTTP server.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerHttpsConfig {
    pub port: u16,
    pub certificate: ServerCertificateConfig,
    pub min_version: TlsVersion,
}

impl Default for ServerHttpsConfig {
    fn default() -> Self {
        Self {
            port: 443,
            certificate: ServerCertificateConfig::default(),
            min_version: TlsVersion::default(),
        }
    }
}

impl TryFrom<RawServerHttpsConfig> for ServerHttpsConfig {
    type Error = Problems;

    fn try_from(raw: RawServerHttpsConfig) -> Result<Self, Problems> {
        let defaults = Self::default();
        let mut problems = Problems::default();
        let certificate = match raw.certificate {
            Some(certificate) => validate_nested(Some(certificate), "certificate", &mut problems),
            None => Some(defaults.certificate),
        };

        problems.into_result(Self {
            port: raw.port.unwrap_or(defaults.port),
            certificate: certificate.unwrap_or_default(),
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
        assert_eq!(
            https.certificate.path,
            PathBuf::from(".ceres/tls/server.crt")
        );
        assert_eq!(
            https.certificate.key,
            PathBuf::from(".ceres/tls/server.key")
        );
        assert_eq!(https.certificate.auto, None);
        assert_eq!(https.min_version, TlsVersion::Tls12);
        assert_eq!(config.http.unwrap().port, 80);
    }

    /// The `certificate` of a validated `https: {certificate: ...}` section.
    fn certificate(written: &str) -> Result<ServerCertificateConfig, Problems> {
        server(&format!("https:\n  certificate: {written}\n"))
            .map(|config| config.https.unwrap().certificate)
    }

    #[test]
    fn auto_certificates_take_the_shorthand_or_settings() {
        let managed = ServerCertificateConfig {
            auto: Some(ServerCertificateAutoConfig::default()),
            ..ServerCertificateConfig::default()
        };
        assert_eq!(certificate("auto"), Ok(managed.clone()));
        assert_eq!(certificate("{auto: true}"), Ok(managed.clone()));
        assert_eq!(certificate("{auto: {}}"), Ok(managed));
        assert_eq!(
            certificate("{auto: false}"),
            Ok(ServerCertificateConfig::default())
        );
        for refused in [
            "manual",
            "true",
            "{auto: yes-please}",
            "{auto: {days: 30, typo: 1}}",
            "{cert: a.crt}",
        ] {
            let document = format!("https:\n  certificate: {refused}\n");
            let read = yaml_serde::from_str::<RawServerConfig>(&document);
            assert!(read.is_err(), "{refused:?} reads");
        }

        let settings = certificate(
            "\n    path: certs/site.crt\n    key: certs/site.key\n    auto:\n      ip: \
             [10.20.1.230, '::1']\n      dns: [camctrl.local]\n      days: 825\n      ca:\n        \
             key-password: hunter2\n",
        )
        .unwrap();
        assert_eq!(settings.path, PathBuf::from("certs/site.crt"));
        let auto = settings.auto.unwrap();
        assert_eq!(
            auto.ip,
            [
                "10.20.1.230".parse::<IpAddr>().unwrap(),
                "::1".parse().unwrap()
            ]
        );
        assert_eq!(auto.dns, ["camctrl.local"]);
        assert_eq!(auto.days, 825);
        assert!(!auto.detects_names());
        // A supplied authority keeps the default paths it omits.
        let ca = auto.ca.clone().unwrap();
        assert_eq!(ca.path, PathBuf::from(".ceres/tls/ca.crt"));
        assert_eq!(ca.key_password.as_deref(), Some("hunter2"));
        assert_eq!(auto.authority(), ca);
    }

    #[test]
    fn omitted_names_and_authorities_are_detected_and_created() {
        let auto = certificate("auto").unwrap().auto.unwrap();
        assert!(auto.detects_names());
        assert_eq!(auto.days, 365);
        assert_eq!(auto.ca, None);
        assert_eq!(
            auto.authority(),
            ServerCertificateAuthorityConfig {
                path: ".ceres/tls/ca.crt".into(),
                key: ".ceres/tls/ca.key".into(),
                key_password: None,
            }
        );
    }

    #[test]
    fn auto_certificates_refuse_what_they_cannot_issue() {
        let location = |written: &str| {
            let problems = certificate(written).unwrap_err();
            assert_eq!(problems.0.len(), 1, "{problems:?}");
            problems.0[0].location.clone()
        };
        // An unencrypted key is all `auto` writes, so a password could never apply.
        assert_eq!(
            location("{key-password: hunter2, auto: true}"),
            "https.certificate.key_password"
        );
        assert_eq!(location("{auto: {days: 0}}"), "https.certificate.auto.days");
        assert_eq!(
            location("{auto: {days: 826}}"),
            "https.certificate.auto.days"
        );
        assert!(certificate("{auto: {days: 1}}").is_ok());
        assert_eq!(
            location("{auto: {dns: ['bad name']}}"),
            "https.certificate.auto.dns"
        );
        assert_eq!(
            location("{auto: {dns: ['']}}"),
            "https.certificate.auto.dns"
        );
        // Without `auto`, the password decrypts a key the user wrote.
        assert!(certificate("{key-password: hunter2}").is_ok());
    }

    #[test]
    fn certificate_files_must_not_collide() {
        let problems = |written: &str| -> Vec<(String, String)> {
            certificate(written)
                .unwrap_err()
                .0
                .into_iter()
                .map(|problem| (problem.location, problem.message))
                .collect()
        };
        assert_eq!(
            problems("{path: tls/site.pem, key: ./tls/site.pem}"),
            [(
                "https.certificate.key".to_string(),
                "is ./tls/site.pem, the same file as `path`.".to_string()
            )]
        );
        // The defaults count, and so do spellings that fold to the same file.
        assert_eq!(
            problems("{auto: {ca: {path: .ceres/tls/server.crt}}}"),
            [(
                "https.certificate.auto.ca.path".to_string(),
                "is .ceres/tls/server.crt, the same file as `path`.".to_string()
            )]
        );
        assert_eq!(
            problems("{auto: {ca: {path: ca/x/../ca.pem, key: ca/ca.pem}}}"),
            [(
                "https.certificate.auto.ca.key".to_string(),
                "is ca/ca.pem, the same file as `auto.ca.path`.".to_string()
            )]
        );
        assert_eq!(
            problems("{key: .ceres/tls/ca.key, auto: true}"),
            [(
                "https.certificate.auto.ca.key".to_string(),
                "is .ceres/tls/ca.key, the same file as `key`.".to_string()
            )]
        );
        // The authority's paths only matter when Ceres manages the certificate.
        assert!(certificate("{key: .ceres/tls/ca.key}").is_ok());
        assert!(certificate("{path: a/b.crt, key: b.crt}").is_ok());
    }

    #[test]
    fn validated_certificates_read_back_as_written() {
        // A Python instance passes back through its raw form, so a validated section must
        // serialize into a raw one meaning the same thing.
        for written in [
            "auto",
            "{path: a.crt, key: a.key, key-password: p}",
            "{auto: {ip: ['10.0.0.1'], days: 30, ca: {path: ca.pem}}}",
        ] {
            let validated = certificate(written).unwrap();
            let value = yaml_serde::to_value(&validated).unwrap();
            let raw: RawServerCertificateConfig = yaml_serde::from_value(value).unwrap();
            assert_eq!(ServerCertificateConfig::try_from(raw), Ok(validated));
        }
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
            "https:\n  cert: server.crt\n",
            "https:\n  key: server.key\n",
            "https:\n  key-password: hunter2\n",
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
