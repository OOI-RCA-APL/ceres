//! The certificate Ceres issues and renews itself under `certificate.auto`.
//!
//! A managed certificate is signed by a certificate authority, which clients trust once
//! for every certificate it signs. The authority is the one `auto.ca` names, or one Ceres
//! creates at the default paths the first time it needs it and never rewrites.

use std::fmt;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::path::{Path, PathBuf};

use ceres_config::{
    ServerCertificateAuthorityConfig, ServerCertificateAutoConfig, ServerCertificateConfig,
};
use rustls::pki_types::{CertificateDer, PrivateKeyDer};
use sha2::{Digest, Sha256};
use time::{Duration, OffsetDateTime};
use x509_parser::certificate::X509Certificate;
use x509_parser::extensions::GeneralName;

use super::{Error, Notice, read, read_certificates, read_private_key};

/// How close to expiry a certificate issued for `days` renews: once two thirds of its
/// lifetime is spent, and never later than 30 days before it expires.
pub fn renewal_window(days: u32) -> Duration {
    (Duration::days(i64::from(days)) / 3_i32).min(Duration::days(30))
}

/// An authority this close to expiry draws a warning at every check. Ceres never renews one,
/// since every client would have to trust the new one.
const AUTHORITY_WARNING: Duration = Duration::days(30);

/// How long an authority Ceres creates stays valid.
const AUTHORITY_LIFETIME: Duration = Duration::days(3650);

/// How far back validity starts, so a client whose clock runs a little behind accepts a
/// certificate issued moments ago.
const BACKDATE: Duration = Duration::hours(1);

/// A name a certificate vouches for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SubjectName {
    Dns(String),
    Ip(IpAddr),
}

impl fmt::Display for SubjectName {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Dns(name) => formatter.write_str(name),
            Self::Ip(address) => write!(formatter, "{address}"),
        }
    }
}

impl SubjectName {
    /// Remove repeats from `names`, keeping the first of each in order. DNS names compare
    /// without case and are kept lowercase.
    pub fn unique(names: impl IntoIterator<Item = Self>) -> Vec<Self> {
        let mut unique: Vec<Self> = Vec::new();
        for name in names {
            let name = match name {
                Self::Dns(name) => Self::Dns(name.to_ascii_lowercase()),
                name => name,
            };
            if !unique.contains(&name) {
                unique.push(name);
            }
        }

        unique
    }

    /// The names this machine answers to: localhost and the loopback addresses, the
    /// hostname, and every interface address other than loopback and link-local ones.
    pub fn detected() -> Vec<Self> {
        Self::local(hostname(), interface_addresses())
    }

    fn local(hostname: Option<String>, interfaces: Vec<IpAddr>) -> Vec<Self> {
        let names = [
            Self::Dns("localhost".into()),
            Self::Ip(IpAddr::V4(Ipv4Addr::LOCALHOST)),
            Self::Ip(IpAddr::V6(Ipv6Addr::LOCALHOST)),
        ]
        .into_iter()
        .chain(hostname.map(Self::Dns))
        .chain(
            interfaces
                .into_iter()
                .filter(|address| !address.is_loopback() && !is_link_local(address))
                .map(Self::Ip),
        );
        Self::unique(names)
    }

    /// The names a managed certificate must carry, the configured ones, or the ones
    /// `detect` answers when none are configured.
    pub fn required(
        auto: &ServerCertificateAutoConfig,
        detect: impl FnOnce() -> Vec<Self>,
    ) -> Vec<Self> {
        if auto.detects_names() {
            return Self::unique(detect());
        }

        let addresses = auto.ip.iter().copied().map(Self::Ip);
        Self::unique(addresses.chain(auto.dns.iter().cloned().map(Self::Dns)))
    }

    fn san(&self) -> Result<rcgen::SanType, Error> {
        match self {
            Self::Dns(name) => rcgen::string::Ia5String::try_from(name.as_str())
                .map(rcgen::SanType::DnsName)
                .map_err(|error| Error::Issue(format!("{name:?} cannot be a DNS name. {error}"))),
            Self::Ip(address) => Ok(rcgen::SanType::IpAddress(*address)),
        }
    }
}

/// Whether an address only reaches its own link, which no client would name a server by.
fn is_link_local(address: &IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => address.is_link_local(),
        IpAddr::V6(address) => (address.segments()[0] & 0xffc0) == 0xfe80,
    }
}

/// Why a managed certificate is due to be issued.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Renewal {
    /// The certificate or its key does not exist.
    Missing,
    /// The certificate or its key cannot be read as one.
    Unparsable(String),
    /// The authority signing managed certificates did not sign this one.
    ForeignIssuer,
    /// The certificate's validity starts in the future.
    NotYetValid,
    /// The certificate has expired or expires within its [`renewal_window`].
    Expiring(OffsetDateTime),
    /// The certificate does not name every required name.
    MissingNames(Vec<SubjectName>),
    /// A new certificate was asked for regardless.
    Forced,
}

impl fmt::Display for Renewal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Missing => formatter.write_str("there is no certificate yet"),
            Self::Unparsable(reason) => {
                write!(formatter, "the certificate cannot be read. {reason}")
            }
            Self::ForeignIssuer => formatter.write_str("another authority signed the certificate"),
            Self::NotYetValid => formatter.write_str("the certificate is not valid yet"),
            Self::Expiring(expires) => {
                write!(formatter, "the certificate expires on {}", expires.date())
            }
            Self::MissingNames(names) => {
                let names: Vec<String> = names.iter().map(ToString::to_string).collect();
                write!(
                    formatter,
                    "the certificate does not name {}",
                    names.join(", ")
                )
            }
            Self::Forced => formatter.write_str("a new certificate was asked for"),
        }
    }
}

/// The authority signing managed certificates, as found on disk.
enum Authority {
    /// Both files exist. The chain starts with the authority's own certificate.
    Present {
        chain: Vec<CertificateDer<'static>>,
        key: PrivateKeyDer<'static>,
        expires: OffsetDateTime,
    },
    /// Neither default file exists yet, so Ceres creates the authority.
    Absent,
}

