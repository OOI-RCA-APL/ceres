//! Credential scrubbing.
//!
//! Configuration payloads drop credential-bearing fields by name at every nesting
//! level before they serve. Admin access means permission to read the configuration,
//! not to walk away with the signing secret, which mints a session token for any user.

use serde_json::Value;

/// The field names that never serve, wherever they appear.
const CREDENTIAL_FIELDS: [&str; 3] = ["secret", "password", "key_password"];

/// Drop credential fields from a payload, recursing through objects and arrays.
pub fn scrub_credentials(value: Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .into_iter()
                .filter(|(name, _)| !CREDENTIAL_FIELDS.contains(&name.as_str()))
                .map(|(name, value)| (name, scrub_credentials(value)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.into_iter().map(scrub_credentials).collect()),
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn credentials_drop_at_every_level() {
        let scrubbed = scrub_credentials(json!({
            "secret": "s",
            "server": {"authentication": {"secret": "s", "duration": 1800}},
            "components": [{"arguments": {"password": "p", "kept": true}}],
            "ssl": {"key_password": "k", "cert": "cert.pem"},
        }));
        assert_eq!(
            scrubbed,
            json!({
                "server": {"authentication": {"duration": 1800}},
                "components": [{"arguments": {"kept": true}}],
                "ssl": {"cert": "cert.pem"},
            })
        );
    }
}
