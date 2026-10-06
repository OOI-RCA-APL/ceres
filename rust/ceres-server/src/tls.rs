//! TLS configuration loading.
//!
//! Builds a rustls server configuration from the `server.https` config section. Encrypted
//! private keys decrypt with `key-password`. Under `certificate.auto` Ceres issues the
//! certificate itself, renews it while serving, and swaps it in without a restart.

mod managed;

use std::path::Path;
use std::sync::{Arc, PoisonError, RwLock};
use std::time::Duration;

use ceres_config::{ServerCertificateConfig, ServerHttpsConfig, TlsVersion};
pub use managed::{
    Inspection, Managed, Renewal, SubjectName, authority_certificate, fingerprint, hostname,
    write_pair,
};
use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
use rustls::server::{ClientHello, ResolvesServerCert};
use rustls::sign::CertifiedKey;
use time::OffsetDateTime;

/// How often a listener with a managed certificate checks whether it is due for renewal.
pub const RENEWAL_INTERVAL: Duration = Duration::from_secs(24 * 60 * 60);

/// A TLS loading failure.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// A certificate or key the listener reads does not exist.
    #[error(
        "{path} does not exist. Run `ceres generate certificate` to write the certificate \
         {certificate} and key {key}, or set `certificate: auto` under `server.https` for \
         Ceres to manage them."
    )]
    Missing {
        path: String,
        certificate: String,
        key: String,
    },
    #[error("cannot read {path}. {source}")]
    Unreadable {
        path: String,
        source: std::io::Error,
    },
    #[error("{path} holds a certificate that cannot be parsed. {reason}")]
    Malformed { path: String, reason: String },
    #[error("{path} holds no usable PEM {expected}")]
    Empty {
        path: String,
        expected: &'static str,
    },
    /// A file that is not text, like a DER encoding, where PEM is expected.
    #[error("{path} is not text, expected a PEM {expected}")]
    NotPem {
        path: String,
        expected: &'static str,
    },
    #[error("cannot decrypt the private key. {0}")]
    Decrypt(String),
    #[error(transparent)]
    Rustls(#[from] rustls::Error),
    #[error(
        "{path} does not exist. Ceres never creates the certificate authority `auto.ca` names."
    )]
    AuthorityMissing { path: String },
    /// One file of the default authority exists without the other. Creating a new
    /// authority would replace the one clients already trust.
    #[error(
        "{present} exists without {missing}. Restore {missing}, or remove {present} for Ceres \
         to create a new certificate authority, which every client then has to trust again."
    )]
    AuthorityIncomplete { present: String, missing: String },
    #[error("cannot issue the certificate. {0}")]
    Issue(String),
    #[error("cannot write {path}. {source}")]
    Write {
        path: String,
        source: std::io::Error,
    },
}

/// Something worth the engine's log that happened to a managed certificate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Notice {
    Info(String),
    Warning(String),
}

/// Where a listener sends its [`Notice`]s.
pub type Report = Arc<dyn Fn(Notice) + Send + Sync>;

/// The certificate a listener presents, replaced in place when a managed one renews.
///
/// A handshake reads it once, so open connections keep the certificate they started with.
#[derive(Debug)]
pub struct Presented(RwLock<Arc<CertifiedKey>>);

impl Presented {
    fn new(key: Arc<CertifiedKey>) -> Arc<Self> {
        Arc::new(Self(RwLock::new(key)))
    }

    fn current(&self) -> Arc<CertifiedKey> {
        self.0
            .read()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    fn replace(&self, key: Arc<CertifiedKey>) {
        *self.0.write().unwrap_or_else(PoisonError::into_inner) = key;
    }
}

impl ResolvesServerCert for Presented {
    fn resolve(&self, _client_hello: ClientHello<'_>) -> Option<Arc<CertifiedKey>> {
        Some(self.current())
    }
}

/// A listener's TLS, its rustls configuration plus what renews a managed certificate.
pub struct Tls {
    pub config: Arc<rustls::ServerConfig>,
    renewer: Option<Renewer>,
}

impl Tls {
    /// Load the `https` section's certificate, first issuing a managed one when it is due.
    pub fn load(https: &ServerHttpsConfig, report: Report) -> Result<Self, Error> {
        Self::load_detecting(https, report, SubjectName::detected)
    }