impl Authority {
    /// Read the authority at `config`'s paths. A `supplied` one has to exist, a default
    /// one is [`Self::Absent`] when neither of its files exists.
    fn read(config: &ServerCertificateAuthorityConfig, supplied: bool) -> Result<Self, Error> {
        let certificate_exists = config.path.exists();
        let key_exists = config.key.exists();
        if supplied {
            // A typo in a supplied path must not mint a new authority silently.
            for (path, exists) in [
                (&config.path, certificate_exists),
                (&config.key, key_exists),
            ] {
                if !exists {
                    return Err(Error::AuthorityMissing {
                        path: path.display().to_string(),
                    });
                }
            }
        } else if !certificate_exists && !key_exists {
            return Ok(Self::Absent);
        } else if certificate_exists != key_exists {
            let (present, missing) = if certificate_exists {
                (&config.path, &config.key)
            } else {
                (&config.key, &config.path)
            };
            return Err(Error::AuthorityIncomplete {
                present: present.display().to_string(),
                missing: missing.display().to_string(),
            });
        }

        let chain = read_certificates(&config.path)?;
        let key = read_private_key(&config.key, config.key_password.as_deref())?;
        let expires = Self::validate(config, &chain, &key)?;
        Ok(Self::Present {
            chain,
            key,
            expires,
        })
    }

    /// Check that the authority's certificate may sign certificates and that its key belongs
    /// to it, answering when it expires.
    fn validate(
        config: &ServerCertificateAuthorityConfig,
        chain: &[CertificateDer<'static>],
        key: &PrivateKeyDer<'static>,
    ) -> Result<OffsetDateTime, Error> {
        let unusable = |reason: String| Error::AuthorityUnusable {
            path: config.path.display().to_string(),
            reason,
        };
        let (_, certificate) = x509_parser::parse_x509_certificate(&chain[0])
            .map_err(|error| malformed(&config.path, error))?;
        if !certificate.is_ca() {
            return Err(unusable("It is not a certificate authority.".into()));
        }
        // Without the extension every usage is allowed.
        match certificate.key_usage() {
            Ok(Some(usage)) if !usage.value.key_cert_sign() => {
                return Err(unusable(
                    "Its key usage does not include signing certificates.".into(),
                ));
            }
            Ok(_) => {}
            Err(error) => return Err(malformed(&config.path, error)),
        }

        let provider = rustls::crypto::ring::default_provider();
        match rustls::sign::CertifiedKey::from_der(chain.to_vec(), key.clone_key(), &provider) {
            Ok(_) => {}
            Err(rustls::Error::InconsistentKeys(_)) => {
                return Err(unusable(format!(
                    "The key {} does not belong to it.",
                    config.key.display()
                )));
            }
            Err(error) => {
                return Err(unusable(format!(
                    "The key {} cannot be used. {error}",
                    config.key.display()
                )));
            }
        }

        Ok(certificate.validity().not_after.to_datetime())
    }

    /// The warning an authority expiring within [`AUTHORITY_WARNING`] of `now` draws.
    fn warning(
        &self,
        config: &ServerCertificateAuthorityConfig,
        supplied: bool,
        now: OffsetDateTime,
    ) -> Option<String> {
        let Self::Present { expires, .. } = self else {
            return None;
        };
        if *expires - now > AUTHORITY_WARNING {
            return None;
        }

        let path = config.path.display();
        let state = if *expires <= now {
            format!(
                "The certificate authority {path} expired on {}, so clients no longer trust the \
                 certificates it signs.",
                expires.date()
            )
        } else {
            format!(
                "The certificate authority {path} expires on {}.",
                expires.date()
            )
        };
        let remedy = if supplied {
            "Replace it at the paths `auto.ca` names".to_string()
        } else {
            format!(
                "Remove {path} and {} for Ceres to create a new one",
                config.key.display()
            )
        };
        Some(format!(
            "{state} Ceres never renews an authority. {remedy}, and trust the new one on each \
             client."
        ))
    }
}

/// The certificate at the configured paths, or why it is due to be issued.
enum Leaf {
    Current {
        certificate: CertificateDer<'static>,
        not_after: OffsetDateTime,
    },
    Due(Renewal),
}

impl Leaf {
    /// Judge the certificate at `certificate`'s paths against the authority and names.
    fn judge(
        certificate: &ServerCertificateConfig,
        authority: &Authority,
        names: &[SubjectName],
        window: Duration,
        now: OffsetDateTime,
    ) -> Result<Self, Error> {
        let (Some(chain), Some(key)) = (read(&certificate.path)?, read(&certificate.key)?) else {
            return Ok(Self::Due(Renewal::Missing));
        };

        let unparsable = |reason: String| Ok(Self::Due(Renewal::Unparsable(reason)));
        let chain: Vec<CertificateDer<'static>> =
            match rustls_pemfile::certs(&mut chain.as_slice()).collect::<Result<Vec<_>, _>>() {
                Ok(chain) if !chain.is_empty() => chain,
                Ok(_) => return unparsable("it holds no PEM certificate".into()),
                Err(error) => return unparsable(error.to_string()),
            };
        let key = match rustls_pemfile::private_key(&mut key.as_slice()) {
            Ok(Some(key)) => key,
            Ok(None) => return unparsable("its key file holds no PEM private key".into()),
            Err(error) => return unparsable(error.to_string()),
        };
        let provider = rustls::crypto::ring::default_provider();
        if let Err(error) = rustls::sign::CertifiedKey::from_der(chain.clone(), key, &provider) {
            return unparsable(error.to_string());
        }

        let presented = chain[0].clone();
        let leaf = match x509_parser::parse_x509_certificate(&presented) {
            Ok((_, leaf)) => leaf,
            Err(error) => return unparsable(error.to_string()),
        };

        let Authority::Present {
            chain: authority, ..
        } = authority
        else {
            return Ok(Self::Due(Renewal::ForeignIssuer));
        };
        if !signed_by(&leaf, &authority[0]) {
            return Ok(Self::Due(Renewal::ForeignIssuer));
        }

        let validity = leaf.validity();
        if validity.not_before.timestamp() > now.unix_timestamp() {
            return Ok(Self::Due(Renewal::NotYetValid));
        }

        let not_after = validity.not_after.to_datetime();
        if not_after - now < window {
            return Ok(Self::Due(Renewal::Expiring(not_after)));
        }

        let carried = carried_names(&leaf);
        let missing: Vec<SubjectName> = names
            .iter()
            .filter(|name| !carried.contains(name))
            .cloned()
            .collect();
        if !missing.is_empty() {
            return Ok(Self::Due(Renewal::MissingNames(missing)));
        }

        Ok(Self::Current {
            certificate: presented,
            not_after,
        })
    }
}

/// Whether `authority`, a DER certificate, issued and signed `leaf`.
fn signed_by(leaf: &X509Certificate<'_>, authority: &[u8]) -> bool {
    let Ok((_, authority)) = x509_parser::parse_x509_certificate(authority) else {
        return false;
    };

    leaf.issuer().as_raw() == authority.subject().as_raw()
        && leaf.verify_signature(Some(authority.public_key())).is_ok()
}

/// The names a certificate's subject alternative names carry.
fn carried_names(certificate: &X509Certificate<'_>) -> Vec<SubjectName> {
    let Ok(Some(extension)) = certificate.subject_alternative_name() else {
        return Vec::new();
    };

    let names = extension
        .value
        .general_names
        .iter()
        .filter_map(|name| match name {
            GeneralName::DNSName(name) => Some(SubjectName::Dns(name.to_string())),
            GeneralName::IPAddress(bytes) => match bytes.len() {
                4 => <[u8; 4]>::try_from(*bytes).ok().map(IpAddr::from),
                16 => <[u8; 16]>::try_from(*bytes).ok().map(IpAddr::from),
                _ => None,
            }
            .map(SubjectName::Ip),
            _ => None,
        });
    SubjectName::unique(names)
}

/// What `ceres check` reports about a managed certificate, read without writing anything.
#[derive(Debug, Clone, PartialEq)]
pub struct Inspection {
    /// When the certificate expires, `None` when it is due to be issued.
    pub expires: Option<OffsetDateTime>,
    /// Why the certificate is due to be issued, `None` when it is kept as it is.
    pub renewal: Option<Renewal>,
    /// Whether Ceres creates the default authority before issuing.
    pub creates_authority: bool,
    /// The warning an authority close to expiry or past it draws.
    pub authority_warning: Option<String>,
}

impl Inspection {
    /// Inspect the managed certificate at `certificate`'s paths.
    pub fn of(
        certificate: &ServerCertificateConfig,
        auto: &ServerCertificateAutoConfig,
        names: &[SubjectName],
        now: OffsetDateTime,
    ) -> Result<Self, Error> {
        let config = auto.authority();
        let supplied = auto.ca.is_some();
        let authority = Authority::read(&config, supplied)?;
        let creates_authority = matches!(authority, Authority::Absent);
        let authority_warning = authority.warning(&config, supplied, now);
        let window = renewal_window(auto.days);
        Ok(
            match Leaf::judge(certificate, &authority, names, window, now)? {
                Leaf::Current { not_after, .. } => Self {
                    expires: Some(not_after),
                    renewal: None,
                    creates_authority,
                    authority_warning,
                },
                Leaf::Due(renewal) => Self {
                    expires: None,
                    renewal: Some(renewal),
                    creates_authority,
                    authority_warning,
                },
            },
        )
    }
}

/// The managed certificate once ensured, as `generate certificate` and the log describe it.
#[derive(Debug, Clone, PartialEq)]
pub struct Managed {
    /// Path of the authority certificate clients trust.
    pub authority: PathBuf,
    /// Whether the authority was created along the way.
    pub created_authority: bool,
    /// Why a new certificate was issued, `None` when the existing one was kept.
    pub issued: Option<Renewal>,
    /// The names the certificate carries.
    pub names: Vec<SubjectName>,
    pub expires: OffsetDateTime,
    /// SHA-256 fingerprint of the certificate, colon-separated uppercase hex.
    pub fingerprint: String,
    /// The warning an authority close to expiry or past it draws.
    pub authority_warning: Option<String>,
}

impl Managed {
    /// Issue a certificate at `certificate`'s paths when one is due or `force` is set,
    /// creating the default authority first when it does not exist. Relative paths resolve
    /// against `base`.
    ///
    /// A current certificate is left as it is. Every file is written beside its final path
    /// and renamed over it, keys readable by their owner alone.
    pub fn ensure(
        base: &Path,
        certificate: &ServerCertificateConfig,
        auto: &ServerCertificateAutoConfig,
        names: &[SubjectName],
        now: OffsetDateTime,
        force: bool,
    ) -> Result<Self, Error> {
        let authority = auto.authority();
        let issuance = Issuance {
            days: auto.days,
            authority: ServerCertificateAuthorityConfig {
                path: base.join(&authority.path),
                key: base.join(&authority.key),
                ..authority
            },
            supplied: auto.ca.is_some(),
        };
        let certificate = ServerCertificateConfig {
            path: base.join(&certificate.path),
            key: base.join(&certificate.key),
            ..certificate.clone()
        };
        issuance.ensure(&certificate, names, now, force)
    }

