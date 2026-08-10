//! Scalar value types used across configuration sections.
//!
//! These parse the spellings the engine accepts, numbers or ISO 8601 text for
//! durations, plain byte counts or unit-suffixed text for sizes, and scalar-or-list
//! fields that keep whichever shape they were written in.

use std::fmt;
use std::time::Duration;

use schemars::{JsonSchema, Schema, SchemaGenerator, json_schema};
use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// A positive duration, written as seconds or ISO 8601 text.
///
/// Serializes as ISO 8601 in the same normalized form the engine's API uses, for example
/// `PT30M` or `P1DT2H`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimeDelta(Duration);

impl TimeDelta {
    pub const fn from_secs(seconds: u64) -> Self {
        Self(Duration::from_secs(seconds))
    }

    pub const fn from_duration(duration: Duration) -> Self {
        Self(duration)
    }

    pub fn duration(&self) -> Duration {
        self.0
    }

    /// Parse a duration from seconds, ISO 8601, `HH:MM:SS`, or suffixed text.
    pub fn parse(text: &str) -> Result<Self, String> {
        let text = text.trim();
        if let Ok(seconds) = text.parse::<f64>() {
            return Self::from_seconds(seconds);
        }

        if text.starts_with('P') || text.starts_with("-P") {
            return Self::parse_iso8601(text);
        }

        if text.contains(':') {
            return Self::parse_clock(text);
        }

        Self::parse_suffixed(text)
    }

    /// Parse the engine's suffix grammar, a number carrying `us`, `ms`, `s`, `m`,
    /// `h`, or `d`, spaces and case ignored.
    fn parse_suffixed(text: &str) -> Result<Self, String> {
        let error = || format!("invalid duration {text:?}");
        let text = text.replace(' ', "").to_lowercase();
        let (number, scale) = if let Some(number) = text.strip_suffix("us") {
            (number, 1e-6)
        } else if let Some(number) = text.strip_suffix("ms") {
            (number, 1e-3)
        } else if let Some(number) = text.strip_suffix('s') {
            (number, 1.0)
        } else if let Some(number) = text.strip_suffix('m') {
            (number, 60.0)
        } else if let Some(number) = text.strip_suffix('h') {
            (number, 3600.0)
        } else if let Some(number) = text.strip_suffix('d') {
            (number, 86400.0)
        } else {
            return Err(error());
        };

        if number.is_empty() {
            return Err(error());
        }

        let value: f64 = number.parse().map_err(|_| error())?;
        Self::from_seconds(value * scale)
    }

    fn from_seconds(seconds: f64) -> Result<Self, String> {
        if !seconds.is_finite() || seconds < 0.0 {
            return Err("duration must be a positive number of seconds".to_string());
        }

        Ok(Self(Duration::from_secs_f64(seconds)))
    }

    /// Parse the `P{days}DT{hours}H{minutes}M{seconds}S` form.
    fn parse_iso8601(text: &str) -> Result<Self, String> {
        let error = || format!("invalid ISO 8601 duration {text:?}");
        if text.starts_with('-') {
            return Err("duration must be positive".to_string());
        }

        let body = text.strip_prefix('P').ok_or_else(error)?;
        let (date, time) = match body.split_once('T') {
            Some((date, time)) => (date, time),
            None => (body, ""),
        };

        let mut seconds = 0.0;
        let mut parse_components = |section: &str, units: &[(char, f64)]| -> Result<(), String> {
            let mut remaining = section;
            for (unit, scale) in units {
                if let Some((value, rest)) = remaining.split_once(*unit) {
                    seconds += value.parse::<f64>().map_err(|_| error())? * scale;
                    remaining = rest;
                }
            }

            if remaining.is_empty() {
                Ok(())
            } else {
                Err(error())
            }
        };

        parse_components(date, &[('W', 604800.0), ('D', 86400.0)])?;
        parse_components(time, &[('H', 3600.0), ('M', 60.0), ('S', 1.0)])?;
        Self::from_seconds(seconds)
    }

    /// Parse the `[DD days, ]HH:MM:SS[.ffffff]` form.
    fn parse_clock(text: &str) -> Result<Self, String> {
        let error = || format!("invalid duration {text:?}");
        let parts: Vec<&str> = text.split(':').collect();
        let (hours, minutes, seconds) = match parts.as_slice() {
            [hours, minutes, seconds] => (*hours, *minutes, *seconds),
            [minutes, seconds] => ("0", *minutes, *seconds),
            _ => return Err(error()),
        };

        let hours = hours.trim().parse::<f64>().map_err(|_| error())?;
        let minutes = minutes.parse::<f64>().map_err(|_| error())?;
        let seconds = seconds.parse::<f64>().map_err(|_| error())?;
        Self::from_seconds(hours * 3600.0 + minutes * 60.0 + seconds)
    }
}

