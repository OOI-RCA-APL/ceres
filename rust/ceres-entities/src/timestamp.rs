//! Record timestamps.

use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize, Serializer};

/// A UTC timestamp serialized in the API's wire format.
///
/// The wire format is RFC 3339 with a `Z` suffix, carrying all six microsecond digits when
/// the timestamp has sub-second precision and none otherwise, `2026-07-29T12:30:45.123456Z`
/// or `2026-07-29T12:30:45Z`. Precision beyond microseconds is truncated, the databases
/// store no more than that.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Deserialize)]
pub struct Timestamp(pub DateTime<Utc>);

impl Timestamp {
    /// Render the wire form.
    pub fn to_wire(&self) -> String {
        if self.0.timestamp_subsec_micros() == 0 {
            self.0.to_rfc3339_opts(SecondsFormat::Secs, true)
        } else {
            self.0.to_rfc3339_opts(SecondsFormat::Micros, true)
        }
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_wire())
    }
}

#[cfg(test)]
mod tests {
    use chrono::TimeZone;

    use super::*;

    #[test]
    fn timestamps_serialize_like_the_api() {
        let plain = Timestamp(Utc.with_ymd_and_hms(2026, 7, 29, 12, 30, 45).unwrap());
        assert_eq!(plain.to_wire(), "2026-07-29T12:30:45Z");

        let fractional = Timestamp(Utc.timestamp_opt(plain.0.timestamp(), 123_456_000).unwrap());
        assert_eq!(fractional.to_wire(), "2026-07-29T12:30:45.123456Z");

        let low = Timestamp(Utc.timestamp_opt(plain.0.timestamp(), 100_000).unwrap());
        assert_eq!(low.to_wire(), "2026-07-29T12:30:45.000100Z");
    }
}