    /// What the log says about the certificate at `certificate`: what was created and
    /// issued, and the authority's expiry when it is close.
    pub fn notices(&self, certificate: &Path) -> Vec<Notice> {
        let mut notices: Vec<Notice> = self
            .authority_warning
            .iter()
            .cloned()
            .map(Notice::Warning)
            .collect();
        let Some(renewal) = &self.issued else {
            return notices;
        };

        if self.created_authority {
            notices.push(Notice::Info(format!(
                "Created the certificate authority {}. Trust it on each client to trust the \
                 HTTPS certificate it signs.",
                self.authority.display()
            )));
        }
        let names: Vec<String> = self.names.iter().map(ToString::to_string).collect();
        notices.push(Notice::Info(format!(
            "Issued the HTTPS certificate {} for {}, expiring {}, because {renewal}.",
            certificate.display(),
            names.join(", "),
            self.expires.date()
        )));
        notices
    }
}

/// How managed certificates are issued: their lifetime and the authority signing them.
#[derive(Clone)]
struct Issuance {
    days: u32,
    authority: ServerCertificateAuthorityConfig,
    /// Whether the configuration names the authority, which then has to exist.
    supplied: bool,
}

impl Issuance {
    fn ensure(
        &self,
        certificate: &ServerCertificateConfig,
        names: &[SubjectName],
        now: OffsetDateTime,
        force: bool,
    ) -> Result<Managed, Error> {
        let config = &self.authority;
        let mut authority = Authority::read(config, self.supplied)?;
        let window = renewal_window(self.days);
        let leaf = Leaf::judge(certificate, &authority, names, window, now)?;

        if let (
            false,
            Leaf::Current {
                certificate: presented,
                not_after,
            },
        ) = (force, &leaf)
        {
            let (_, parsed) = x509_parser::parse_x509_certificate(presented)
                .map_err(|error| malformed(&certificate.path, error))?;
            return Ok(Managed {
                authority: config.path.clone(),
                created_authority: false,
                issued: None,
                names: carried_names(&parsed),
                expires: *not_after,
                fingerprint: fingerprint(presented),
                authority_warning: authority.warning(config, self.supplied, now),
            });
        }

        let issued = match leaf {
            Leaf::Due(renewal) => renewal,
            Leaf::Current { .. } => Renewal::Forced,
        };

        // Validity counts whole seconds, so the bounds below differ by exactly `days`.
        let now = now.replace_nanosecond(0).unwrap_or(now);
        let created_authority = matches!(authority, Authority::Absent);
        if created_authority {
            authority = create_authority(&config.path, &config.key, now)?;
        }

        let authority_warning = authority.warning(config, self.supplied, now);
        let Authority::Present {
            chain: authority_chain,
            key: authority_key,
            ..
        } = authority
        else {
            unreachable!("the authority exists once created");
        };
        let not_before = now - BACKDATE;
        // Apple counts the last second as valid, so `days` covers the period inclusively.
        let not_after = not_before + Duration::days(i64::from(self.days)) - Duration::SECOND;
        let (chain, key, der) = sign(
            names,
            &authority_chain,
            &authority_key,
            not_before,
            not_after,
        )?;
        write_pair(&certificate.path, &chain, &certificate.key, &key)?;

        Ok(Managed {
            authority: config.path.clone(),
            created_authority,
            issued: Some(issued),
            names: names.to_vec(),
            expires: not_after,
            fingerprint: fingerprint(&der),
            authority_warning,
        })
    }
}

fn malformed(path: &Path, error: impl fmt::Display) -> Error {
    Error::Malformed {
        path: path.display().to_string(),
        reason: error.to_string(),
    }
}

/// Create a certificate authority at `path` and `key`, answering it as read back.
fn create_authority(path: &Path, key: &Path, now: OffsetDateTime) -> Result<Authority, Error> {
    let signing_key = rcgen::KeyPair::generate_for(&rcgen::PKCS_ECDSA_P256_SHA256)
        .map_err(|error| Error::Issue(format!("cannot generate a key. {error}")))?;

    let mut params = rcgen::CertificateParams::default();
    params.distinguished_name = rcgen::DistinguishedName::new();
    let name = match hostname() {
        Some(host) => format!("Ceres authority for {host}"),
        None => "Ceres authority".into(),
    };
    params
        .distinguished_name
        .push(rcgen::DnType::CommonName, name);
    params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Constrained(0));
    params.key_usages = vec![rcgen::KeyUsagePurpose::KeyCertSign];
    params.not_before = now - BACKDATE;
    params.not_after = params.not_before + AUTHORITY_LIFETIME - Duration::SECOND;

