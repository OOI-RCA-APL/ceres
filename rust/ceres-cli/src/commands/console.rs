//! Commands for interacting with a project's web console.

use std::net::IpAddr;
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
    let Some((scheme, port)) = meta.server.console_listener() else {
        fail!(
            "Server is not configured. Add a `server.https` or `server.http` listener to \
             `ceres.yaml`."
        );
    };

    // Validation guarantees the bind address parses, and a wildcard is reachable locally.
    let host = match meta.server.bind.parse::<IpAddr>() {
        Ok(address) if address.is_unspecified() => "localhost".to_string(),
        Ok(IpAddr::V6(address)) => format!("[{address}]"),
        _ => meta.server.bind.clone(),
    };

    Ok(format!("{scheme}://{host}:{port}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn urls_resolve_host_and_scheme() {
        let meta = ConfigMeta::parse("server:\n  http:\n    port: 8080\n").unwrap();
        assert_eq!(console_url(&meta).unwrap(), "http://localhost:8080");

        let meta = ConfigMeta::parse(
            "server:\n  bind: 10.0.0.5\n  https:\n    port: 8443\n  http:\n    redirect: true\n",
        )
        .unwrap();
        assert_eq!(console_url(&meta).unwrap(), "https://10.0.0.5:8443");

        let meta = ConfigMeta::parse("server:\n  bind: '::1'\n  http: {}\n").unwrap();
        assert_eq!(console_url(&meta).unwrap(), "http://[::1]:80");
        let meta = ConfigMeta::parse("server:\n  bind: '::'\n  http: {}\n").unwrap();
        assert_eq!(console_url(&meta).unwrap(), "http://localhost:80");
    }

    #[test]
    fn a_missing_port_explains_itself() {
        let meta = ConfigMeta::default();
        let error = console_url(&meta).unwrap_err();
        assert!(error.message.unwrap().contains("Server is not configured"));
    }
}
