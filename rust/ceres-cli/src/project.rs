//! Project discovery and derived paths.
//!
//! A project is identified by its configuration file. The `.ceres` state directory and the
//! CLI server info path in it must match where a running engine writes the server info file.

use std::path::{Path, PathBuf};

use ceres_config::ConfigMeta;
use serde::Deserialize;
use sha1::{Digest, Sha1};

use crate::error::{Result, failure};

/// Name of the directory in a project that holds what Ceres writes for itself.
pub const STATE_DIRECTORY: &str = ".ceres";

/// Configuration file names searched in the working directory, in priority order.
pub const CONFIG_NAMES: [&str; 3] = ["ceres.yaml", "ceres.yml", "ceres.json"];

/// Load `.env` from the project directory into the process environment.
///
/// The directory is the explicit configuration file's, or the working directory. Variables
/// already set stay as they are, so the real environment always wins over the file, and
/// every child process inherits the result.
pub fn load_env(config: Option<&Path>) {
    let directory = match config.and_then(Path::parent) {
        Some(parent) if parent.as_os_str().is_empty() => PathBuf::from("."),
        Some(parent) => parent.to_path_buf(),
        None => PathBuf::from("."),
    };

    let path = directory.join(".env");
    if !path.is_file() {
        return;
    }

    if let Err(error) = dotenvy::from_path(&path) {
        eprintln!("Warning: failed to load {}. {error}", path.display());
    }
}

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

    /// A short hash of the project directory, used to name the project's service.
    ///
    /// The first six hex characters of the SHA-1 of the directory path string.
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

    /// The `.ceres` directory beside the configuration, holding what Ceres writes for itself.
    pub fn state_directory(&self) -> PathBuf {
        self.directory().join(STATE_DIRECTORY)
    }

    /// Create the `.ceres` directory if needed, returning its path.
    ///
    /// It ignores itself through its own `.gitignore`, so nothing in it reaches version
    /// control whatever the project's own ignore rules say. A `.gitignore` already there
    /// is left as it is. The engine creates the directory the same way.
    pub fn create_state_directory(&self) -> Result<PathBuf> {
        let directory = self.state_directory();
        std::fs::create_dir_all(&directory)
            .map_err(|error| failure!("Failed to create {}. {error}", directory.display()))?;

        let ignore = directory.join(".gitignore");
        if !ignore.exists() {
            std::fs::write(&ignore, "*\n")
                .map_err(|error| failure!("Failed to write {}. {error}", ignore.display()))?;
        }

        Ok(directory)
    }

    /// The path of the CLI server info file a running engine writes for this project.
    pub fn server_info_path(&self) -> PathBuf {
        self.state_directory().join("server.json")
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
    fn server_info_lives_in_the_state_directory() {
        let project = Project::at("/opt/project/ceres.yaml");
        assert_eq!(
            project.server_info_path(),
            Path::new("/opt/project/.ceres/server.json")
        );
    }

    #[test]
    fn the_state_directory_ignores_itself() {
        let directory = tempfile::tempdir().unwrap();
        let project = Project::at(directory.path().join("ceres.yaml"));

        let created = project.create_state_directory().unwrap();
        assert_eq!(created, directory.path().join(".ceres"));
        let ignore = created.join(".gitignore");
        assert_eq!(std::fs::read_to_string(&ignore).unwrap(), "*\n");

        // A `.gitignore` the user edited is left alone.
        std::fs::write(&ignore, "*\n!keep\n").unwrap();
        project.create_state_directory().unwrap();
        assert_eq!(std::fs::read_to_string(&ignore).unwrap(), "*\n!keep\n");
    }

    #[test]
    fn discovery_fails_outside_a_project() {
        let directory = tempfile::tempdir().unwrap();
        let _guard = std::env::set_current_dir(directory.path());
        let error = Project::discover(None).unwrap_err();
        assert!(error.message.unwrap().contains("ceres.yaml"));
    }
}
