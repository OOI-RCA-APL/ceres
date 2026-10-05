//! The `generate` command group, rendering project resources.

use std::fmt;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::path::{Path, PathBuf};

use ceres_config::{DEFAULT_TLS_CERT, DEFAULT_TLS_KEY};
use sha2::{Digest, Sha256};
use time::{Duration, OffsetDateTime};

use crate::cli::{CertificateArgs, OpenapiArgs, SchemaFormat};
use crate::error::{Exit, Result, fail, failure};
use crate::output::Output;
use crate::project::Project;

/// Generate the OpenAPI schema and write it to a file or stdout.
pub fn openapi(args: &OpenapiArgs) -> Result<()> {
    let document = ceres_server::openapi_document(crate::cli::VERSION);
    let rendered = match args.format {
        SchemaFormat::Yaml => {
            // The YAML emitter has no indentation setting, so an indent it cannot
            // honor is refused rather than silently rendered at two.
            if args.indent != 2 {
                return Err(Exit::failed(
                    "YAML output uses a fixed indent of 2. --indent applies to JSON output.",
                ));
            }

            yaml_serde::to_string(&document)
                .map_err(|error| Exit::failed(format!("Cannot render the schema. {error}")))?
        }
        SchemaFormat::Json => {
            let indent = " ".repeat(args.indent as usize);
            let mut rendered = Vec::new();
            let formatter = serde_json::ser::PrettyFormatter::with_indent(indent.as_bytes());
            let mut serializer = serde_json::Serializer::with_formatter(&mut rendered, formatter);
            serde::Serialize::serialize(&document, &mut serializer)
                .map_err(|error| Exit::failed(format!("Cannot render the schema. {error}")))?;
            String::from_utf8(rendered).expect("serde_json writes UTF-8")
        }
    };

    match &args.output {
        Some(path) => std::fs::write(path, rendered)
            .map_err(|error| Exit::failed(format!("Cannot write {}. {error}", path.display()))),
        None => {
            use std::io::Write;

            let stdout = std::io::stdout();
            let mut lock = stdout.lock();
            let _ = lock.write_all(rendered.as_bytes());
            Ok(())
        }
    }
}

/// A name a certificate vouches for.
#[derive(Debug, Clone, PartialEq, Eq)]
enum SubjectName {
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

/// Generate a self-signed certificate and key for the HTTPS listener.
///
/// Both go to the paths the `server.https` section names, or to the default
/// `.ceres/tls` paths when there is no such section. Existing files are only replaced
/// with `--force`. The key file is readable by its owner alone.
pub fn certificate(args: &CertificateArgs, project: &Project, output: &Output) -> Result<()> {
    let meta = project.load_meta()?;
    let (cert, key) = match &meta.server.https {
        Some(https) => (https.cert.clone(), https.key.clone()),
        None => (
            PathBuf::from(DEFAULT_TLS_CERT),
            PathBuf::from(DEFAULT_TLS_KEY),
        ),
    };
    let cert_path = project.directory().join(&cert);
    let key_path = project.directory().join(&key);

    if !args.force {
        for (shown, path) in [(&cert, &cert_path), (&key, &key_path)] {
            if path.exists() {
                fail!(
                    "{} already exists. Pass --force to replace it.",
                    shown.display()
                );
            }
        }
    }

    let state = project.state_directory();
    if cert_path.starts_with(&state) || key_path.starts_with(&state) {
        project.create_state_directory()?;
    }

    let names = subject_names(args, hostname(), interface_addresses());
    let now = OffsetDateTime::now_utc();
    let expires = now + Duration::days(i64::from(args.days));
    let (certificate_pem, key_pem, der) = sign(&names, now, expires)?;

    for path in [&cert_path, &key_path] {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| failure!("Failed to create {}. {error}", parent.display()))?;
        }
    }
    std::fs::write(&cert_path, certificate_pem)
        .map_err(|error| failure!("Failed to write {}. {error}", cert.display()))?;
    write_private(&key_path, &key_pem)
        .map_err(|error| failure!("Failed to write {}. {error}", key.display()))?;

    let names: Vec<String> = names.iter().map(ToString::to_string).collect();
    output.write(format!("Wrote the certificate to {}.", cert.display()));
    output.write(format!("Wrote the key to {}.", key.display()));
    output.write(format!("Names: {}", names.join(", ")));
    output.write(format!("Expires: {} ({} days)", expires.date(), args.days));
    output.write(format!("SHA-256 fingerprint: {}", fingerprint(&der)));
    Ok(())
}

