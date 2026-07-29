//! The logging configuration section.

use schemars::{JsonSchema, Schema, SchemaGenerator, json_schema};
use serde::ser::SerializeStruct;
use serde::{Deserialize, Serialize, Serializer};

use crate::error::Problems;

/// Severity levels used throughout Ceres for events, alerts, and logs.
///
/// Levels are ordered from least to most severe. The serialized values match the lowercase
/// names of Python's standard `logging` module levels.
#[derive(
    Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, JsonSchema,
)]
#[serde(rename_all = "lowercase")]
pub enum Level {
    Debug,
    Info,
    Warning,
    Error,
    Critical,
}

impl Level {
    /// Parse a level from its lowercase serialized name.
    pub fn parse(text: &str) -> Result<Self, String> {
        match text {
            "debug" => Ok(Self::Debug),
            "info" => Ok(Self::Info),
            "warning" => Ok(Self::Warning),
            "error" => Ok(Self::Error),
            "critical" => Ok(Self::Critical),
            _ => Err(format!("invalid level {text:?}")),
        }
    }

    /// The level's lowercase serialized name.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Debug => "debug",
            Self::Info => "info",
            Self::Warning => "warning",
            Self::Error => "error",
            Self::Critical => "critical",
        }
    }
}

/// A record-type logging switch, either on or off, or on at a specific minimum level.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum LogToggle {
    Enabled(bool),
    Level(Level),
}

impl LogToggle {
    /// Return the minimum level to log at, `None` when the switch is off.
    ///
    /// A plain `true` logs at the given default level.
    pub fn level(&self, default: Level) -> Option<Level> {
        match self {
            Self::Enabled(false) => None,
            Self::Enabled(true) => Some(default),
            Self::Level(level) => Some(*level),
        }
    }
}

impl JsonSchema for LogToggle {
    fn schema_name() -> std::borrow::Cow<'static, str> {
        "LogToggle".into()
    }

    fn json_schema(generator: &mut SchemaGenerator) -> Schema {
        let level = generator.subschema_for::<Level>();
        json_schema!({
            "anyOf": [{ "type": "boolean" }, level],
        })
    }
}

/// Per-component or per-engine logging configuration.
///
/// `output` and `store` set minimum levels for the streamed and persisted log streams, and
/// the toggle fields enable optional logging of specific record types.
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
#[schemars(title = "LoggingConfig")]
pub struct RawLoggingConfig {
    /// Minimum severity that reaches the engine's streamed log output.
    pub output: Option<Level>,

    /// Minimum severity persisted to the engine's log store.
    pub store: Option<Level>,

    /// Whether to log events, or the minimum severity to log them at.
    pub events: Option<LogToggle>,

    /// Whether to log raw connection messages, or the minimum severity to log them at.
    pub messages: Option<LogToggle>,

    /// Whether to log parsed particles, or the minimum severity to log them at.
    pub particles: Option<LogToggle>,

    /// Whether to log alerts, or the minimum severity to log them at.
    pub alerts: Option<LogToggle>,
}

/// Validated logging configuration.
///
/// Fields stay `None` when the configuration did not set them, because per-component logging
/// resolves by overlaying each node's explicitly-set fields onto its container's. The
/// accessors resolve defaults, and serialization emits resolved values.
#[derive(Debug, Clone, Default, Deserialize)]
pub struct LoggingConfig {
    pub output: Option<Level>,
    pub store: Option<Level>,
    pub events: Option<LogToggle>,
    pub messages: Option<LogToggle>,
    pub particles: Option<LogToggle>,
    pub alerts: Option<LogToggle>,
}

impl LoggingConfig {
    /// Minimum severity that reaches the engine's streamed log output.
    pub fn output(&self) -> Level {
        self.output.unwrap_or(Level::Info)
    }

    /// Minimum severity persisted to the engine's log store.
    pub fn store(&self) -> Level {
        self.store.unwrap_or(Level::Debug)
    }

    /// Whether to log events, or the minimum severity to log them at.
    pub fn events(&self) -> LogToggle {
        self.events.unwrap_or(LogToggle::Enabled(true))
    }

