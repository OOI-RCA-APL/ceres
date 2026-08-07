//! Component addresses.

use std::fmt;

use serde::{Deserialize, Serialize};

/// A concrete component address.
///
/// The engine's own address is `~`. Component addresses start with `@` and name a path of
/// component names separated by dots, `@system.sensor.parser`. Each name matches the same
/// pattern component names do everywhere else.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct Address(String);

impl Address {
    /// Parse an address, validating its shape.
    pub fn parse(text: &str) -> Result<Self, String> {
        if is_valid(text) {
            Ok(Self(text.to_string()))
        } else {
            Err(format!("{text:?} is not a valid component address"))
        }
    }

    /// Wrap a string that is already known to be a valid address.
    ///
    /// Values arriving from the database were validated when written, revalidating them on
    /// every read would only cost time.
    pub fn trusted(text: String) -> Self {
        Self(text)
    }

    /// View the address as text.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for Address {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl<'de> Deserialize<'de> for Address {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        if !is_valid(&text) {
            return Err(serde::de::Error::custom(format!(
                "{text:?} is not a valid component address"
            )));
        }

        Ok(Self(text))
    }
}

/// Check an address against `~` or `@name(.name)*`.
fn is_valid(text: &str) -> bool {
    if text == "~" {
        return true;
    }

    let Some(path) = text.strip_prefix('@') else {
        return false;
    };

    path.split('.').all(is_valid_name)
}

/// Check one path segment against the component name pattern.
fn is_valid_name(name: &str) -> bool {
    let mut characters = name.chars();
    let Some(first) = characters.next() else {
        return false;
    };

    if !(first.is_ascii_alphabetic() || first == '_' || first == '-') {
        return false;
    }

    characters.all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn addresses_validate_their_shape() {
        assert!(Address::parse("~").is_ok());
        assert!(Address::parse("@sensor").is_ok());
        assert!(Address::parse("@system.sensor-1.parser_a").is_ok());
        assert!(Address::parse("sensor").is_err());
        assert!(Address::parse("@").is_err());
        assert!(Address::parse("@a..b").is_err());
        assert!(Address::parse("@1abc").is_err());
    }

    #[test]
    fn addresses_serialize_transparently() {
        let address = Address::parse("@sensor.temp").unwrap();
        assert_eq!(serde_json::to_string(&address).unwrap(), "\"@sensor.temp\"");
    }
}
