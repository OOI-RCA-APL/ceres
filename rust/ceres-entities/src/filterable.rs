//! The filterable field surface of an entity.
//!
//! `#[derive(Filterable)]` reads an entity struct and emits its `FIELDS` table, one
//! entry per field, so the filter surface follows the entity definitions at compile
//! time. Two kinds of filter derive from a field, and a third exists apart from them:
//!
//! - **Field filters** match a field's value, equality for every family plus what the
//!   family brings, the window operators for a timestamp and ordered bounds for a
//!   level.
//! - **Field operation filters** match within a field's content, the `contains`,
//!   `prefix`, and `suffix` variants on text, byte, and JSON fields, each compiling to
//!   the backend's own matching expression.
//! - **Query filters** shape the query rather than match fields, `order`, `limit`, and
//!   `offset`, plus the structural constructs, subfilter combinators and subsampling,
//!   which compile from their own wire keys rather than from a field.

use ceres_config::Level;

/// One filterable field, its wire key and the family its type placed it in.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FilterField {
    /// The field's wire name, the `#[serde(rename)]` value when one is present.
    pub key: &'static str,
    pub family: FieldFamily,
    /// The field's operation filters, their keys generated from the key at derive
    /// time.
    ///
    /// Prefixed on the key by default (`type_contains`), bare where the Python filter
    /// names them bare (`contains` on a log's content and a message's data), which the
    /// entity marks with `#[filterable(bare_operations)]`.
    pub operations: &'static [FieldOperation],
}

/// One operation filter on a field, its wire key and what it matches.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct FieldOperation {
    pub key: &'static str,
    pub kind: OperationKind,
}

/// How an operation filter matches within a field's content.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum OperationKind {
    Contains,
    Prefix,
    Suffix,
}

/// The filter family a field's type belongs to, which decides its operators.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum FieldFamily {
    /// Equality on a UUID, stored as text on the SQLite family.
    Uuid,
    /// Equality on a plain absolute address.
    Address,
    /// Equality plus the window operators, `after`, `before`, `timespan`, `max_age`,
    /// and `min_age`.
    Timestamp,
    /// Equality on text.
    Text,
    /// Equality over a closed set of values, a plain enum's variants.
    Values(&'static [&'static str]),
    /// Equality plus ordered bounds, `min_` and `max_` prefixed on the field's key.
    Level,
    /// Raw bytes, equality on the stored blob plus whole-byte operations.
    Bytes,
    /// A JSON payload, whose operations match its serialized text and which carries
    /// no equality key of its own.
    Json,
    /// Equality on a boolean, which takes one value rather than a set of them.
    Boolean,
    /// Equality on the serialized text of a JSON value, which carries no operations.
    ///
    /// A variable's value compares this way, on the text the column stores, so that
    /// numbers, strings, and structures all compare by the same rule.
    JsonValue,
    /// Equality on a whole address, outside the selector grammar.
    ///
    /// A workspace's scope is the one address in the system filtered this way. It names
    /// a subtree rather than a component, so matching it against a selector's segments
    /// would mean something else entirely.
    PlainAddress,
}

impl FieldFamily {
    /// Whether the family's own key filters by equality and orders natively.
    ///
    /// JSON payloads are the exception, the Python filters give them operation keys
    /// only, so their own key is not part of the wire surface.
    pub fn native(&self) -> bool {
        !matches!(self, Self::Json)
    }

    /// Whether the family takes one value rather than a set of them.
    ///
    /// A boolean filter is a scalar in the Python models, so a list is a validation
    /// error rather than an `IN`.
    pub fn scalar(&self) -> bool {
        matches!(self, Self::Boolean)
    }
}

/// An entity whose filterable fields are known at compile time.
pub trait Filterable {
    const FIELDS: &'static [FilterField];
}

/// A type with a closed set of admissible wire values.
pub trait FilterValues {
    /// The values in declaration order, which for ordered enums is severity order.
    const VALUES: &'static [&'static str];
}

impl FilterValues for Level {
    const VALUES: &'static [&'static str] = &["debug", "info", "warning", "error", "critical"];
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The level names must track the enum, in order, or bound expansion drifts.
    #[test]
    fn level_values_match_the_enum() {
        for (name, level) in Level::VALUES.iter().zip([
            Level::Debug,
            Level::Info,
            Level::Warning,
            Level::Error,
            Level::Critical,
        ]) {
            assert_eq!(Level::parse(name), Ok(level));
            assert_eq!(level.as_str(), *name);
        }
    }
}
