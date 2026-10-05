//! TLS configuration loading.
//!
//! Builds a rustls server configuration from the `server.https` config section. Encrypted
//! private keys decrypt with `key-password`, and a `client-ca` bundle enables optional
//! client certificate verification.

use std::path::Path;
use std::sync::Arc;

use ceres_config::{ServerHttpsConfig, TlsVersion};
use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
use rustls::server::WebPkiClientVerifier;

/// A TLS loading failure.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("cannot read {path}. {source}")]
    Unreadable {
        path: String,
        source: std::io::Error,
    },
    #[error("{path} holds no usable {expected}")]
    Empty {
        path: String,
        expected: &'static str,
    },
    #[error("cannot decrypt the private key. {0}")]
    Decrypt(String),
    #[error(transparent)]
    Rustls(#[from] rustls::Error),
    #[error("{0}")]
    ClientVerifier(String),
}

/// Build the rustls configuration for the `https` section.
pub fn server_config(https: &ServerHttpsConfig) -> Result<Arc<rustls::ServerConfig>, Error> {
    let certificates = read_certificates(&https.cert)?;
    let key = read_private_key(&https.key, https.key_password.as_deref())?;

    let versions: &[&rustls::SupportedProtocolVersion] = match https.min_version {
        TlsVersion::Tls12 => &[&rustls::version::TLS12, &rustls::version::TLS13],
        TlsVersion::Tls13 => &[&rustls::version::TLS13],
    };
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let builder = rustls::ServerConfig::builder_with_provider(provider.clone())
        .with_protocol_versions(versions)?;

    let builder = match &https.client_ca {
        Some(ca_path) => {
            // A CA bundle enables client certificate verification, optional rather
            // than required.
            let mut roots = rustls::RootCertStore::empty();
            for certificate in read_certificates(ca_path)? {
                roots
                    .add(certificate)
                    .map_err(|error| Error::ClientVerifier(error.to_string()))?;
            }

            let verifier = WebPkiClientVerifier::builder_with_provider(Arc::new(roots), provider)
                .allow_unauthenticated()
                .build()
                .map_err(|error| Error::ClientVerifier(error.to_string()))?;
            builder.with_client_cert_verifier(verifier)
        }
        None => builder.with_no_client_auth(),
    };

    let mut config = builder.with_single_cert(certificates, key)?;
    // Browsers only speak HTTP/2 over TLS and only when ALPN offers it. Without `h2` every
    // video widget holds one of the six HTTP/1.1 connections a browser allows per origin.
    config.alpn_protocols = vec![b"h2".to_vec(), b"http/1.1".to_vec()];
    Ok(Arc::new(config))
}

fn read_certificates(path: &Path) -> Result<Vec<CertificateDer<'static>>, Error> {
    let text = std::fs::read(path).map_err(|source| Error::Unreadable {
        path: path.display().to_string(),
        source,
    })?;
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
    let text = std::fs::read_to_string(path).map_err(|source| Error::Unreadable {
        path: path.display().to_string(),
        source,
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
            cert: cert_path,
            key: key_path,
            key_password: password.map(str::to_string),
            ..ServerHttpsConfig::default()
        }
    }

    /// Encrypt a plain PKCS#8 key PEM under a password.
    fn encrypt_key(pem: String, password: &str) -> String {
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
        let loaded = server_config(&config).unwrap();
        assert_eq!(
            loaded.alpn_protocols,
            [b"h2".to_vec(), b"http/1.1".to_vec()]
        );
    }

    #[test]
    fn encrypted_keys_decrypt_with_the_configured_password() {
        let directory = tempfile::tempdir().unwrap();
        let config = https(directory.path(), Some("hunter2"), |key| {
            encrypt_key(key, "hunter2")
        });
        assert!(server_config(&config).is_ok());

        let config = https(directory.path(), None, |key| encrypt_key(key, "hunter2"));
        assert!(matches!(server_config(&config), Err(Error::Decrypt(_))));
    }

    #[test]
    fn missing_files_name_their_path() {
        let directory = tempfile::tempdir().unwrap();
        let mut config = https(directory.path(), None, |key| key);
        config.cert = directory.path().join("absent.pem");
        let error = server_config(&config).unwrap_err();
        assert!(error.to_string().contains("absent.pem"), "{error}");
    }

    #[test]
    fn min_versions_floor_the_negotiation() {
        let directory = tempfile::tempdir().unwrap();
        let mut config = https(directory.path(), None, |key| key);
        assert_eq!(
            handshake(&config, &rustls::version::TLS12),
            Some(rustls::ProtocolVersion::TLSv1_2)
        );
        config.min_version = TlsVersion::Tls13;
        assert_eq!(handshake(&config, &rustls::version::TLS12), None);
        assert_eq!(
            handshake(&config, &rustls::version::TLS13),
            Some(rustls::ProtocolVersion::TLSv1_3)
        );
    }

    /// Complete an in-memory handshake with a client offering only `version`, returning the
    /// negotiated version or `None` when the server refuses it.
    fn handshake(
        https: &ServerHttpsConfig,
        version: &'static rustls::SupportedProtocolVersion,
    ) -> Option<rustls::ProtocolVersion> {
        let mut roots = rustls::RootCertStore::empty();
        roots.add_parsable_certificates(read_certificates(&https.cert).unwrap());
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let client = rustls::ClientConfig::builder_with_provider(provider)
            .with_protocol_versions(&[version])
            .unwrap()
            .with_root_certificates(roots)
            .with_no_client_auth();
        let mut client =
            rustls::ClientConnection::new(Arc::new(client), "localhost".try_into().unwrap())
                .unwrap();
        let mut server = rustls::ServerConnection::new(server_config(https).unwrap()).unwrap();

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
        client.protocol_version()
    }

    /// A fixed seed for the key-encryption test, randomness has no bearing on it.
    fn rand_seed() -> impl rand_core::CryptoRngCore {
        use rand_core::SeedableRng;
        rand_chacha::ChaCha20Rng::from_seed([7; 32])
    }
}
