//! HTTP client for a running engine's CLI server.
//!
//! The engine writes a per-project server info file holding the ephemeral port and the token
//! the CLI authenticates with. Requests target `http://localhost:<port>/api/`.

use std::time::Duration;

use crate::error::{Result, fail, failure};
use crate::project::{Project, ServerInfo};

/// Client for the CLI server of the engine running this project.
pub struct Client {
    info: ServerInfo,
}

impl Client {
    /// Create a client from the project's server info file.
    ///
    /// Fails when the file is missing or unreadable, which means no engine is running.
    pub fn connect(project: &Project) -> Result<Self> {
        match project.server_info() {
            Some(info) => Ok(Self { info }),
            None => Err(failure!(
                "Server does not appear to be running. '{}' doesn't exist or isn't readable.",
                project.server_info_path().display()
            )),
        }
    }

    /// Create a client only when the server info file exists and the server responds.
    pub fn connect_alive(project: &Project) -> Option<Self> {
        let client = Self::connect(project).ok()?;
        if client.alive() { Some(client) } else { None }
    }

    /// Check whether the server is reachable and responding.
    pub fn alive(&self) -> bool {
        let agent = agent(Some(Duration::from_secs(2)));
        match agent
            .get(self.url("alive", &[]))
            .header("Authorization", &self.info.token)
            .call()
        {
            Ok(response) => response.status().as_u16() < 502,
            Err(_) => false,
        }
    }

    /// Send a GET request and return the response body.
    pub fn get(&self, path: &str, query: &[(&str, &str)]) -> Result<String> {
        let request = agent(None)
            .get(self.url(path, query))
            .header("Authorization", &self.info.token);

        Self::body(request.call())
    }

    /// Send a POST request with an optional JSON body and return the response body.
    pub fn post(
        &self,
        path: &str,
        query: &[(&str, &str)],
        body: Option<&serde_json::Value>,
    ) -> Result<String> {
        let request = agent(None)
            .post(self.url(path, query))
            .header("Authorization", &self.info.token);

        match body {
            Some(body) => Self::body(request.send_json(body)),
            None => Self::body(request.send_empty()),
        }
    }

    /// Build a full request URL from a path and query parameters.
    fn url(&self, path: &str, query: &[(&str, &str)]) -> String {
        let mut url = format!("http://localhost:{}/api/{path}", self.info.port);

        for (index, (name, value)) in query.iter().enumerate() {
            let separator = if index == 0 { '?' } else { '&' };
            url.push(separator);
            url.push_str(name);
            url.push('=');
            url.push_str(&encode(value));
        }

        url
    }

    /// Extract the response body, converting error statuses into CLI failures.
    fn body(
        response: std::result::Result<ureq::http::Response<ureq::Body>, ureq::Error>,
    ) -> Result<String> {
        let mut response =
            response.map_err(|error| failure!("Failed to connect to the CLI server. {error}"))?;

        let status = response.status().as_u16();
        let body = response
            .body_mut()
            .read_to_string()
            .map_err(|error| failure!("Failed to read response. {error}"))?;

        if status >= 400 {
            if body.is_empty() {
                fail!("Request failed with status {status}.");
            }

            fail!("{body}");
        }

        Ok(body)
    }
}

/// Build an HTTP agent, optionally with a global timeout.
fn agent(timeout: Option<Duration>) -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(timeout)
        .http_status_as_error(false)
        .build()
        .into()
}

/// Percent-encode a query parameter value.
fn encode(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                encoded.push(byte as char);
            }
            _ => encoded.push_str(&format!("%{byte:02X}")),
        }
    }

    encoded
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_values_are_percent_encoded() {
        assert_eq!(encode("@sensor:all|~"), "%40sensor%3Aall%7C~");
        assert_eq!(encode("plain-value_1.0~"), "plain-value_1.0~");
    }
}
