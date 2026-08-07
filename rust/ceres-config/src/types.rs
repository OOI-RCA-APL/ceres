//! Validated configuration sections.
//!
//! Each section comes in two forms. The raw form derives `Deserialize` and `JsonSchema` and
//! carries no guarantees beyond shape. The validated form is only constructed through
//! validation, so holding one is proof the section is well formed. Validation collects every
//! problem it finds rather than stopping at the first.

use std::path::PathBuf;
use std::sync::LazyLock;

use regex_lite::Regex;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};

/// The pattern every name-like configuration value must match.
pub const NAME_PATTERN: &str = r"[a-zA-Z_\-][a-zA-Z0-9_\-]*";

static NAME_REGEX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(&format!("^{NAME_PATTERN}$")).expect("the pattern compiles"));

/// A validated name, letters, digits, underscores, and dashes, not starting with a digit.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct Name(String);

impl Name {
    /// Validate a name's textual form.
    pub fn parse(text: &str) -> Result<Self, Problem> {
        if !NAME_REGEX.is_match(text) {
            return Err(Problem::new(
                "",
                format!("{text:?} must match pattern '^{NAME_PATTERN}$'."),
            ));
        }

        Ok(Self(text.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for Name {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}", self.0)
    }
}

/// Validate an optional name field, pushing any problem under the field's name.
fn validate_name(value: Option<String>, field: &str, problems: &mut Problems) -> Option<Name> {
    let text = value?;
    match Name::parse(&text) {
        Ok(name) => Some(name),
        Err(problem) => {
            problems.push(problem.under(field));
            None
        }
    }
}

/// Process-level options applied when running the engine as a system service.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ServiceConfig")]
pub struct RawServiceConfig {
    /// Service name registered with the operating system.
    pub name: Option<String>,

    /// User the service runs as.
    pub user: Option<String>,

    /// Optional path to redirect standard output to.
    pub stdout: Option<PathBuf>,

    /// Optional path to redirect standard error to.
    pub stderr: Option<PathBuf>,
}

/// Validated process-level options for running the engine as a system service.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ServiceConfig {
    pub name: Option<Name>,
    pub user: Option<Name>,
    pub stdout: Option<PathBuf>,
    pub stderr: Option<PathBuf>,
}

impl TryFrom<RawServiceConfig> for ServiceConfig {
    type Error = Problems;

    fn try_from(raw: RawServiceConfig) -> Result<Self, Problems> {
        let mut problems = Problems::default();
        let name = validate_name(raw.name, "name", &mut problems);
        let user = validate_name(raw.user, "user", &mut problems);

        problems.into_result(Self {
            name,
            user,
            stdout: raw.stdout,
            stderr: raw.stderr,
        })
    }
}

/// Branding and layout options for the engine's web console.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "ConsoleConfig")]
pub struct RawConsoleConfig {
    /// Title shown in the console's browser tab and header.
    pub title: Option<String>,

    /// Path to a favicon image served by the console.
    pub favicon: Option<PathBuf>,
}

/// Validated branding and layout options for the engine's web console.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ConsoleConfig {
    pub title: Option<String>,
    pub favicon: Option<PathBuf>,
}

impl TryFrom<RawConsoleConfig> for ConsoleConfig {
    type Error = Problems;

    fn try_from(raw: RawConsoleConfig) -> Result<Self, Problems> {
        Ok(Self {
            title: raw.title,
            favicon: raw.favicon,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_service_sections_validate() {
        let raw = RawServiceConfig {
            name: Some("my-service".to_string()),
            user: None,
            stdout: Some(PathBuf::from("logs/out.log")),
            stderr: None,
        };

        let config = ServiceConfig::try_from(raw).unwrap();
        assert_eq!(config.name.unwrap().as_str(), "my-service");
        assert_eq!(config.stdout.unwrap(), PathBuf::from("logs/out.log"));
    }

    #[test]
    fn bad_names_report_their_location() {
        let raw = RawServiceConfig {
            name: Some("9lives".to_string()),
            user: Some("bad user".to_string()),
            ..RawServiceConfig::default()
        };

        let problems = ServiceConfig::try_from(raw).unwrap_err();
        let locations: Vec<&str> = problems
            .0
            .iter()
            .map(|problem| problem.location.as_str())
            .collect();
        assert_eq!(locations, ["name", "user"]);
    }

    #[test]
    fn unknown_service_fields_are_rejected() {
        let error = yaml_serde::from_str::<RawServiceConfig>("names: typo\n").unwrap_err();
        assert!(error.to_string().contains("names"));
    }
}
