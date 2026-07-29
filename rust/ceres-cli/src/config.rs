//! Minimal project configuration parsing.
//!
//! The CLI only needs the engine-level settings it acts on directly, the HTTP server address
//! and the service options. Everything else in the configuration is ignored here and left to
//! the engine, which owns the full schema.

use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::error::{Result, failure};

/// Engine-level configuration without the component tree.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct ConfigMeta {
    pub service: ServiceConfig,
    pub server: ServerConfig,
}

/// Configuration for the engine's HTTP server.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct ServerConfig {
    pub host: String,
    pub port: Option<u16>,
    pub ssl: Option<serde_yaml_ng::Value>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: "0.0.0.0".to_string(),
            port: None,
            ssl: None,
        }
    }
}

/// Process-level options applied when running the engine as a system service.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(default)]
pub struct ServiceConfig {
    pub name: Option<String>,
    pub user: Option<String>,
    pub stdout: Option<PathBuf>,
    pub stderr: Option<PathBuf>,
}

impl ConfigMeta {
    /// Read and parse the configuration file at `path`.
    ///
    /// YAML is a superset of JSON, so a single parser covers every supported extension. An
    /// empty file parses as an empty configuration.
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path).map_err(|_| {
            failure!(
                "Failed to load configuration. Failed to read file at '{}'.",
                path.display()
            )
        })?;

        if content.trim().is_empty() {
            return Ok(Self::default());
        }

        serde_yaml_ng::from_str(&content)
            .map_err(|error| failure!("Failed to load configuration. {error}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_fields_and_missing_sections_parse() {
        let meta: ConfigMeta =
            serde_yaml_ng::from_str("components:\n  sensor:\n    type: Sensor\n").unwrap();
        assert_eq!(meta.server.host, "0.0.0.0");
        assert_eq!(meta.server.port, None);
        assert!(meta.service.name.is_none());
    }

    #[test]
    fn server_and_service_fields_parse() {
        let meta: ConfigMeta = serde_yaml_ng::from_str(
            "server:\n  host: 127.0.0.1\n  port: 8080\nservice:\n  name: my-service\n",
        )
        .unwrap();
        assert_eq!(meta.server.host, "127.0.0.1");
        assert_eq!(meta.server.port, Some(8080));
        assert_eq!(meta.service.name.as_deref(), Some("my-service"));
    }
}