    let certificate = params
        .self_signed(&signing_key)
        .map_err(|error| Error::Issue(format!("cannot sign the authority. {error}")))?;
    write_pair(path, &certificate.pem(), key, &signing_key.serialize_pem())?;

    Ok(Authority::Present {
        chain: vec![certificate.der().clone()],
        key: PrivateKeyDer::try_from(signing_key.serialize_der())
            .map_err(|error| Error::Issue(error.into()))?,
        expires: params.not_after,
    })
}

/// Sign a certificate for `names` with a fresh ECDSA P-256 key, answering the chain the
/// listener serves and the key in PEM, and the certificate alone in DER.
fn sign(
    names: &[SubjectName],
    authority_chain: &[CertificateDer<'static>],
    authority_key: &PrivateKeyDer<'static>,
    not_before: OffsetDateTime,
    not_after: OffsetDateTime,
) -> Result<(String, String, Vec<u8>), Error> {
    let issue = |error: rcgen::Error| Error::Issue(error.to_string());
    let authority_key = rcgen::KeyPair::try_from(authority_key).map_err(issue)?;
    let issuer =
        rcgen::Issuer::from_ca_cert_der(&authority_chain[0], authority_key).map_err(issue)?;
    let key = rcgen::KeyPair::generate_for(&rcgen::PKCS_ECDSA_P256_SHA256).map_err(issue)?;

    let mut params = rcgen::CertificateParams::default();
    params.distinguished_name = rcgen::DistinguishedName::new();
    params
        .distinguished_name
        .push(rcgen::DnType::CommonName, "Ceres");
    params.subject_alt_names = names
        .iter()
        .map(SubjectName::san)
        .collect::<Result<_, _>>()?;
    params.key_usages = vec![rcgen::KeyUsagePurpose::DigitalSignature];
    params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
    params.use_authority_key_identifier_extension = true;
    params.not_before = not_before;
    params.not_after = not_after;

    let certificate = params.signed_by(&key, &issuer).map_err(issue)?;
    let mut chain = certificate.pem();
    for authority in authority_chain {
        chain.push_str(&encode_certificate(authority));
    }

    Ok((chain, key.serialize_pem(), certificate.der().to_vec()))
}

/// The SHA-256 fingerprint of a DER certificate, as colon-separated uppercase hex.
pub fn fingerprint(der: &[u8]) -> String {
    Sha256::digest(der)
        .iter()
        .map(|byte| format!("{byte:02X}"))
        .collect::<Vec<_>>()
        .join(":")
}

/// Write a certificate and its key, each beside its path and renamed over it.
///
/// Both are written in full before either replaces what is there, so a failed write leaves
/// the existing files alone. The key is renamed into place first, so a certificate never
/// stands without its key.
pub fn write_pair(
    certificate_path: &Path,
    certificate: &str,
    key_path: &Path,
    key: &str,
) -> Result<(), Error> {
    let failed = |path: &Path| {
        let path = path.display().to_string();
        move |source| Error::Write { path, source }
    };
    for path in [certificate_path, key_path] {
        ceres_config::create_parent_directory(path).map_err(failed(path))?;
    }

    let staged_certificate =
        stage(certificate_path, certificate, 0o644).map_err(failed(certificate_path))?;
    let staged_key = stage(key_path, key, 0o600).map_err(failed(key_path))?;
    staged_key
        .persist(key_path)
        .map_err(|error| failed(key_path)(error.error))?;
    staged_certificate
        .persist(certificate_path)
        .map_err(|error| failed(certificate_path)(error.error))?;
    Ok(())
}

/// Write `contents` to a temporary file beside `path`, created with `mode` on Unix, ready
/// to be renamed over it.
fn stage(path: &Path, contents: &str, mode: u32) -> std::io::Result<tempfile::NamedTempFile> {
    use std::io::Write;

    let directory = match path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent,
        _ => Path::new("."),
    };
    let mut builder = tempfile::Builder::new();
    builder.prefix(".ceres-certificate-");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        builder.permissions(std::fs::Permissions::from_mode(mode));
    }
    #[cfg(not(unix))]
    let _ = mode;

    let mut file = builder.tempfile_in(directory)?;
    file.write_all(contents.as_bytes())?;
    file.as_file().sync_all()?;
    Ok(file)
}