    /// [`Self::load`], with `detect` answering the machine's names at every check.
    pub fn load_detecting(
        https: &ServerHttpsConfig,
        report: Report,
        detect: fn() -> Vec<SubjectName>,
    ) -> Result<Self, Error> {
        let renewer = https
            .certificate
            .auto
            .as_ref()
            .map(|_| -> Result<Renewer, Error> {
                let renewer = Renewer {
                    certificate: https.certificate.clone(),
                    presented: None,
                    detect,
                    report,
                };
                renewer.ensure()?;
                Ok(renewer)
            })
            .transpose()?;

        let presented = Presented::new(certified_key(&https.certificate)?);
        let config = server_config(https, presented.clone())?;
        Ok(Self {
            config,
            renewer: renewer.map(|renewer| Renewer {
                presented: Some(presented),
                ..renewer
            }),
        })
    }

    /// Renew a managed certificate every `interval` for as long as the future is polled.
    /// Without a managed certificate it waits forever.
    pub async fn renew_every(&self, interval: Duration) {
        let Some(renewer) = &self.renewer else {
            return std::future::pending().await;
        };

        loop {
            tokio::time::sleep(interval).await;
            renewer.renew();
        }
    }
}

/// What renews a managed certificate and swaps it into the listener.
struct Renewer {
    certificate: ServerCertificateConfig,
    presented: Option<Arc<Presented>>,
    detect: fn() -> Vec<SubjectName>,
    report: Report,
}

impl Renewer {
    /// Issue the certificate when it is due, reporting what was issued.
    fn ensure(&self) -> Result<Option<Managed>, Error> {
        let auto = self
            .certificate
            .auto
            .as_ref()
            .expect("a renewer exists for a managed certificate");
        let names = SubjectName::required(auto, self.detect);
        let managed = Managed::ensure(
            Path::new(""),
            &self.certificate,
            auto,
            &names,
            OffsetDateTime::now_utc(),
            false,
        )?;
        if managed.issued.is_none() {
            return Ok(None);
        }

        for notice in managed.notices(&self.certificate.path) {
            (self.report)(notice);
        }
        Ok(Some(managed))
    }

    /// Renew the certificate when it is due and present the new one, keeping the current
    /// one when renewal fails.
    fn renew(&self) {
        let renewed = self.ensure().and_then(|managed| {
            if managed.is_some()
                && let Some(presented) = &self.presented
            {
                presented.replace(certified_key(&self.certificate)?);
            }

            Ok(())
        });
        if let Err(error) = renewed {
            (self.report)(Notice::Warning(format!(
                "Cannot renew the HTTPS certificate {}, serving the current one. {error}",
                self.certificate.path.display()
            )));
        }
    }
}

/// Build the rustls configuration for the `https` section, presenting what `presented`
/// holds at each handshake.
fn server_config(
    https: &ServerHttpsConfig,
    presented: Arc<Presented>,
) -> Result<Arc<rustls::ServerConfig>, Error> {
    let versions: &[&rustls::SupportedProtocolVersion] = match https.min_version {
        TlsVersion::Tls12 => &[&rustls::version::TLS12, &rustls::version::TLS13],
        TlsVersion::Tls13 => &[&rustls::version::TLS13],
    };
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let mut config = rustls::ServerConfig::builder_with_provider(provider)
        .with_protocol_versions(versions)?
        .with_no_client_auth()
        .with_cert_resolver(presented);
    // Browsers only speak HTTP/2 over TLS and only when ALPN offers it. Without `h2` every
    // video widget holds one of the six HTTP/1.1 connections a browser allows per origin.
    config.alpn_protocols = vec![b"h2".to_vec(), b"http/1.1".to_vec()];
    Ok(Arc::new(config))
}

/// Read the certificate chain and key the listener presents, checking they belong together.
fn certified_key(certificate: &ServerCertificateConfig) -> Result<Arc<CertifiedKey>, Error> {
    for path in [&certificate.path, &certificate.key] {
        if !path.exists() {
            return Err(Error::Missing {
                path: path.display().to_string(),
                certificate: certificate.path.display().to_string(),
                key: certificate.key.display().to_string(),
            });
        }
    }

    let chain = read_certificates(&certificate.path)?;
    let key = read_private_key(&certificate.key, certificate.key_password.as_deref())?;
    let provider = rustls::crypto::ring::default_provider();
    Ok(Arc::new(CertifiedKey::from_der(chain, key, &provider)?))
}

/// The HTTPS certificate as `ceres check` reports it, read without writing anything.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Status {
    /// When the presented certificate expires, in seconds since the Unix epoch. `None` when
    /// a managed certificate is due to be issued at startup.
    pub expires: Option<i64>,
    /// What startup does to a managed certificate, `None` when it keeps the current one.
    pub plan: Option<String>,
}

