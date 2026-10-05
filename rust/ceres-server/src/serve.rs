//! Binding and serving.
//!
//! A server binds eagerly so its real port is known before anything serves, which is how
//! the control server reports the ephemeral port it was given, then serves an axum
//! router until stopped. Shutdown is graceful, in-flight requests finish first.

use std::net::{SocketAddr, TcpListener};
use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use axum_server::Handle;
use axum_server::tls_rustls::RustlsConfig;

use crate::tls;

/// A server bound to its address, ready to serve.
pub struct BoundServer {
    listener: TcpListener,
    handle: Handle<SocketAddr>,
    tls: Option<Arc<rustls::ServerConfig>>,
}

/// A serving failure.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("cannot bind {address}. {source}")]
    Bind {
        address: String,
        source: std::io::Error,
    },
    #[error(transparent)]
    Tls(#[from] tls::Error),
    #[error(transparent)]
    Serve(#[from] std::io::Error),
}

impl BoundServer {
    /// Bind to an address, port zero selecting an ephemeral port.
    pub fn bind(host: &str, port: u16) -> Result<Self, Error> {
        let address = format!("{host}:{port}");
        let listener = TcpListener::bind(&address).map_err(|source| Error::Bind {
            address: address.clone(),
            source,
        })?;
        listener
            .set_nonblocking(true)
            .map_err(|source| Error::Bind { address, source })?;

        Ok(Self {
            listener,
            handle: Handle::new(),
            tls: None,
        })
    }

    /// Terminate TLS with the `https` section's certificate material.
    pub fn with_tls(mut self, https: &ceres_config::ServerHttpsConfig) -> Result<Self, Error> {
        self.tls = Some(tls::server_config(https)?);
        Ok(self)
    }

    /// The port actually bound, which differs from the requested one when it was zero.
    pub fn port(&self) -> u16 {
        self.listener
            .local_addr()
            .map(|address| address.port())
            .unwrap_or_default()
    }

    /// A handle that stops the server gracefully from another task.
    pub fn stopper(&self) -> Stopper {
        Stopper {
            handle: self.handle.clone(),
        }
    }

    /// Serve the router until stopped.
    pub async fn serve(self, router: Router) -> Result<(), Error> {
        let service = router.into_make_service();
        match self.tls {
            Some(config) => {
                let mut server =
                    axum_server::from_tcp_rustls(self.listener, RustlsConfig::from_config(config))?
                        .handle(self.handle);
                // Extended CONNECT lets a browser open its WebSockets as streams of the one
                // HTTP/2 connection rather than spending a plain HTTP/1.1 connection each.
                server.http_builder().http2().enable_connect_protocol();
                server.serve(service).await?;
            }
            None => {
                axum_server::from_tcp(self.listener)?
                    .handle(self.handle)
                    .serve(service)
                    .await?;
            }
        }

        Ok(())
    }
}

/// Stops a serving [`BoundServer`] gracefully.
#[derive(Clone)]
pub struct Stopper {
    handle: Handle<SocketAddr>,
}

impl Stopper {
    /// Stop the server, letting in-flight requests finish within the grace period.
    pub fn stop(&self, grace: Duration) {
        self.handle.graceful_shutdown(Some(grace));
    }
}

#[cfg(test)]
mod tests {
    use rustls::pki_types::ServerName;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpStream;

    use super::*;
    use crate::{AppConfig, build_router};

    fn test_router() -> Router {
        build_router(AppConfig {
            console: None,
            cli_token: None,
            auth: None,
            host: Arc::new(crate::host::NoHost),
            version: "0.0.0".to_string(),
        })
    }

    #[tokio::test]
    async fn servers_bind_ephemerally_and_stop_gracefully() {
        let server = BoundServer::bind("127.0.0.1", 0).unwrap();
        let port = server.port();
        assert_ne!(port, 0);

        let stopper = server.stopper();
        let serving = tokio::spawn(server.serve(test_router()));

        let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port))
            .await
            .unwrap();
        stream
            .write_all(b"GET /api/alive HTTP/1.1\r\nhost: localhost\r\nconnection: close\r\n\r\n")
            .await
            .unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).await.unwrap();
        assert!(response.starts_with("HTTP/1.1 200"), "{response}");

        stopper.stop(Duration::from_millis(100));
        serving.await.unwrap().unwrap();
    }

    /// A client trusting only the self-signed certificate `https` names, offering `h2` alone.
    fn h2_client(https: &ceres_config::ServerHttpsConfig) -> tokio_rustls::TlsConnector {
        let mut roots = rustls::RootCertStore::empty();
        let pem = std::fs::read(&https.cert).unwrap();
        for certificate in rustls_pemfile::certs(&mut pem.as_slice()) {
            roots.add(certificate.unwrap()).unwrap();
        }
        let provider = Arc::new(rustls::crypto::ring::default_provider());
        let mut config = rustls::ClientConfig::builder_with_provider(provider)
            .with_safe_default_protocol_versions()
            .unwrap()
            .with_root_certificates(roots)
            .with_no_client_auth();
        config.alpn_protocols = vec![b"h2".to_vec()];
        tokio_rustls::TlsConnector::from(Arc::new(config))
    }

    #[tokio::test]
    async fn tls_servers_multiplex_requests_over_one_h2_connection() {
        let directory = tempfile::tempdir().unwrap();
        let https = crate::tls::tests::https(directory.path(), None, |key| key);
        let server = BoundServer::bind("127.0.0.1", 0)
            .unwrap()
            .with_tls(&https)
            .unwrap();
        let port = server.port();
        let stopper = server.stopper();
        let serving = tokio::spawn(server.serve(test_router()));

        let tcp = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
        let tls = h2_client(&https)
            .connect(ServerName::try_from("localhost").unwrap(), tcp)
            .await
            .unwrap();
        assert_eq!(tls.get_ref().1.alpn_protocol(), Some(&b"h2"[..]));

        let (mut client, connection) = h2::client::handshake(tls).await.unwrap();
        tokio::spawn(connection);
        let mut responses = Vec::new();
        for _ in 0..50 {
            client = client.ready().await.unwrap();
            let request = axum::http::Request::get("https://localhost/api/alive")
                .body(())
                .unwrap();
            responses.push(client.send_request(request, true).unwrap().0);
        }
        for response in responses {
            assert_eq!(response.await.unwrap().status(), 200);
        }
        // The server's settings have arrived by now, WebSockets may join the connection.
        assert!(client.is_extended_connect_protocol_enabled());

        stopper.stop(Duration::from_millis(100));
        serving.await.unwrap().unwrap();
    }
}
