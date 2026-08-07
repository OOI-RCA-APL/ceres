//! Project discovery and derived paths.
//!
//! A project is identified by its configuration file. The directory hash and the CLI server
//! info path must match the scheme a running engine uses when it writes the server info file.

use std::path::{Path, PathBuf};

use ceres_config::ConfigMeta;
use serde::Deserialize;
use sha1::{Digest, Sha1};

use crate::error::{Result, failure};

/// Configuration file names searched in the working directory, in priority order.
pub const CONFIG_NAMES: [&str; 3] = ["ceres.yaml", "ceres.yml", "ceres.json"];

/// Connection details written by a running engine for its CLI server.
#[derive(Debug, Clone, Deserialize)]
pub struct ServerInfo {
    pub port: u16,
    pub token: String,
}

/// A Ceres project rooted at a resolved configuration file path.
#[derive(Debug, Clone)]
pub struct Project {
    config_path: PathBuf,
}

impl Project {
    /// Locate the project configuration and return the project.
    ///
    /// Use the explicit path when given, otherwise search the working directory for the
    /// well-known configuration file names.
    pub fn discover(explicit: Option<&Path>) -> Result<Self> {
        let path = match explicit {
            Some(path) => path.to_path_buf(),
            None => CONFIG_NAMES
                .iter()
                .map(PathBuf::from)
                .find(|path| path.is_file())
                .ok_or_else(|| {
                    failure!("Must be in a directory containing one of: {CONFIG_NAMES:?}")
                })?,
        };

        let config_path = path.canonicalize().map_err(|_| {
            failure!("Failed to load configuration. Configuration file {path:?} does not exist.")
        })?;

        Ok(Self { config_path })
    }

    pub fn config_path(&self) -> &Path {
        &self.config_path
    }

    /// Return a handle to the project whose configuration is at this exact path.
    ///
    /// The path is taken as given, with none of [`Self::discover`]'s searching or
    /// canonicalization.
    #[cfg(test)]
    pub fn at(config_path: impl Into<PathBuf>) -> Self {
        Self {
            config_path: config_path.into(),
        }
    }

    /// The directory containing the configuration file.
    pub fn directory(&self) -> &Path {
        self.config_path
            .parent()
            .expect("a canonical file path has a parent")
    }

    /// A short hash of the project directory, used to name per-project temporary files.
    ///
    /// The first six hex characters of the SHA-1 of the directory path string, the same
    /// scheme the engine uses.
    pub fn directory_hash(&self) -> String {
        let mut hasher = Sha1::new();
        hasher.update(self.directory().to_string_lossy().as_bytes());
        let digest = hasher.finalize();

        let mut hash = String::with_capacity(6);
        for byte in digest.iter().take(3) {
            hash.push_str(&format!("{byte:02x}"));
        }

        hash
    }

    /// The path of the CLI server info file a running engine writes for this project.
    pub fn server_info_path(&self) -> PathBuf {
        temporary_directory().join(format!("ceres-{}.server.json", self.directory_hash()))
    }

    /// Read and parse the CLI server info file, returning `None` on any failure.
    pub fn server_info(&self) -> Option<ServerInfo> {
        let content = std::fs::read_to_string(self.server_info_path()).ok()?;
        serde_json::from_str(&content).ok()
    }

    /// Load and validate the engine-level project configuration.
    pub fn load_meta(&self) -> Result<ConfigMeta> {
        ConfigMeta::load(&self.config_path)
            .map_err(|problems| failure!("Failed to load configuration.\n{problems}"))
    }
}

/// Return the platform temporary directory, preferring `/tmp` on Unix.
fn temporary_directory() -> PathBuf {
    if cfg!(unix) && Path::new("/tmp").is_dir() {
        return PathBuf::from("/tmp");
    }

    std::env::temp_dir()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn directory_hashes_use_truncated_sha1() {
        // The first six hex characters of sha1("/opt/project").
        let project = Project::at("/opt/project/ceres.yaml");
        assert_eq!(project.directory_hash(), "8d1253");
    }

    #[test]
    fn discovery_fails_outside_a_project() {
        let directory = tempfile::tempdir().unwrap();
        let _guard = std::env::set_current_dir(directory.path());
        let error = Project::discover(None).unwrap_err();
        assert!(error.message.unwrap().contains("ceres.yaml"));
    }
}