/// The machine's hostname, when it is one a certificate can name.
#[cfg(unix)]
pub fn hostname() -> Option<String> {
    let mut buffer = [0u8; 256];
    // SAFETY: the buffer is writable for its whole length, which is what is passed.
    let status = unsafe { libc::gethostname(buffer.as_mut_ptr().cast(), buffer.len()) };
    if status != 0 {
        return None;
    }

    let end = buffer.iter().position(|&byte| byte == 0)?;
    let name = std::str::from_utf8(&buffer[..end]).ok()?;
    let valid = !name.is_empty()
        && name
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "-.".contains(character));
    valid.then(|| name.to_string())
}

#[cfg(not(unix))]
pub fn hostname() -> Option<String> {
    std::env::var("COMPUTERNAME").ok()
}

/// Every address assigned to the machine's network interfaces.
#[cfg(unix)]
fn interface_addresses() -> Vec<IpAddr> {
    let mut addresses = Vec::new();
    let mut head: *mut libc::ifaddrs = std::ptr::null_mut();
    // SAFETY: getifaddrs fills `head` with a list that stays valid until freeifaddrs.
    if unsafe { libc::getifaddrs(&mut head) } != 0 {
        return addresses;
    }

    let mut cursor = head;
    while !cursor.is_null() {
        // SAFETY: every node of the list is valid until freeifaddrs below, and an address
        // is read as the socket address type its family names.
        unsafe {
            let entry = &*cursor;
            if !entry.ifa_addr.is_null() {
                match i32::from((*entry.ifa_addr).sa_family) {
                    libc::AF_INET => {
                        let address = &*entry.ifa_addr.cast::<libc::sockaddr_in>();
                        let bits = u32::from_be(address.sin_addr.s_addr);
                        addresses.push(IpAddr::V4(Ipv4Addr::from(bits)));
                    }
                    libc::AF_INET6 => {
                        let address = &*entry.ifa_addr.cast::<libc::sockaddr_in6>();
                        addresses.push(IpAddr::V6(Ipv6Addr::from(address.sin6_addr.s6_addr)));
                    }
                    _ => {}
                }
            }
            cursor = entry.ifa_next;
        }
    }

    // SAFETY: `head` came from getifaddrs and nothing borrowed from it outlives this call.
    unsafe { libc::freeifaddrs(head) };
    addresses
}

#[cfg(not(unix))]
fn interface_addresses() -> Vec<IpAddr> {
    Vec::new()
}

/// The authority certificate at `path` clients trust, as PEM, and its SHA-256 fingerprint.
///
/// Only the first certificate is answered, re-encoded, so nothing else in the file leaks.
pub fn authority_certificate(path: &Path) -> Result<(String, String), Error> {
    let chain = read_certificates(path)?;
    Ok((encode_certificate(&chain[0]), fingerprint(&chain[0])))
}

/// A DER certificate as PEM, with the line endings rcgen writes.
fn encode_certificate(der: &[u8]) -> String {
    let config = pem::EncodeConfig::new().set_line_ending(pem::LineEnding::LF);
    pem::encode_config(&pem::Pem::new("CERTIFICATE", der.to_vec()), config)
}