impl fmt::Display for TimeDelta {
    /// Format as normalized ISO 8601, omitting zero components.
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let total_microseconds = self.0.as_micros();
        if total_microseconds == 0 {
            return write!(formatter, "PT0S");
        }

        let days = total_microseconds / 86_400_000_000;
        let hours = (total_microseconds / 3_600_000_000) % 24;
        let minutes = (total_microseconds / 60_000_000) % 60;
        let seconds = (total_microseconds / 1_000_000) % 60;
        let microseconds = total_microseconds % 1_000_000;

        write!(formatter, "P")?;
        if days > 0 {
            write!(formatter, "{days}D")?;
        }

        if hours > 0 || minutes > 0 || seconds > 0 || microseconds > 0 {
            write!(formatter, "T")?;
            if hours > 0 {
                write!(formatter, "{hours}H")?;
            }
            if minutes > 0 {
                write!(formatter, "{minutes}M")?;
            }
            if microseconds > 0 {
                let fraction = format!("{microseconds:06}");
                let fraction = fraction.trim_end_matches('0');
                write!(formatter, "{seconds}.{fraction}S")?;
            } else if seconds > 0 {
                write!(formatter, "{seconds}S")?;
            }
        }

        Ok(())
    }
}

impl Serialize for TimeDelta {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_string())
    }
}

impl<'de> Deserialize<'de> for TimeDelta {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Input {
            Number(f64),
            Text(String),
        }

        match Input::deserialize(deserializer)? {
            Input::Number(seconds) => Self::from_seconds(seconds).map_err(D::Error::custom),
            Input::Text(text) => Self::parse(&text).map_err(D::Error::custom),
        }
    }
}

impl JsonSchema for TimeDelta {
    fn schema_name() -> std::borrow::Cow<'static, str> {
        "TimeDelta".into()
    }

    fn json_schema(_generator: &mut SchemaGenerator) -> Schema {
        json_schema!({
            "anyOf": [
                { "type": "number", "minimum": 0 },
                { "type": "string", "format": "duration" },
            ],
        })
    }
}

/// A byte count, written as a plain number or unit-suffixed text like `500KB` or `1GiB`.
///
/// Decimal units are powers of 1000 and binary units powers of 1024.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct ByteSize(u64);

impl ByteSize {
    pub const fn new(bytes: u64) -> Self {
        Self(bytes)
    }

    pub fn bytes(&self) -> u64 {
        self.0
    }

    /// Parse a byte count from a number or unit-suffixed text.
    pub fn parse(text: &str) -> Result<Self, String> {
        let text = text.trim();
        let split = text
            .find(|character: char| !character.is_ascii_digit() && character != '.')
            .unwrap_or(text.len());
        let (value, unit) = text.split_at(split);

        let value: f64 = value
            .parse()
            .map_err(|_| format!("invalid byte size {text:?}"))?;
        let scale: u64 = match unit.trim().to_ascii_lowercase().as_str() {
            "" | "b" => 1,
            "kb" => 1000,
            "kib" => 1 << 10,
            "mb" => 1_000_000,
            "mib" => 1 << 20,
            "gb" => 1_000_000_000,
            "gib" => 1 << 30,
            "tb" => 1_000_000_000_000,
            "tib" => 1 << 40,
            "pb" => 1_000_000_000_000_000,
            "pib" => 1 << 50,
            _ => return Err(format!("invalid byte size unit {unit:?}")),
        };

        Ok(Self((value * scale as f64) as u64))
    }
}

impl Serialize for ByteSize {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for ByteSize {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        #[derive(Deserialize)]
        #[serde(untagged)]
        enum Input {
            Number(u64),
            Text(String),
        }

        match Input::deserialize(deserializer)? {
            Input::Number(bytes) => Ok(Self(bytes)),
            Input::Text(text) => Self::parse(&text).map_err(D::Error::custom),
        }
    }
}

impl JsonSchema for ByteSize {
    fn schema_name() -> std::borrow::Cow<'static, str> {
        "ByteSize".into()
    }

    fn json_schema(_generator: &mut SchemaGenerator) -> Schema {
        json_schema!({
            "anyOf": [
                { "type": "integer", "minimum": 0 },
                { "type": "string" },
            ],
        })
    }
}

/// A secret string that never leaves through serialization or debug output.
///
/// Serializes as a fixed mask so a secret can only be read through `expose`.
#[derive(Clone, Default, PartialEq, Eq, Deserialize)]
#[serde(transparent)]
pub struct Secret(String);

impl Secret {
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Return the real secret value.
    pub fn expose(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for Secret {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "Secret(\"**********\")")
    }
}

impl Serialize for Secret {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str("**********")
    }
}

impl JsonSchema for Secret {
    fn schema_name() -> std::borrow::Cow<'static, str> {
        "Secret".into()
    }

    fn json_schema(_generator: &mut SchemaGenerator) -> Schema {
        json_schema!({ "type": "string", "format": "password", "writeOnly": true })
    }
}

