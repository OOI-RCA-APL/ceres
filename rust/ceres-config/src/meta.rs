//! Engine-level configuration loading.

use std::path::Path;

use serde::Deserialize;

use crate::error::{Problem, Problems};
use crate::types::{ConsoleConfig, RawConsoleConfig, RawServiceConfig, ServiceConfig};

/// Configuration for the engine's HTTP server.
///
/// Parsed leniently until the section's validation is ported. Consumers validate the fields
/// they read.
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

/// The engine-level sections of a project configuration.
///
/// Unknown top-level keys, including the component tree, pass through without complaint. The
/// component schema is defined by user code and validated where components are loaded.
#[derive(Debug, Clone, Default)]
pub struct ConfigMeta {
    pub service: ServiceConfig,
    pub console: ConsoleConfig,
    pub server: ServerConfig,
}

/// The raw deserialized form of [`ConfigMeta`].
#[derive(Debug, Default, Deserialize)]
#[serde(default)]
struct RawConfigMeta {
    service: Option<serde_yaml_ng::Value>,
    console: Option<serde_yaml_ng::Value>,
    server: ServerConfig,
}

impl ConfigMeta {
    /// Read, parse, and validate the configuration file at `path`.
    ///
    /// YAML is a superset of JSON, so a single parser covers every supported extension. An
    /// empty file parses as an empty configuration.
    pub fn load(path: &Path) -> Result<Self, Problems> {
        let content = std::fs::read_to_string(path).map_err(|_| {
            Problems(vec![Problem::new(
                "",
                format!("Failed to read file at '{}'.", path.display()),
            )])
        })?;

        Self::parse(&content)
    }

    /// Parse and validate configuration text.
    pub fn parse(content: &str) -> Result<Self, Problems> {
        if content.trim().is_empty() {
            return Ok(Self::default());
        }

        let raw: RawConfigMeta = serde_yaml_ng::from_str(content)
            .map_err(|error| Problems(vec![Problem::new("", error.to_string())]))?;

        let mut problems = Problems::default();
        let service = validate_section::<RawServiceConfig, ServiceConfig>(
            raw.service,
            "service",
            &mut problems,
        );
        let console = validate_section::<RawConsoleConfig, ConsoleConfig>(
            raw.console,
            "console",
            &mut problems,
        );

        problems.into_result(Self {
            service,
            console,
            server: raw.server,
        })
    }
}

/// Deserialize and validate one configuration section, collecting its problems.
///
/// Returns the section's default when the section is absent or invalid, with any problems
/// recorded under the section's name.
fn validate_section<Raw, Validated>(
    value: Option<serde_yaml_ng::Value>,
    section: &str,
    problems: &mut Problems,
) -> Validated
where
    Raw: for<'a> Deserialize<'a>,
    Validated: TryFrom<Raw, Error = Problems> + Default,
{
    let Some(value) = value else {
        return Validated::default();
    };

    let raw: Raw = match serde_yaml_ng::from_value(value) {
        Ok(raw) => raw,
        Err(error) => {
            problems.push(Problem::new(section, error.to_string()));
            return Validated::default();
        }
    };

    match Validated::try_from(raw) {
        Ok(validated) => validated,
        Err(section_problems) => {
            problems.absorb(section_problems, section);
            Validated::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_configurations_parse_and_validate() {
        let meta = ConfigMeta::parse(
            "service:\n  name: probe\nconsole:\n  title: Probe\nserver:\n  port: 8080\n\
             components:\n  sensor:\n    type: Sensor\n",
        )
        .unwrap();

        assert_eq!(meta.service.name.unwrap().as_str(), "probe");
        assert_eq!(meta.console.title.as_deref(), Some("Probe"));
        assert_eq!(meta.server.port, Some(8080));
    }

    #[test]
    fn empty_configurations_parse_as_defaults() {
        let meta = ConfigMeta::parse("").unwrap();
        assert!(meta.service.name.is_none());
        assert_eq!(meta.server.host, "0.0.0.0");
    }

    #[test]
    fn section_problems_carry_full_locations() {
        let problems = ConfigMeta::parse("service:\n  name: 9lives\n").unwrap_err();
        assert_eq!(problems.0.len(), 1);
        assert_eq!(problems.0[0].location, "service.name");
    }

    #[test]
    fn unknown_section_keys_are_located() {
        let problems = ConfigMeta::parse("console:\n  fav: icon.png\n").unwrap_err();
        assert_eq!(problems.0[0].location, "console");
        assert!(problems.0[0].message.contains("fav"));
    }
}