/// The names a generated certificate vouches for, in order and without repeats.
///
/// Those are localhost and the loopback addresses, the machine's hostname, its interface
/// addresses other than loopback and link-local ones, then the names asked for.
fn subject_names(
    args: &CertificateArgs,
    hostname: Option<String>,
    interfaces: Vec<IpAddr>,
) -> Vec<SubjectName> {
    let mut names = vec![
        SubjectName::Dns("localhost".to_string()),
        SubjectName::Ip(IpAddr::V4(Ipv4Addr::LOCALHOST)),
        SubjectName::Ip(IpAddr::V6(Ipv6Addr::LOCALHOST)),
    ];
    names.extend(hostname.map(SubjectName::Dns));
    names.extend(
        interfaces
            .into_iter()
            .filter(|address| !address.is_loopback() && !is_link_local(address))
            .map(SubjectName::Ip),
    );
    names.extend(args.ips.iter().copied().map(SubjectName::Ip));
    names.extend(args.dns.iter().cloned().map(SubjectName::Dns));

    let mut unique: Vec<SubjectName> = Vec::new();
    for name in names {
        let name = match name {
            SubjectName::Dns(name) => SubjectName::Dns(name.to_ascii_lowercase()),
            name => name,
        };
        if !unique.contains(&name) {
            unique.push(name);
        }
    }
    unique
}

/// Whether an address only reaches its own link, which no client would name a server by.
fn is_link_local(address: &IpAddr) -> bool {
    match address {
        IpAddr::V4(address) => address.is_link_local(),
        IpAddr::V6(address) => (address.segments()[0] & 0xffc0) == 0xfe80,
    }
}

/// Sign a certificate for `names` with a fresh ECDSA P-256 key, answering the
/// certificate and key in PEM and the certificate in DER.
fn sign(
    names: &[SubjectName],
    not_before: OffsetDateTime,
    not_after: OffsetDateTime,
) -> Result<(String, String, Vec<u8>)> {
    let key = rcgen::KeyPair::generate_for(&rcgen::PKCS_ECDSA_P256_SHA256)
        .map_err(|error| failure!("Failed to generate a key. {error}"))?;

    let mut params = rcgen::CertificateParams::default();
    params.distinguished_name = rcgen::DistinguishedName::new();
    params
        .distinguished_name
        .push(rcgen::DnType::CommonName, "Ceres");
    params.subject_alt_names = names
        .iter()
        .map(|name| match name {
            SubjectName::Dns(name) => rcgen::string::Ia5String::try_from(name.as_str())
                .map(rcgen::SanType::DnsName)
                .map_err(|error| failure!("{name:?} cannot be a DNS name. {error}")),
            SubjectName::Ip(address) => Ok(rcgen::SanType::IpAddress(*address)),
        })
        .collect::<Result<_>>()?;
    params.key_usages = vec![rcgen::KeyUsagePurpose::DigitalSignature];
    params.extended_key_usages = vec![rcgen::ExtendedKeyUsagePurpose::ServerAuth];
    params.not_before = not_before;
    params.not_after = not_after;

    let certificate = params
        .self_signed(&key)
        .map_err(|error| failure!("Failed to sign the certificate. {error}"))?;
    Ok((
        certificate.pem(),
        key.serialize_pem(),
        certificate.der().to_vec(),
    ))
}

/// The SHA-256 fingerprint of a DER certificate, as colon-separated uppercase hex.
fn fingerprint(der: &[u8]) -> String {
    Sha256::digest(der)
        .iter()
        .map(|byte| format!("{byte:02X}"))
        .collect::<Vec<_>>()
        .join(":")
}