/// A value written as either a single item or a list of items, keeping its written shape.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum MaybeSequence<T> {
    One(T),
    Many(Vec<T>),
}

impl<T> MaybeSequence<T> {
    /// View the value as a slice regardless of its written shape.
    pub fn as_slice(&self) -> &[T] {
        match self {
            Self::One(value) => std::slice::from_ref(value),
            Self::Many(values) => values,
        }
    }
}

impl<T> Default for MaybeSequence<T> {
    fn default() -> Self {
        Self::Many(Vec::new())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn durations_parse_from_every_accepted_spelling() {
        assert_eq!(TimeDelta::parse("15").unwrap(), TimeDelta::from_secs(15));
        assert_eq!(
            TimeDelta::parse("15.5").unwrap().duration(),
            Duration::from_millis(15500)
        );
        assert_eq!(
            TimeDelta::parse("PT30M").unwrap(),
            TimeDelta::from_secs(1800)
        );
        assert_eq!(
            TimeDelta::parse("P1DT2H").unwrap(),
            TimeDelta::from_secs(93600)
        );
        assert_eq!(
            TimeDelta::parse("00:00:15").unwrap(),
            TimeDelta::from_secs(15)
        );
        assert!(TimeDelta::parse("-PT30S").is_err());
        assert!(TimeDelta::parse("nonsense").is_err());
    }

    /// The suffix grammar must accept exactly what the engine's Python `_parse_sdelta`
    /// accepts, every unit, floats, exponents, spacing, and case included.
    #[test]
    fn durations_parse_the_suffix_grammar() {
        let seconds = |value: f64| TimeDelta::from_duration(Duration::from_secs_f64(value));
        assert_eq!(TimeDelta::parse("30d").unwrap(), seconds(30.0 * 86400.0));
        assert_eq!(TimeDelta::parse("12h").unwrap(), seconds(12.0 * 3600.0));
        assert_eq!(TimeDelta::parse("30m").unwrap(), seconds(1800.0));
        assert_eq!(TimeDelta::parse("45s").unwrap(), seconds(45.0));
        assert_eq!(TimeDelta::parse("250ms").unwrap(), seconds(0.25));
        assert_eq!(TimeDelta::parse("500us").unwrap(), seconds(0.0005));
        assert_eq!(TimeDelta::parse("1.5h").unwrap(), seconds(5400.0));
        assert_eq!(TimeDelta::parse("0.5d").unwrap(), seconds(43200.0));
        assert_eq!(TimeDelta::parse("1e2s").unwrap(), seconds(100.0));
        assert_eq!(TimeDelta::parse(" 30 d ").unwrap(), seconds(30.0 * 86400.0));
        assert_eq!(TimeDelta::parse("30D").unwrap(), seconds(30.0 * 86400.0));
        assert_eq!(TimeDelta::parse("+5s").unwrap(), seconds(5.0));
        assert_eq!(TimeDelta::parse("0s").unwrap(), TimeDelta::from_secs(0));

        for rejected in ["d", "s", "-5s", "week", "5x", "5dd", "infs", "nans", ""] {
            assert!(TimeDelta::parse(rejected).is_err(), "{rejected}");
        }
    }

    #[test]
    fn durations_serialize_like_the_api() {
        for (seconds, expected) in [
            (90, "PT1M30S"),
            (1800, "PT30M"),
            (93600, "P1DT2H"),
            (0, "PT0S"),
            (172800, "P2D"),
        ] {
            assert_eq!(TimeDelta::from_secs(seconds).to_string(), expected);
        }

        let fractional = TimeDelta(Duration::from_micros(1500));
        assert_eq!(fractional.to_string(), "PT0.0015S");
        let fifteen_and_a_half = TimeDelta(Duration::from_millis(15500));
        assert_eq!(fifteen_and_a_half.to_string(), "PT15.5S");
    }

    #[test]
    fn byte_sizes_parse_decimal_and_binary_units() {
        assert_eq!(ByteSize::parse("500").unwrap().bytes(), 500);
        assert_eq!(ByteSize::parse("1KiB").unwrap().bytes(), 1024);
        assert_eq!(ByteSize::parse("2.5MB").unwrap().bytes(), 2_500_000);
        assert!(ByteSize::parse("10 lightyears").is_err());
    }

    #[test]
    fn maybe_sequences_keep_their_written_shape() {
        let one: MaybeSequence<String> = yaml_serde::from_str("'*'").unwrap();
        assert_eq!(one, MaybeSequence::One("*".to_string()));
        assert_eq!(serde_json::to_string(&one).unwrap(), "\"*\"");

        let many: MaybeSequence<String> = yaml_serde::from_str("[a, b]").unwrap();
        assert_eq!(many.as_slice().len(), 2);
    }
}
