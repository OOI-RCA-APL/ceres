//! Commands for interacting with a project's web console.

use std::process::Command;

use ceres_config::ConfigMeta;

use crate::error::{Result, fail, failure};
use crate::output::Output;
use crate::project::Project;

/// Write the project's web console URL to stdout.
pub fn url(project: &Project, output: &Output) -> Result<()> {
    let meta = project.load_meta()?;
    output.put(console_url(&meta)?);
    Ok(())
}

/// Open the project's web console in a browser.
pub fn open(project: &Project) -> Result<()> {
    let meta = project.load_meta()?;
    let url = console_url(&meta)?;

    let program = if cfg!(target_os = "macos") {
        "open"
    } else {
        "xdg-open"
    };

    Command::new(program)
        .arg(&url)
        .status()
        .map_err(|error| failure!("Failed to open {url}. {error}"))?;

    Ok(())
}

/// Build the web console URL from the project's server configuration.
fn console_url(meta: &ConfigMeta) -> Result<String> {
    let Some(port) = meta.server.port else {
        fail!(
            "Server is not configured. Add `server` settings to `ceres.yaml` with a defined \
             `port` number."
        );
    };

    let host = if meta.server.host == "0.0.0.0" {
        "localhost"
    } else {
        &meta.server.host
    };

    let scheme = if meta.server.ssl.is_none() {
        "http"
    } else {
        "https"
    };

    Ok(format!("{scheme}://{host}:{port}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urls_resolve_host_and_scheme() {
        let meta = ConfigMeta::parse("server:\n  port: 8080\n").unwrap();
        assert_eq!(console_url(&meta).unwrap(), "http://localhost:8080");

        let meta =
            ConfigMeta::parse("server:\n  host: 10.0.0.5\n  port: 443\n  ssl:\n    cert: c\n")
                .unwrap();
        assert_eq!(console_url(&meta).unwrap(), "https://10.0.0.5:443");
    }

    #[test]
    fn a_missing_port_explains_itself() {
        let meta = ConfigMeta::default();
        let error = console_url(&meta).unwrap_err();
        assert!(error.message.unwrap().contains("Server is not configured"));
    }
}