impl Status {
    /// Read the `https` section's certificate the way the listener does, without issuing.
    pub fn of(
        https: &ServerHttpsConfig,
        detect: impl FnOnce() -> Vec<SubjectName>,
        now: OffsetDateTime,
    ) -> Result<Self, Error> {
        let certificate = &https.certificate;
        let Some(auto) = &certificate.auto else {
            let key = certified_key(certificate)?;
            let presented = key.end_entity_cert()?;
            let (_, parsed) = x509_parser::parse_x509_certificate(presented).map_err(|error| {
                Error::Malformed {
                    path: certificate.path.display().to_string(),
                    reason: error.to_string(),
                }
            })?;
            return Ok(Self {
                expires: Some(parsed.validity().not_after.timestamp()),
                plan: None,
            });
        };

        let inspection =
            Inspection::of(certificate, auto, &SubjectName::required(auto, detect), now)?;
        let path = certificate.path.display();
        let plan = inspection.renewal.map(|renewal| {
            if inspection.creates_authority {
                format!(
                    "Startup creates the certificate authority {} and issues the HTTPS \
                     certificate {path} with it.",
                    auto.authority().path.display()
                )
            } else {
                format!("Startup issues a new HTTPS certificate {path}, because {renewal}.")
            }
        });
        Ok(Self {
            expires: inspection.expires.map(OffsetDateTime::unix_timestamp),
            plan,
        })
    }

    /// [`Self::of`] with the names this machine has right now.
    pub fn current(https: &ServerHttpsConfig) -> Result<Self, Error> {
        Self::of(https, SubjectName::detected, OffsetDateTime::now_utc())
    }
}

/// Read a file, `None` when it does not exist.
fn read(path: &Path) -> Result<Option<Vec<u8>>, Error> {
    match std::fs::read(path) {
        Ok(bytes) => Ok(Some(bytes)),
        Err(source) if source.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(source) => Err(Error::Unreadable {
            path: path.display().to_string(),
            source,
        }),
    }
}

/// Read a file that has to exist.
fn read_existing(path: &Path) -> Result<Vec<u8>, Error> {
    read(path)?.ok_or_else(|| Error::Unreadable {
        path: path.display().to_string(),
        source: std::io::ErrorKind::NotFound.into(),
    })
}

fn read_certificates(path: &Path) -> Result<Vec<CertificateDer<'static>>, Error> {
    let text = read_existing(path)?;
    let certificates: Vec<_> = rustls_pemfile::certs(&mut text.as_slice())
        .collect::<Result<_, _>>()
        .map_err(|source| Error::Unreadable {
            path: path.display().to_string(),
            source,
        })?;
    if certificates.is_empty() {
        return Err(Error::Empty {
            path: path.display().to_string(),
            expected: "certificate",
        });
    }

    Ok(certificates)
}