    /// Whether to log raw connection messages, or the minimum severity to log them at.
    pub fn messages(&self) -> LogToggle {
        self.messages.unwrap_or(LogToggle::Enabled(false))
    }

    /// Whether to log parsed particles, or the minimum severity to log them at.
    pub fn particles(&self) -> LogToggle {
        self.particles.unwrap_or(LogToggle::Enabled(false))
    }

    /// Whether to log alerts, or the minimum severity to log them at.
    pub fn alerts(&self) -> LogToggle {
        self.alerts.unwrap_or(LogToggle::Enabled(false))
    }

    /// Overlay another configuration's explicitly-set fields onto this one.
    pub fn merged(&self, local: &Self) -> Self {
        Self {
            output: local.output.or(self.output),
            store: local.store.or(self.store),
            events: local.events.or(self.events),
            messages: local.messages.or(self.messages),
            particles: local.particles.or(self.particles),
            alerts: local.alerts.or(self.alerts),
        }
    }
}

impl PartialEq for LoggingConfig {
    /// Compare resolved values, so an unset field equals its default set explicitly.
    fn eq(&self, other: &Self) -> bool {
        self.output() == other.output()
            && self.store() == other.store()
            && self.events() == other.events()
            && self.messages() == other.messages()
            && self.particles() == other.particles()
            && self.alerts() == other.alerts()
    }
}

impl Serialize for LoggingConfig {
    /// Serialize resolved values, matching how the configuration has always dumped.
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut state = serializer.serialize_struct("LoggingConfig", 6)?;
        state.serialize_field("output", &self.output())?;
        state.serialize_field("store", &self.store())?;
        state.serialize_field("events", &self.events())?;
        state.serialize_field("messages", &self.messages())?;
        state.serialize_field("particles", &self.particles())?;
        state.serialize_field("alerts", &self.alerts())?;
        state.end()
    }
}

impl TryFrom<RawLoggingConfig> for LoggingConfig {
    type Error = Problems;

    fn try_from(raw: RawLoggingConfig) -> Result<Self, Problems> {
        Ok(Self {
            output: raw.output,
            store: raw.store,
            events: raw.events,
            messages: raw.messages,
            particles: raw.particles,
            alerts: raw.alerts,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn levels_order_by_severity() {
        assert!(Level::Debug < Level::Info);
        assert!(Level::Warning >= Level::Info);
        assert!(Level::Critical > Level::Error);
    }

    #[test]
    fn logging_sections_parse_levels_and_toggles() {
        let raw: RawLoggingConfig =
            serde_yaml_ng::from_str("output: debug\nevents: true\nmessages: warning\n").unwrap();
        let config = LoggingConfig::try_from(raw).unwrap();

        assert_eq!(config.output(), Level::Debug);
        assert_eq!(config.store(), Level::Debug);
        assert_eq!(config.events(), LogToggle::Enabled(true));
        assert_eq!(config.messages(), LogToggle::Level(Level::Warning));
        assert_eq!(config.messages().level(Level::Info), Some(Level::Warning));
    }

    #[test]
    fn merging_overlays_only_explicitly_set_fields() {
        let inherited = LoggingConfig {
            output: Some(Level::Warning),
            events: Some(LogToggle::Enabled(false)),
            ..LoggingConfig::default()
        };
        let local = LoggingConfig {
            store: Some(Level::Error),
            ..LoggingConfig::default()
        };

        let merged = inherited.merged(&local);
        assert_eq!(merged.output(), Level::Warning);
        assert_eq!(merged.store(), Level::Error);
        assert_eq!(merged.events(), LogToggle::Enabled(false));
    }

    #[test]
    fn equality_compares_resolved_values() {
        let unset = LoggingConfig::default();
        let explicit = LoggingConfig {
            output: Some(Level::Info),
            ..LoggingConfig::default()
        };

        assert_eq!(unset, explicit);
    }

    #[test]
    fn serialization_emits_resolved_values() {
        let config = LoggingConfig::default();
        let serialized = serde_json::to_string(&config).unwrap();
        assert!(serialized.contains("\"output\":\"info\""));
        assert!(serialized.contains("\"events\":true"));
    }
}
