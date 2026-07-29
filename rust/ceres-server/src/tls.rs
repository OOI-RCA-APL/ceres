//! TLS configuration loading.
//!
//! Builds a rustls server configuration from the `ssl` config section. Every protocol
//! constant the section's `version` accepts floors the negotiation at TLS 1.2, matching
//! Python's own default minimum, so the offered versions are always 1.2 and 1.3.
//! Encrypted private keys decrypt with `key_password`, and a `ca_certs` bundle enables
//! optional client certificate verification.

use std::path::Path;
use std::sync::Arc;

use ceres_config::ServerSslConfig;
use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
use rustls::server::WebPkiClientVerifier;

/// A TLS loading failure.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("the ssl section needs both a key and a certificate")]
    Incomplete,
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

/// Build the rustls configuration for the `ssl` section, or `None` when it carries no
/// certificate material.
pub fn server_config(ssl: &ServerSslConfig) -> Result<Option<Arc<rustls::ServerConfig>>, Error> {
    let (key_path, cert_path) = match (&ssl.key, &ssl.cert) {
        (Some(key), Some(cert)) => (key, cert),
        (None, None) => return Ok(None),
        _ => return Err(Error::Incomplete),
    };

    let certificates = read_certificates(cert_path)?;
    let key = read_private_key(key_path, ssl.key_password.as_deref())?;

    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let builder = rustls::ServerConfig::builder_with_provider(provider.clone())
        .with_protocol_versions(&[&rustls::version::TLS12, &rustls::version::TLS13])?;

    let builder = match &ssl.ca_certs {
        Some(ca_path) => {
            // A CA bundle enables client certificate verification, optional rather than
            // required, matching how the Python server treated the setting.
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

    Ok(Some(Arc::new(builder.with_single_cert(certificates, key)?)))
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
mod tests {
    use super::*;

    /// Write one self-signed identity's certificate and key, the key transformed first.
    fn ssl(
        directory: &Path,
        password: Option<&str>,
        transform_key: impl Fn(String) -> String,
    ) -> ServerSslConfig {
        let certified = rcgen::generate_simple_self_signed(["localhost".to_string()]).unwrap();
        let key_path = directory.join("key.pem");
        let cert_path = directory.join("cert.pem");
        std::fs::write(
            &key_path,
            transform_key(certified.signing_key.serialize_pem()),
        )
        .unwrap();
        std::fs::write(&cert_path, certified.cert.pem()).unwrap();
        ServerSslConfig {
            key: Some(key_path),
            key_password: password.map(str::to_string),
            cert: Some(cert_path),
            version: None,
            ca_certs: None,
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
    fn plain_keys_load() {
        let directory = tempfile::tempdir().unwrap();
        let config = ssl(directory.path(), None, |key| key);
        assert!(server_config(&config).unwrap().is_some());
    }

    #[test]
    fn encrypted_keys_decrypt_with_the_configured_password() {
        let directory = tempfile::tempdir().unwrap();
        let config = ssl(directory.path(), Some("hunter2"), |key| {
            encrypt_key(key, "hunter2")
        });
        assert!(server_config(&config).unwrap().is_some());

        let config = ssl(directory.path(), None, |key| encrypt_key(key, "hunter2"));
        assert!(matches!(server_config(&config), Err(Error::Decrypt(_))));
    }

    #[test]
    fn missing_halves_are_refused() {
        let directory = tempfile::tempdir().unwrap();
        let mut config = ssl(directory.path(), None, |key| key);
        config.cert = None;
        assert!(matches!(server_config(&config), Err(Error::Incomplete)));

        let empty = ServerSslConfig {
            key: None,
            key_password: None,
            cert: None,
            version: None,
            ca_certs: None,
        };
        assert!(server_config(&empty).unwrap().is_none());
    }

    /// A fixed seed for the key-encryption test, randomness has no bearing on it.
    fn rand_seed() -> impl rand_core::CryptoRngCore {
        use rand_core::SeedableRng;
        rand_chacha::ChaCha20Rng::from_seed([7; 32])
    }
}
