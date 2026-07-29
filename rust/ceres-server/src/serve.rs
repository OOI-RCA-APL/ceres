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

    /// Terminate TLS with the `ssl` section's certificate material.
    pub fn with_tls(mut self, ssl: &ceres_config::ServerSslConfig) -> Result<Self, Error> {
        self.tls = tls::server_config(ssl)?;
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
                axum_server::from_tcp_rustls(self.listener, RustlsConfig::from_config(config))?
                    .handle(self.handle)
                    .serve(service)
                    .await?;
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
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    use super::*;
    use crate::{AppConfig, build_router};

    #[tokio::test]
    async fn servers_bind_ephemerally_and_stop_gracefully() {
        let server = BoundServer::bind("127.0.0.1", 0).unwrap();
        let port = server.port();
        assert_ne!(port, 0);

        let stopper = server.stopper();
        let app = build_router(AppConfig {
            console: None,
            cli_token: None,
        });
        let serving = tokio::spawn(server.serve(app));

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
}