/// Create an authority at `path` and `key`, for tests that supply one.
#[cfg(test)]
pub(crate) fn write_authority(path: &Path, key: &Path) {
    create_authority(path, key, OffsetDateTime::now_utc()).unwrap();
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;
    use std::time::SystemTime;

    use rustls::client::danger::ServerCertVerifier;
    use x509_parser::extensions::ParsedExtension;

    use super::*;

    const DAY: i64 = 24 * 60 * 60;

    /// A project directory with its managed certificate and default authority inside it.
    struct Project {
        _directory: tempfile::TempDir,
        certificate: ServerCertificateConfig,
        issuance: Issuance,
    }

    impl Project {
        fn new() -> Self {
            Self::lasting(365)
        }

        /// A project issuing certificates valid for `days`.
        fn lasting(days: u32) -> Self {
            let directory = tempfile::tempdir().unwrap();
            let tls = directory.path().join(".ceres/tls");
            Self {
                certificate: ServerCertificateConfig {
                    path: tls.join("server.crt"),
                    key: tls.join("server.key"),
                    key_password: None,
                    auto: Some(ServerCertificateAutoConfig::default()),
                },
                issuance: Issuance {
                    days,
                    authority: ServerCertificateAuthorityConfig {
                        path: tls.join("ca.crt"),
                        key: tls.join("ca.key"),
                        key_password: None,
                    },
                    supplied: false,
                },
                _directory: directory,
            }
        }

        fn ensure(&self, names: &[SubjectName], now: OffsetDateTime) -> Result<Managed, Error> {
            self.issuance.ensure(&self.certificate, names, now, false)
        }

        fn state(&self) -> PathBuf {
            self.issuance
                .authority
                .path
                .parent()
                .unwrap()
                .parent()
                .unwrap()
                .to_owned()
        }

        fn leaf(&self) -> Vec<u8> {
            read_certificates(&self.certificate.path).unwrap()[0].to_vec()
        }

        fn authority(&self) -> Vec<u8> {
            read_certificates(&self.issuance.authority.path).unwrap()[0].to_vec()
        }
    }

    fn localhost() -> Vec<SubjectName> {
        vec![SubjectName::Dns("localhost".into())]
    }

    fn now() -> OffsetDateTime {
        OffsetDateTime::now_utc()
    }

    #[test]
    fn a_fresh_project_gets_an_authority_and_a_certificate_it_signs() {
        let project = Project::new();
        let names = [
            SubjectName::Dns("localhost".into()),
            SubjectName::Ip("10.20.1.230".parse().unwrap()),
        ];
        let managed = project.ensure(&names, now()).unwrap();
        assert!(managed.created_authority);
        assert_eq!(managed.issued, Some(Renewal::Missing));
        assert_eq!(managed.authority, project.issuance.authority.path);
        assert_eq!(managed.names, names);
        assert_eq!(managed.fingerprint, fingerprint(&project.leaf()));
        assert_eq!(
            std::fs::read_to_string(project.state().join(".gitignore")).unwrap(),
            "*\n"
        );

        // The served chain is the certificate, then the authority clients trust.
        let chain = read_certificates(&project.certificate.path).unwrap();
        assert_eq!(chain.len(), 2);
        assert_eq!(chain[1].to_vec(), project.authority());

        let (_, authority) = x509_parser::parse_x509_certificate(&chain[1]).unwrap();
        let constraints = authority.basic_constraints().unwrap().unwrap().value;
        assert!(constraints.ca);
        assert_eq!(constraints.path_len_constraint, Some(0));
        let usage = authority.key_usage().unwrap().unwrap().value;
        assert!(usage.key_cert_sign());
        let lifetime = authority.validity().not_after.timestamp()
            - authority.validity().not_before.timestamp();
        assert_eq!(lifetime, 3650 * DAY - 1);
        assert_eq!(
            authority
                .public_key()
                .algorithm
                .parameters
                .as_ref()
                .unwrap()
                .as_oid()
                .unwrap(),
            x509_parser::oid_registry::OID_EC_P256
        );

        let (_, leaf) = x509_parser::parse_x509_certificate(&chain[0]).unwrap();
        assert!(!leaf.is_ca());
        assert!(
            leaf.extended_key_usage()
                .unwrap()
                .unwrap()
                .value
                .server_auth
        );
        assert_eq!(carried_names(&leaf), names);
        assert_eq!(
            leaf.public_key()
                .algorithm
                .parameters
                .as_ref()
                .unwrap()
                .as_oid()
                .unwrap(),
            x509_parser::oid_registry::OID_EC_P256
        );
        assert!(signed_by(&leaf, &chain[1]));
        assert!(leaf.extensions().iter().any(|extension| matches!(
            extension.parsed_extension(),
            ParsedExtension::AuthorityKeyIdentifier(_)
        )));

        // Clients trusting only the authority accept the certificate for every name.
        let roots = {
            let mut roots = rustls::RootCertStore::empty();
            roots.add(chain[1].clone()).unwrap();
            Arc::new(roots)
        };
        let verifier = rustls::client::WebPkiServerVerifier::builder_with_provider(
            roots,
            Arc::new(rustls::crypto::ring::default_provider()),
        )
        .build()
        .unwrap();
        for name in ["localhost", "10.20.1.230"] {
            verifier
                .verify_server_cert(
                    &chain[0],
                    &chain[1..],
                    &name.try_into().unwrap(),
                    &[],
                    rustls::pki_types::UnixTime::since_unix_epoch(
                        SystemTime::now()
                            .duration_since(SystemTime::UNIX_EPOCH)
                            .unwrap(),
                    ),
                )
                .unwrap_or_else(|error| panic!("{name}: {error}"));
        }
    }

    #[cfg(unix)]
    #[test]
    fn keys_are_readable_by_their_owner_alone() {
        use std::os::unix::fs::PermissionsExt;

        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();
        let mode = |path: &Path| std::fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode(&project.certificate.key), 0o600);
        assert_eq!(mode(&project.issuance.authority.key), 0o600);
        assert_eq!(mode(&project.certificate.path), 0o644);
        assert_eq!(mode(&project.issuance.authority.path), 0o644);
        // Nothing staged is left beside them.
        let leftovers: Vec<_> = std::fs::read_dir(project.certificate.path.parent().unwrap())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .filter(|name| name.to_string_lossy().starts_with(".ceres-certificate-"))
            .collect();
        assert!(leftovers.is_empty(), "{leftovers:?}");
    }

    #[test]
    fn validity_spans_the_configured_days_to_the_second() {
        let project = Project::new();
        let issued_at = now();
        let managed = project.ensure(&localhost(), issued_at).unwrap();
        let der = project.leaf();
        let leaf = parse(&der);
        let validity = leaf.validity();
        let not_before = validity.not_before.timestamp();
        assert_eq!(not_before, issued_at.unix_timestamp() - 60 * 60);
        assert_eq!(validity.not_after.timestamp() - not_before, 365 * DAY - 1);
        assert_eq!(
            managed.expires.unix_timestamp(),
            validity.not_after.timestamp()
        );
    }

    #[test]
    fn current_certificates_and_authorities_are_left_alone() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();
        let leaf = std::fs::read(&project.certificate.path).unwrap();
        let key = std::fs::read(&project.certificate.key).unwrap();
        let authority = std::fs::read(&project.issuance.authority.path).unwrap();

        let managed = project.ensure(&localhost(), now()).unwrap();
        assert_eq!(managed.issued, None);
        assert!(!managed.created_authority);
        assert_eq!(managed.names, localhost());
        assert_eq!(managed.notices(&project.certificate.path), []);
        assert_eq!(std::fs::read(&project.certificate.path).unwrap(), leaf);
        assert_eq!(std::fs::read(&project.certificate.key).unwrap(), key);

        // Forcing reissues the certificate and still keeps the authority.
        let forced = project
            .issuance
            .ensure(&project.certificate, &localhost(), now(), true)
            .unwrap();
        assert_eq!(forced.issued, Some(Renewal::Forced));
        assert_ne!(std::fs::read(&project.certificate.path).unwrap(), leaf);
        assert_eq!(
            std::fs::read(&project.issuance.authority.path).unwrap(),
            authority
        );
    }

    #[test]
    fn certificates_renew_within_thirty_days_of_expiry() {
        let project = Project::lasting(365);
        let issued = project.ensure(&localhost(), now()).unwrap();
        let leaf = project.leaf();

        let window = Duration::days(30);
        let outside = issued.expires - window - Duration::SECOND;
        assert_eq!(project.ensure(&localhost(), outside).unwrap().issued, None);
        assert_eq!(project.leaf(), leaf);

        let inside = issued.expires - window + Duration::SECOND;
        let renewed = project.ensure(&localhost(), inside).unwrap();
        assert_eq!(renewed.issued, Some(Renewal::Expiring(issued.expires)));
        assert_ne!(project.leaf(), leaf);

        // An expired certificate renews the same way.
        let project = Project::new();
        let issued = project.ensure(&localhost(), now()).unwrap();
        let later = issued.expires + Duration::DAY;
        assert_eq!(
            project.ensure(&localhost(), later).unwrap().issued,
            Some(Renewal::Expiring(issued.expires))
        );
    }

    #[test]
    fn short_lived_certificates_renew_with_a_third_of_their_lifetime_left() {
        let project = Project::lasting(30);
        let issued = project.ensure(&localhost(), now()).unwrap();
        let leaf = project.leaf();

        // A fresh certificate is kept rather than reissued at every check.
        assert_eq!(project.ensure(&localhost(), now()).unwrap().issued, None);

        let window = Duration::days(10);
        let outside = issued.expires - window - Duration::SECOND;
        assert_eq!(project.ensure(&localhost(), outside).unwrap().issued, None);
        assert_eq!(project.leaf(), leaf);

        let inside = issued.expires - window + Duration::SECOND;
        let renewed = project.ensure(&localhost(), inside).unwrap();
        assert_eq!(renewed.issued, Some(Renewal::Expiring(issued.expires)));
        assert_ne!(project.leaf(), leaf);
    }

    #[test]
    fn certificates_renew_when_a_required_name_is_missing() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();

        let wider = [
            SubjectName::Dns("localhost".into()),
            SubjectName::Ip("10.20.1.230".parse().unwrap()),
        ];
        let renewed = project.ensure(&wider, now()).unwrap();
        assert_eq!(
            renewed.issued,
            Some(Renewal::MissingNames(vec![SubjectName::Ip(
                "10.20.1.230".parse().unwrap()
            )]))
        );
        assert_eq!(carried_names(&parse(&project.leaf())), wider);

        // A certificate naming more than required is kept, and DNS names match without case.
        let narrower = [SubjectName::Dns("LOCALHOST".into())];
        assert_eq!(
            project
                .ensure(&SubjectName::unique(narrower), now())
                .unwrap()
                .issued,
            None
        );
    }

    #[test]
    fn certificates_another_authority_signed_are_reissued() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();

        // A certificate from elsewhere, self-signed, at the managed path.
        let foreign = rcgen::generate_simple_self_signed(["localhost".to_string()]).unwrap();
        write_pair(
            &project.certificate.path,
            &foreign.cert.pem(),
            &project.certificate.key,
            &foreign.signing_key.serialize_pem(),
        )
        .unwrap();
        assert_eq!(
            project.ensure(&localhost(), now()).unwrap().issued,
            Some(Renewal::ForeignIssuer)
        );

        // A certificate the previous authority signed, after the authority was replaced.
        let leaf = project.leaf();
        std::fs::remove_file(&project.issuance.authority.path).unwrap();
        std::fs::remove_file(&project.issuance.authority.key).unwrap();
        let managed = project.ensure(&localhost(), now()).unwrap();
        assert!(managed.created_authority);
        assert_eq!(managed.issued, Some(Renewal::ForeignIssuer));
        assert_ne!(project.leaf(), leaf);
        assert!(signed_by(&parse(&project.leaf()), &project.authority()));
    }

    #[test]
    fn unreadable_certificates_are_reissued() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();

        std::fs::write(&project.certificate.path, "not a certificate").unwrap();
        assert!(matches!(
            project.ensure(&localhost(), now()).unwrap().issued,
            Some(Renewal::Unparsable(_))
        ));

        // A key that does not belong to the certificate.
        let other = rcgen::KeyPair::generate().unwrap();
        std::fs::write(&project.certificate.key, other.serialize_pem()).unwrap();
        assert!(matches!(
            project.ensure(&localhost(), now()).unwrap().issued,
            Some(Renewal::Unparsable(_))
        ));

        std::fs::remove_file(&project.certificate.key).unwrap();
        assert_eq!(
            project.ensure(&localhost(), now()).unwrap().issued,
            Some(Renewal::Missing)
        );
    }

    #[test]
    fn certificates_not_valid_yet_are_reissued() {
        let project = Project::new();
        let issued = project.ensure(&localhost(), now() + Duration::DAY).unwrap();
        assert!(issued.issued.is_some());
        assert_eq!(
            project.ensure(&localhost(), now()).unwrap().issued,
            Some(Renewal::NotYetValid)
        );
    }

    #[test]
    fn supplied_authorities_are_never_created() {
        let project = Project::new();
        let supplied = Issuance {
            supplied: true,
            ..project.issuance.clone()
        };
        let error = supplied
            .ensure(&project.certificate, &localhost(), now(), false)
            .unwrap_err();
        assert_eq!(
            error.to_string(),
            format!(
                "{} does not exist. Ceres never creates the certificate authority `auto.ca` \
                 names.",
                supplied.authority.path.display()
            )
        );
        assert!(!supplied.authority.path.exists());
        assert!(!supplied.authority.key.exists());
        assert!(!project.certificate.path.exists());

        // `Managed::ensure` reads `auto.ca` as supplied.
        let auto = ServerCertificateAutoConfig {
            ca: Some(supplied.authority.clone()),
            ..ServerCertificateAutoConfig::default()
        };
        let error = Managed::ensure(
            Path::new(""),
            &project.certificate,
            &auto,
            &localhost(),
            now(),
            false,
        )
        .unwrap_err();
        assert!(matches!(error, Error::AuthorityMissing { .. }), "{error}");
        assert!(!supplied.authority.path.exists());
    }

    #[test]
    fn half_an_authority_is_never_replaced() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();
        let authority = &project.issuance.authority;
        std::fs::remove_file(&authority.key).unwrap();
        let error = project.ensure(&localhost(), now()).unwrap_err();
        assert_eq!(
            error.to_string(),
            format!(
                "{present} exists without {missing}. Restore {missing}, or remove {present} for \
                 Ceres to create a new certificate authority, which every client then has to \
                 trust again.",
                present = authority.path.display(),
                missing = authority.key.display()
            )
        );
        assert!(!authority.key.exists());
    }

    #[test]
    fn authorities_whose_key_does_not_fit_are_refused() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();
        let authority = &project.issuance.authority;
        let other = rcgen::KeyPair::generate().unwrap();
        std::fs::write(&authority.key, other.serialize_pem()).unwrap();
        let leaf = project.leaf();

        let error = project
            .issuance
            .ensure(&project.certificate, &localhost(), now(), true)
            .unwrap_err();
        assert_eq!(
            error.to_string(),
            format!(
                "{} cannot sign HTTPS certificates. The key {} does not belong to it.",
                authority.path.display(),
                authority.key.display()
            )
        );
        assert_eq!(project.leaf(), leaf);
    }

    #[test]
    fn authorities_that_cannot_sign_certificates_are_refused() {
        let project = Project::new();
        let authority = project.issuance.authority.clone();

        // A server certificate where the authority belongs.
        let leaf = rcgen::generate_simple_self_signed(["localhost".to_string()]).unwrap();
        write_pair(
            &authority.path,
            &leaf.cert.pem(),
            &authority.key,
            &leaf.signing_key.serialize_pem(),
        )
        .unwrap();
        let error = project.ensure(&localhost(), now()).unwrap_err();
        assert_eq!(
            error.to_string(),
            format!(
                "{} cannot sign HTTPS certificates. It is not a certificate authority.",
                authority.path.display()
            )
        );
        assert!(!project.certificate.path.exists());

        // An authority whose key usage leaves out signing certificates.
        let key = rcgen::KeyPair::generate().unwrap();
        let mut params = rcgen::CertificateParams::default();
        params.is_ca = rcgen::IsCa::Ca(rcgen::BasicConstraints::Unconstrained);
        params.key_usages = vec![rcgen::KeyUsagePurpose::CrlSign];
        let certificate = params.self_signed(&key).unwrap();
        write_pair(
            &authority.path,
            &certificate.pem(),
            &authority.key,
            &key.serialize_pem(),
        )
        .unwrap();
        let error = project.ensure(&localhost(), now()).unwrap_err();
        assert_eq!(
            error.to_string(),
            format!(
                "{} cannot sign HTTPS certificates. Its key usage does not include signing \
                 certificates.",
                authority.path.display()
            )
        );
        assert!(!project.certificate.path.exists());
    }

    #[test]
    fn authorities_close_to_expiry_draw_a_warning_and_stay() {
        let project = Project::new();
        let authority = &project.issuance.authority;
        // Created long enough ago that 20 days of its lifetime remain.
        let created = now() - AUTHORITY_LIFETIME + Duration::days(20);
        create_authority(&authority.path, &authority.key, created).unwrap();
        let expires = parse(&project.authority())
            .validity()
            .not_after
            .to_datetime();
        let original = project.authority();

        let warning = format!(
            "The certificate authority {path} expires on {}. Ceres never renews an authority. \
             Remove {path} and {} for Ceres to create a new one, and trust the new one on each \
             client.",
            expires.date(),
            authority.key.display(),
            path = authority.path.display(),
        );
        let managed = project.ensure(&localhost(), now()).unwrap();
        assert_eq!(managed.authority_warning.as_ref(), Some(&warning));
        assert_eq!(
            managed.notices(&project.certificate.path)[0],
            Notice::Warning(warning.clone())
        );
        assert_eq!(project.authority(), original);

        // A kept certificate still reports it, and so does the check.
        let kept = project.ensure(&localhost(), now()).unwrap();
        assert_eq!(kept.issued, None);
        assert_eq!(
            kept.notices(&project.certificate.path),
            [Notice::Warning(warning.clone())]
        );
        let auto = ServerCertificateAutoConfig {
            ca: Some(authority.clone()),
            ..ServerCertificateAutoConfig::default()
        };
        let inspection = Inspection::of(&project.certificate, &auto, &localhost(), now()).unwrap();
        assert!(
            inspection
                .authority_warning
                .unwrap()
                .contains("Replace it at the paths")
        );

        // Past expiry it says so, and the authority still stays.
        let later = expires + Duration::DAY;
        let expired = project.ensure(&localhost(), later).unwrap();
        assert!(expired.authority_warning.unwrap().starts_with(&format!(
            "The certificate authority {} expired on {}, so clients no longer trust the \
                 certificates it signs.",
            authority.path.display(),
            expires.date()
        )));
        assert_eq!(project.authority(), original);

        // Further out than 30 days there is nothing to say.
        let fresh = Project::new();
        assert_eq!(
            fresh.ensure(&localhost(), now()).unwrap().authority_warning,
            None
        );
    }

    #[test]
    fn encrypted_authority_keys_decrypt_with_their_password() {
        let project = Project::new();
        project.ensure(&localhost(), now()).unwrap();
        let authority = &project.issuance.authority;
        let plain = std::fs::read_to_string(&authority.key).unwrap();
        std::fs::write(
            &authority.key,
            super::super::tests::encrypt_key(plain, "hunter2"),
        )
        .unwrap();
        std::fs::remove_file(&project.certificate.path).unwrap();

        let mut supplied = Issuance {
            supplied: true,
            ..project.issuance.clone()
        };
        let error = supplied
            .ensure(&project.certificate, &localhost(), now(), false)
            .unwrap_err();
        assert!(matches!(error, Error::Decrypt(_)), "{error}");

        supplied.authority.key_password = Some("hunter2".into());
        let managed = supplied
            .ensure(&project.certificate, &localhost(), now(), false)
            .unwrap();
        assert_eq!(managed.issued, Some(Renewal::Missing));
        assert!(signed_by(&parse(&project.leaf()), &project.authority()));
    }

    #[test]
    fn notices_announce_the_authority_and_the_certificate() {
        let project = Project::new();
        let managed = project.ensure(&localhost(), now()).unwrap();
        let notices = managed.notices(&project.certificate.path);
        assert_eq!(
            notices,
            [
                Notice::Info(format!(
                    "Created the certificate authority {}. Trust it on each client to trust \
                     the HTTPS certificate it signs.",
                    project.issuance.authority.path.display()
                )),
                Notice::Info(format!(
                    "Issued the HTTPS certificate {} for localhost, expiring {}, because there \
                     is no certificate yet.",
                    project.certificate.path.display(),
                    managed.expires.date()
                )),
            ]
        );
    }

    #[test]
    fn names_cover_the_machine_without_loopback_or_link_local_addresses() {
        let names = SubjectName::local(
            Some("Studio-Mac".into()),
            vec![
                "127.0.0.1".parse().unwrap(),
                "::1".parse().unwrap(),
                "169.254.3.4".parse().unwrap(),
                "fe80::1".parse().unwrap(),
                "10.20.1.230".parse().unwrap(),
                "10.20.1.230".parse().unwrap(),
                "fd00::5".parse().unwrap(),
            ],
        );
        assert_eq!(
            names,
            [
                SubjectName::Dns("localhost".into()),
                SubjectName::Ip("127.0.0.1".parse().unwrap()),
                SubjectName::Ip("::1".parse().unwrap()),
                SubjectName::Dns("studio-mac".into()),
                SubjectName::Ip("10.20.1.230".parse().unwrap()),
                SubjectName::Ip("fd00::5".parse().unwrap()),
            ]
        );
        assert_eq!(SubjectName::local(None, Vec::new()).len(), 3);
    }

    #[test]
    fn configured_names_replace_detected_ones() {
        let configured = ServerCertificateAutoConfig {
            ip: vec!["10.20.1.230".parse().unwrap()],
            dns: vec!["Ceres.example".into()],
            ..ServerCertificateAutoConfig::default()
        };
        let detect = || panic!("configured names are not detected");
        assert_eq!(
            SubjectName::required(&configured, detect),
            [
                SubjectName::Ip("10.20.1.230".parse().unwrap()),
                SubjectName::Dns("ceres.example".into()),
            ]
        );
        assert_eq!(
            SubjectName::required(&ServerCertificateAutoConfig::default(), localhost),
            localhost()
        );
    }

    #[test]
    fn fingerprints_are_colon_separated_hex() {
        assert_eq!(
            fingerprint(b"ceres"),
            "9D:DC:40:0D:8B:49:EF:C7:6C:3B:43:50:7D:15:78:75:B8:42:3B:56:34:5E:F0:29:13:FB:19:3F:85:E7:2E:E4"
        );
    }

    fn parse(der: &[u8]) -> X509Certificate<'_> {
        x509_parser::parse_x509_certificate(der).unwrap().1
    }
}