/// Write a file only its owner can read, narrowing the mode of one already there.
fn write_private(path: &Path, contents: &str) -> std::io::Result<()> {
    use std::io::Write;

    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};

        options.mode(0o600);
        let mut file = options.open(path)?;
        file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
        file.write_all(contents.as_bytes())
    }
    #[cfg(not(unix))]
    {
        options.open(path)?.write_all(contents.as_bytes())
    }
}

/// The machine's hostname, when it is one a certificate can name.
#[cfg(unix)]
fn hostname() -> Option<String> {
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
fn hostname() -> Option<String> {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn args(ips: &[&str], dns: &[&str], force: bool) -> CertificateArgs {
        CertificateArgs {
            ips: ips.iter().map(|ip| ip.parse().unwrap()).collect(),
            dns: dns.iter().map(ToString::to_string).collect(),
            days: 825,
            force,
        }
    }

    #[test]
    fn names_cover_the_machine_then_what_was_asked_for() {
        let names = subject_names(
            &args(
                &["10.0.0.9", "127.0.0.1"],
                &["Ceres.example", "localhost"],
                false,
            ),
            Some("bench".to_string()),
            vec![
                "127.0.0.1".parse().unwrap(),
                "192.168.1.20".parse().unwrap(),
                "169.254.3.4".parse().unwrap(),
                "fe80::1".parse().unwrap(),
                "fd00::20".parse().unwrap(),
            ],
        );
        let names: Vec<String> = names.iter().map(ToString::to_string).collect();
        assert_eq!(
            names,
            [
                "localhost",
                "127.0.0.1",
                "::1",
                "bench",
                "192.168.1.20",
                "fd00::20",
                "10.0.0.9",
                "ceres.example",
            ]
        );
    }

    #[test]
    fn certificates_load_into_the_https_listener() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(directory.path().join("ceres.yaml"), "").unwrap();
        let project = Project::at(directory.path().join("ceres.yaml"));
        let output = Output::new(Some(false));

        certificate(&args(&[], &["bench.example"], false), &project, &output).unwrap();

        let state = directory.path().join(".ceres");
        assert_eq!(
            std::fs::read_to_string(state.join(".gitignore")).unwrap(),
            "*\n"
        );
        let https = ceres_config::ServerHttpsConfig {
            cert: state.join("tls/server.crt"),
            key: state.join("tls/server.key"),
            ..ceres_config::ServerHttpsConfig::default()
        };
        let expiry = ceres_server::certificate_expiry(&https).unwrap();
        let days = (expiry - OffsetDateTime::now_utc().unix_timestamp()) / 86_400;
        assert!((824..=825).contains(&days), "{days}");

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            let mode = std::fs::metadata(&https.key).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, 0o600);
        }
    }

    #[test]
    fn existing_files_are_replaced_only_with_force() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(
            directory.path().join("ceres.yaml"),
            "server:\n  https:\n    cert: certs/site.crt\n    key: certs/site.key\n",
        )
        .unwrap();
        let project = Project::at(directory.path().join("ceres.yaml"));
        let output = Output::new(Some(false));

        // The configured paths are written, and no `.ceres` directory is needed for them.
        certificate(&args(&[], &[], false), &project, &output).unwrap();
        let cert = directory.path().join("certs/site.crt");
        let first = std::fs::read_to_string(&cert).unwrap();
        assert!(!directory.path().join(".ceres").exists());

        let error = certificate(&args(&[], &[], false), &project, &output).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("certs/site.crt already exists. Pass --force to replace it."),
            "{error}"
        );
        assert_eq!(std::fs::read_to_string(&cert).unwrap(), first);

        certificate(&args(&[], &[], true), &project, &output).unwrap();
        assert_ne!(std::fs::read_to_string(&cert).unwrap(), first);
    }

    #[test]
    fn fingerprints_are_colon_separated_hex() {
        assert_eq!(
            fingerprint(b"abc"),
            "BA:78:16:BF:8F:01:CF:EA:41:41:40:DE:5D:AE:22:23:B0:03:61:A3:96:17:7A:9C:B4:10:FF:61:F2:00:15:AD"
        );
    }
}