fn read_private_key(path: &Path, password: Option<&str>) -> Result<PrivateKeyDer<'static>, Error> {
    let text = String::from_utf8(read_existing(path)?).map_err(|_| Error::NotPem {
        path: path.display().to_string(),
        expected: "private key",
    })?;
    // An encrypted key marks itself in its PEM label and needs the configured password.
    if text.contains("ENCRYPTED PRIVATE KEY") {
        let password = password.ok_or_else(|| {
            Error::Decrypt("the key is encrypted and no key_password is configured".to_string())
        })?;
        let (label, document) = pkcs8::SecretDocument::from_pem(&text)
            .map_err(|error| Error::Decrypt(error.to_string()))?;
        if label != "ENCRYPTED PRIVATE KEY" {
            return Err(Error::Decrypt(format!("unexpected PEM label {label:?}")));
        }

        let encrypted = pkcs8::EncryptedPrivateKeyInfo::try_from(document.as_bytes())
            .map_err(|error| Error::Decrypt(error.to_string()))?;
        let decrypted = encrypted
            .decrypt(password)
            .map_err(|error| Error::Decrypt(error.to_string()))?;
        return Ok(PrivatePkcs8KeyDer::from(decrypted.as_bytes().to_vec()).into());
    }

    match rustls_pemfile::private_key(&mut text.as_bytes()) {
        Ok(Some(key)) => Ok(key),
        _ => Err(Error::Empty {
            path: path.display().to_string(),
            expected: "private key",
        }),
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use std::sync::Mutex;

    use ceres_config::ServerCertificateAutoConfig;

    use super::*;

    /// Write one self-signed identity's certificate and key, the key transformed first.
    pub(crate) fn https(
        directory: &Path,
        password: Option<&str>,
        transform_key: impl Fn(String) -> String,
    ) -> ServerHttpsConfig {
        let certified = rcgen::generate_simple_self_signed(["localhost".to_string()]).unwrap();
        let key_path = directory.join("key.pem");
        let cert_path = directory.join("cert.pem");
        std::fs::write(
            &key_path,
            transform_key(certified.signing_key.serialize_pem()),
        )
        .unwrap();
        std::fs::write(&cert_path, certified.cert.pem()).unwrap();
        ServerHttpsConfig {
            port: 0,
            certificate: ServerCertificateConfig {
                path: cert_path,
                key: key_path,
                key_password: password.map(str::to_string),
                auto: None,
            },
            ..ServerHttpsConfig::default()
        }
    }

    /// An `https` section managing its certificate under `directory` with the default
    /// authority there too.
    pub(crate) fn managed(directory: &Path) -> ServerHttpsConfig {
        let tls = directory.join(".ceres/tls");
        std::fs::create_dir_all(&tls).unwrap();
        managed::write_authority(&tls.join("ca.crt"), &tls.join("ca.key"));
        ServerHttpsConfig {
            port: 0,
            certificate: ServerCertificateConfig {
                path: tls.join("server.crt"),
                key: tls.join("server.key"),
                key_password: None,
                auto: Some(ServerCertificateAutoConfig {
                    ca: Some(ceres_config::ServerCertificateAuthorityConfig {
                        path: tls.join("ca.crt"),
                        key: tls.join("ca.key"),
                        key_password: None,
                    }),
                    ..ServerCertificateAutoConfig::default()
                }),
            },
            ..ServerHttpsConfig::default()
        }
    }

    /// The names tests detect, so no test depends on the machine running it.
    pub(crate) fn localhost() -> Vec<SubjectName> {
        vec![SubjectName::Dns("localhost".into())]
    }

    /// A report collecting every notice.
    pub(crate) fn collecting() -> (Report, Arc<Mutex<Vec<Notice>>>) {
        let notices = Arc::new(Mutex::new(Vec::new()));
        let sink = notices.clone();
        let report: Report = Arc::new(move |notice| sink.lock().unwrap().push(notice));
        (report, notices)
    }

    fn quiet() -> Report {
        Arc::new(|_| {})
    }

    /// Encrypt a plain PKCS#8 key PEM under a password.
    pub(crate) fn encrypt_key(pem: String, password: &str) -> String {
        let key = pkcs8::SecretDocument::from_pem(&pem).unwrap().1;
        pkcs8::PrivateKeyInfo::try_from(key.as_bytes())
            .unwrap()
            .encrypt(rand_seed(), password)
            .unwrap()
            .to_pem("ENCRYPTED PRIVATE KEY", pkcs8::LineEnding::LF)
            .unwrap()
            .to_string()
    }

    #[test]
    fn plain_keys_load_and_offer_h2() {
        let directory = tempfile::tempdir().unwrap();
        let config = https(directory.path(), None, |key| key);
        let loaded = Tls::load(&config, quiet()).unwrap();
        assert_eq!(
            loaded.config.alpn_protocols,
            [b"h2".to_vec(), b"http/1.1".to_vec()]
        );
    }

    #[test]
    fn encrypted_keys_decrypt_with_the_configured_password() {
        let directory = tempfile::tempdir().unwrap();
        let config = https(directory.path(), Some("hunter2"), |key| {
            encrypt_key(key, "hunter2")
        });
        assert!(Tls::load(&config, quiet()).is_ok());

        let config = https(directory.path(), None, |key| encrypt_key(key, "hunter2"));
        assert!(matches!(
            Tls::load(&config, quiet()),
            Err(Error::Decrypt(_))
        ));
    }

    #[test]
    fn missing_files_name_both_paths_and_both_remedies() {
        // `generate certificate` writes to the configured paths, so the hint holds for any
        // path, not only the defaults.
        let directory = tempfile::tempdir().unwrap();
        let mut config = https(directory.path(), None, |key| key);
        config.certificate.path = directory.path().join("absent.pem");
        let expected = format!(
            "{cert} does not exist. Run `ceres generate certificate` to write the certificate \
             {cert} and key {key}, or set `certificate: auto` under `server.https` for Ceres \
             to manage them.",
            cert = config.certificate.path.display(),
            key = config.certificate.key.display(),
        );
        let error = Tls::load(&config, quiet()).err().unwrap();
        assert_eq!(error.to_string(), expected);
        // `ceres check` fails the same way, before anything starts.
        let error = Status::of(&config, localhost, OffsetDateTime::now_utc()).unwrap_err();
        assert_eq!(error.to_string(), expected);

        let mut config = https(directory.path(), None, |key| key);
        config.certificate.key = directory.path().join("absent.key");
        let error = Tls::load(&config, quiet()).err().unwrap();
        assert!(
            error.to_string().starts_with(&format!(
                "{} does not exist.",
                config.certificate.key.display()
            )),
            "{error}"
        );
    }

    #[test]
    fn unreadable_files_name_their_path() {
        // A directory where the certificate file should be fails to read without being
        // missing.
        let directory = tempfile::tempdir().unwrap();
        let mut config = https(directory.path(), None, |key| key);
        config.certificate.path = directory.path().to_owned();
        let error = Tls::load(&config, quiet()).err().unwrap();
        assert!(matches!(error, Error::Unreadable { .. }), "{error}");
        assert!(
            error
                .to_string()
                .contains(&directory.path().display().to_string()),
            "{error}"
        );
    }

    #[test]
    fn binary_keys_are_refused_as_not_pem() {
        let directory = tempfile::tempdir().unwrap();
        let config = https(directory.path(), None, |key| key);
        std::fs::write(&config.certificate.key, [0x30, 0x82, 0xff, 0xfe]).unwrap();
        let error = Tls::load(&config, quiet()).err().unwrap();
        assert_eq!(
            error.to_string(),
            format!(
                "{} is not text, expected a PEM private key",
                config.certificate.key.display()
            )
        );
    }

    #[test]
    fn expiry_is_read_from_the_presented_certificate() {
        let directory = tempfile::tempdir().unwrap();
        let mut config = https(directory.path(), None, |key| key);
        let now = OffsetDateTime::now_utc();

        let key = rcgen::KeyPair::generate().unwrap();
        let mut params = rcgen::CertificateParams::new(["localhost".to_string()]).unwrap();
        params.not_after = rcgen::date_time_ymd(2031, 5, 4);
        let certificate = params.self_signed(&key).unwrap();
        std::fs::write(&config.certificate.path, certificate.pem()).unwrap();
        std::fs::write(&config.certificate.key, key.serialize_pem()).unwrap();
        assert_eq!(
            Status::of(&config, localhost, now).unwrap(),
            Status {
                expires: Some(rcgen::date_time_ymd(2031, 5, 4).unix_timestamp()),
                plan: None,
            }
        );

        // A key that does not match the certificate fails the way the listener would.
        std::fs::write(
            &config.certificate.key,
            rcgen::KeyPair::generate().unwrap().serialize_pem(),
        )
        .unwrap();
        assert!(Status::of(&config, localhost, now).is_err());
        config.certificate.path = directory.path().join("absent.pem");
        assert!(Status::of(&config, localhost, now).is_err());
    }

    #[test]
    fn min_versions_floor_the_negotiation() {
        let directory = tempfile::tempdir().unwrap();
        let mut config = https(directory.path(), None, |key| key);
        let roots = trusting(&config.certificate.path);
        let tls = Tls::load(&config, quiet()).unwrap();
        assert_eq!(
            handshake(&tls, &roots, &rustls::version::TLS12).map(|(version, _)| version),
            Some(rustls::ProtocolVersion::TLSv1_2)
        );
        config.min_version = TlsVersion::Tls13;
        let tls = Tls::load(&config, quiet()).unwrap();
        assert_eq!(handshake(&tls, &roots, &rustls::version::TLS12), None);
        assert_eq!(
            handshake(&tls, &roots, &rustls::version::TLS13).map(|(version, _)| version),
            Some(rustls::ProtocolVersion::TLSv1_3)
        );
    }

    #[test]
    fn check_reports_what_startup_issues_without_writing() {
        let directory = tempfile::tempdir().unwrap();
        let config = managed(directory.path());
        let mut fresh = config.clone();
        // With no `ca` given the default authority is created, which check announces.
        fresh.certificate.auto.as_mut().unwrap().ca = None;
        let now = OffsetDateTime::now_utc();
        let ca = ceres_config::ServerCertificateAuthorityConfig::default().path;
        assert_eq!(
            Status::of(&fresh, localhost, now).unwrap(),
            Status {
                expires: None,
                plan: Some(format!(
                    "Startup creates the certificate authority {} and issues the HTTPS \
                     certificate {} with it.",
                    ca.display(),
                    fresh.certificate.path.display()
                )),
            }
        );
        assert!(!fresh.certificate.path.exists());
        assert!(!ca.exists());

        // An existing authority signs a new certificate when the current one falls short.
        let (report, _) = collecting();
        Tls::load_detecting(&config, report, localhost).unwrap();
        let issued = std::fs::read(&config.certificate.path).unwrap();
        let wider = || {
            vec![
                SubjectName::Dns("localhost".into()),
                SubjectName::Dns("ceres.example".into()),
            ]
        };
        assert_eq!(
            Status::of(&config, wider, now).unwrap().plan,
            Some(format!(
                "Startup issues a new HTTPS certificate {}, because the certificate does not \
                 name ceres.example.",
                config.certificate.path.display()
            ))
        );
        let current = Status::of(&config, localhost, now).unwrap();
        assert_eq!(current.plan, None);
        assert!(current.expires.unwrap() > now.unix_timestamp());
        assert_eq!(std::fs::read(&config.certificate.path).unwrap(), issued);
    }

    #[test]
    fn startup_issues_managed_certificates_and_reports_it() {
        let directory = tempfile::tempdir().unwrap();
        let config = managed(directory.path());
        let (report, notices) = collecting();
        let tls = Tls::load_detecting(&config, report, localhost).unwrap();
        let roots = trusting(&config.certificate.auto.as_ref().unwrap().authority().path);
        assert!(handshake(&tls, &roots, &rustls::version::TLS13).is_some());

        let notices = notices.lock().unwrap();
        let [Notice::Info(issued)] = notices.as_slice() else {
            panic!("{notices:?}");
        };
        assert!(
            issued.starts_with(&format!(
                "Issued the HTTPS certificate {} for localhost, expiring ",
                config.certificate.path.display()
            )),
            "{issued}"
        );
        assert!(
            issued.ends_with(", because there is no certificate yet."),
            "{issued}"
        );
    }

    #[test]
    fn renewal_swaps_the_presented_certificate_and_keeps_open_connections() {
        let directory = tempfile::tempdir().unwrap();
        let config = managed(directory.path());
        let (report, notices) = collecting();
        let tls = Tls::load_detecting(&config, report, localhost).unwrap();
        let roots = trusting(&config.certificate.auto.as_ref().unwrap().authority().path);
        let (_, before) = handshake(&tls, &roots, &rustls::version::TLS13).unwrap();
        let open = established(&tls, &roots);

        // A current certificate is left as it is.
        tls.renewer.as_ref().unwrap().renew();
        let (_, kept) = handshake(&tls, &roots, &rustls::version::TLS13).unwrap();
        assert_eq!(kept, before);

        std::fs::remove_file(&config.certificate.path).unwrap();
        tls.renewer.as_ref().unwrap().renew();
        let (_, after) = handshake(&tls, &roots, &rustls::version::TLS13).unwrap();
        assert_ne!(after, before);
        assert_eq!(
            open.0.peer_certificates().unwrap()[0],
            before,
            "the open connection keeps its certificate"
        );
        assert!(notices.lock().unwrap().iter().any(|notice| matches!(
            notice,
            Notice::Info(text) if text.ends_with("because there is no certificate yet.")
        )));
    }

    #[test]
    fn failed_renewals_warn_and_keep_serving() {
        let directory = tempfile::tempdir().unwrap();
        let config = managed(directory.path());
        let (report, notices) = collecting();
        let tls = Tls::load_detecting(&config, report, localhost).unwrap();
        let roots = trusting(&config.certificate.auto.as_ref().unwrap().authority().path);
        let (_, before) = handshake(&tls, &roots, &rustls::version::TLS13).unwrap();

        let authority = config.certificate.auto.as_ref().unwrap().authority();
        std::fs::remove_file(&authority.key).unwrap();
        std::fs::remove_file(&config.certificate.path).unwrap();
        tls.renewer.as_ref().unwrap().renew();
        let (_, after) = handshake(&tls, &roots, &rustls::version::TLS13).unwrap();
        assert_eq!(after, before);
        assert_eq!(
            notices.lock().unwrap().last(),
            Some(&Notice::Warning(format!(
                "Cannot renew the HTTPS certificate {}, serving the current one. {} does not \
                 exist. Ceres never creates the certificate authority `auto.ca` names.",
                config.certificate.path.display(),
                authority.key.display()
            )))
        );
    }

    #[tokio::test(start_paused = true)]
    async fn renewal_waits_for_its_interval() {
        let directory = tempfile::tempdir().unwrap();
        let config = managed(directory.path());
        let tls = Tls::load_detecting(&config, quiet(), localhost).unwrap();
        std::fs::remove_file(&config.certificate.path).unwrap();

        let renewing = tls.renew_every(Duration::from_secs(60));
        tokio::pin!(renewing);
        let early = tokio::time::timeout(Duration::from_secs(59), &mut renewing).await;
        assert!(early.is_err());
        assert!(!config.certificate.path.exists());
        let _ = tokio::time::timeout(Duration::from_secs(2), &mut renewing).await;
        assert!(config.certificate.path.exists());

        // A listener reading its own certificate never renews and never finishes.
        let plain = https(directory.path(), None, |key| key);
        let tls = Tls::load(&plain, quiet()).unwrap();
        let waiting = tokio::time::timeout(
            Duration::from_secs(1_000_000),
            tls.renew_every(Duration::from_secs(1)),
        )
        .await;
        assert!(waiting.is_err());
    }

    /// Roots trusting every certificate in the PEM file at `path`.
    pub(crate) fn trusting(path: &Path) -> rustls::RootCertStore {
        let mut roots = rustls::RootCertStore::empty();
        roots.add_parsable_certificates(read_certificates(path).unwrap());
        roots
    }

    type Connections = (rustls::ClientConnection, rustls::ServerConnection);

    /// Complete an in-memory handshake with a client offering only `version`, returning the
    /// negotiated version and the presented certificate, or `None` when either side fails.
    fn handshake(
        tls: &Tls,
        roots: &rustls::RootCertStore,
        version: &'static rustls::SupportedProtocolVersion,
    ) -> Option<(rustls::ProtocolVersion, CertificateDer<'static>)> {
        let (client, _) = connect(tls, roots, version)?;
        Some((
            client.protocol_version()?,
            client.peer_certificates()?[0].clone().into_owned(),
        ))
    }

    fn established(tls: &Tls, roots: &rustls::RootCertStore) -> Connections {
        connect(tls, roots, &rustls::version::TLS13).unwrap()
    }

    fn connect(
        tls: &Tls,
        roots: &rustls::RootCertStore,
        version: &'static rustls::SupportedProtocolVersion,
    ) -> Option<Connections> {
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let client = rustls::ClientConfig::builder_with_provider(provider)
            .with_protocol_versions(&[version])
            .unwrap()
            .with_root_certificates(roots.clone())
            .with_no_client_auth();
        let mut client =
            rustls::ClientConnection::new(Arc::new(client), "localhost".try_into().unwrap())
                .unwrap();
        let mut server = rustls::ServerConnection::new(tls.config.clone()).unwrap();

        // An empty read means end of stream to rustls, so only pass along written bytes.
        while client.is_handshaking() || server.is_handshaking() {
            let mut bytes = Vec::new();
            while client.wants_write() {
                client.write_tls(&mut bytes).unwrap();
            }
            let mut unread = bytes.as_slice();
            while !unread.is_empty() {
                server.read_tls(&mut unread).unwrap();
                server.process_new_packets().ok()?;
            }
            bytes.clear();
            while server.wants_write() {
                server.write_tls(&mut bytes).unwrap();
            }
            let mut unread = bytes.as_slice();
            while !unread.is_empty() {
                client.read_tls(&mut unread).unwrap();
                client.process_new_packets().ok()?;
            }
        }
        Some((client, server))
    }

    /// A fixed seed for the key-encryption test, randomness has no bearing on it.
    fn rand_seed() -> impl rand_core::CryptoRngCore {
        use rand_core::SeedableRng;
        rand_chacha::ChaCha20Rng::from_seed([7; 32])
    }
}
