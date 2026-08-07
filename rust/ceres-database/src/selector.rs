//! Address selector matching.
//!
//! A selector is one or more pipe-separated segments, each a literal address, the
//! engine `~`, or a base with a `:all`, `:children`, or `:descendants` modifier.
//! Relative segments resolve against a root address before compiling, and each
//! segment compiles to the condition the Python `AddressSelector.matches_expression`
//! builds, the whole selector matching where any segment does. The SQLite family
//! matches prefixes with `GLOB` so comparison stays case-sensitive like the in-memory
//! selector, PostgreSQL with an escaped `LIKE`.

use sea_query::{Alias, BinOper, Expr, LikeExpr, SimpleExpr};

use crate::filter::{SqlDialect, glob_escape, like_escape};

/// A validated address selector, its segments held in wire form.
#[derive(Clone, Debug, Default, PartialEq)]
pub(crate) struct AddressSelector {
    segments: Vec<String>,
}

/// The modifiers a segment base can carry.
#[derive(Clone, Copy, PartialEq)]
enum Modifier {
    All,
    Children,
    Descendants,
}

impl Modifier {
    fn parse(text: &str) -> Option<Self> {
        match text {
            "all" => Some(Self::All),
            "children" => Some(Self::Children),
            "descendants" => Some(Self::Descendants),
            _ => None,
        }
    }
}

impl AddressSelector {
    /// Add one wire value's segments, pipe-separated, refusing invalid ones.
    ///
    /// Repeated wire keys fold into one selector, the way the Python layer collects
    /// them into a list the selector joins.
    pub(crate) fn push(&mut self, value: &str) -> Result<(), String> {
        for segment in value.split('|') {
            if !valid_segment(segment) {
                return Err(format!("invalid address selector {value:?}"));
            }

            self.segments.push(segment.to_string());
        }

        Ok(())
    }

    /// Compile the selector against a root, as one condition over the address column.
    pub(crate) fn condition(
        &self,
        key: &'static str,
        root: Option<&str>,
        dialect: SqlDialect,
    ) -> SimpleExpr {
        self.segments
            .iter()
            .map(|segment| segment_condition(key, &absolute_segment(segment, base(root)), dialect))
            .reduce(|combined, condition| combined.or(condition))
            .expect("a selector always holds at least one segment")
    }

    /// Whether an address is selected, resolved against a root, like the Python
    /// `AddressSelector.matches`.
    pub(crate) fn matches(&self, address: &str, root: Option<&str>) -> bool {
        self.segments
            .iter()
            .any(|segment| segment_matches(&absolute_segment(segment, base(root)), address))
    }
}

/// The base relative segments resolve against, every component when the root is absent
/// or the engine.
fn base(root: Option<&str>) -> &str {
    match root {
        None | Some("~") => "@",
        Some(root) => root,
    }
}

/// Whether one absolute segment selects an address, mirroring the compiled SQL.
fn segment_matches(segment: &str, address: &str) -> bool {
    let Some((base, modifier)) = segment.split_once(':') else {
        return address == segment;
    };

    let modifier = Modifier::parse(modifier).expect("validation admits known modifiers only");

    if base == "~" {
        return match modifier {
            Modifier::All => true,
            _ => address != "~",
        };
    }

    if base == "@" {
        return match modifier {
            Modifier::All | Modifier::Descendants => address != "~",
            Modifier::Children => address.starts_with('@') && !address.contains('.'),
        };
    }

    let descendant = address
        .strip_prefix(base)
        .and_then(|rest| rest.strip_prefix('.'));
    match modifier {
        Modifier::All => address == base || descendant.is_some(),
        Modifier::Descendants => descendant.is_some(),
        Modifier::Children => descendant.is_some_and(|rest| !rest.contains('.')),
    }
}

/// Whether a root value is an absolute address, `~` or `@` with dotted names.
pub(crate) fn valid_address(text: &str) -> bool {
    if text == "~" {
        return true;
    }

    match text.strip_prefix('@') {
        Some(path) => valid_path(path),
        None => false,
    }
}

/// Resolve one segment against the base, normalizing the bare `all` first.
///
/// Segments already anchored at `~` or `@` stay untouched, a bare `:modifier` hangs
/// off the base, and a relative path joins under it.
fn absolute_segment(segment: &str, base: &str) -> String {
    let segment = if segment == "all" { ":all" } else { segment };

    if segment.starts_with(':') {
        format!("{base}{segment}")
    } else if segment.starts_with('~') || segment.starts_with('@') {
        segment.to_string()
    } else if base == "@" {
        format!("{base}{segment}")
    } else {
        format!("{base}.{segment}")
    }
}

/// Compile one absolute segment to its condition, like the Python selector's.
fn segment_condition(key: &'static str, segment: &str, dialect: SqlDialect) -> SimpleExpr {
    let column = || Expr::col(Alias::new(key));

    let Some((base, modifier)) = segment.split_once(':') else {
        return column().eq(segment);
    };

    let modifier = Modifier::parse(modifier).expect("validation admits known modifiers only");

    if base == "~" {
        // The engine has no children segment form, so only these two arise.
        return match modifier {
            Modifier::All => Expr::value(true),
            _ => column().ne("~"),
        };
    }

    if base == "@" {
        // With no root component, `all` and `descendants` both select every
        // component, and `children` selects the top-level ones. The patterns hold no
        // letters, so a plain `LIKE` compares identically everywhere.
        return match modifier {
            Modifier::All | Modifier::Descendants => column().ne("~"),
            Modifier::Children => column().like("@%").and(column().not_like("%.%")),
        };
    }

    // A prefix pattern must compare case and treat the `_` a component name can
    // contain literally, `GLOB` gives the SQLite family both and PostgreSQL's own
    // `LIKE` needs only the escape.
    let prefixed = |depth: &str| match dialect {
        SqlDialect::SqliteText => {
            let pattern = format!("{}.{depth}", glob_escape(base)).replace('%', "*");
            column().binary(BinOper::Custom("GLOB"), Expr::val(pattern))
        }
        SqlDialect::Postgres => {
            let pattern = format!("{}.{depth}", like_escape(base));
            column().like(LikeExpr::new(pattern).escape('^'))
        }
    };
    match modifier {
        Modifier::All => column().eq(base).or(prefixed("%")),
        Modifier::Descendants => prefixed("%"),
        Modifier::Children => prefixed("%").and(prefixed("%.%").not()),
    }
}

/// Whether one segment matches the selector grammar.
fn valid_segment(segment: &str) -> bool {
    match segment {
        "~" | "~:all" | "~:descendants" => return true,
        _ => {}
    }

    match segment.split_once(':') {
        Some((base, modifier)) => {
            if Modifier::parse(modifier).is_none() {
                return false;
            }

            // A modifier hangs off the engine handled above, every component (`@`), a
            // bare base resolved against the root, or a path.
            match base {
                "" | "@" => true,
                _ => valid_optionally_absolute_path(base),
            }
        }
        None => valid_optionally_absolute_path(segment),
    }
}

/// Whether text is a dotted name path, with or without the `@` anchor.
fn valid_optionally_absolute_path(text: &str) -> bool {
    let path = text.strip_prefix('@').unwrap_or(text);
    valid_path(path)
}

/// Whether text is one or more dot-separated component names.
fn valid_path(text: &str) -> bool {
    !text.is_empty() && text.split('.').all(valid_name)
}

/// Whether text is one component name, a letter, underscore, or hyphen followed by
/// those plus digits.
fn valid_name(text: &str) -> bool {
    let mut characters = text.chars();
    let Some(first) = characters.next() else {
        return false;
    };
    if !(first.is_ascii_alphabetic() || first == '_' || first == '-') {
        return false;
    }

    characters
        .all(|character| character.is_ascii_alphanumeric() || character == '_' || character == '-')
}

#[cfg(test)]
mod tests {
    use sea_query::{Query, SqliteQueryBuilder};

    use super::*;

    fn render(selector: &AddressSelector, root: Option<&str>, dialect: SqlDialect) -> String {
        let mut statement = Query::select();
        statement
            .expr(Expr::val(1))
            .and_where(selector.condition("address", root, dialect));
        match dialect {
            SqlDialect::SqliteText => statement.to_string(SqliteQueryBuilder),
            SqlDialect::Postgres => statement.to_string(sea_query::PostgresQueryBuilder),
        }
    }

    fn selector(values: &[&str]) -> AddressSelector {
        let mut selector = AddressSelector::default();
        for value in values {
            selector.push(value).unwrap();
        }

        selector
    }

    #[test]
    fn segments_validate_the_grammar() {
        for valid in [
            "~",
            "~:all",
            "~:descendants",
            "@a",
            "@a.b-c",
            "@a:children",
            "a.b:descendants",
            ":all",
            "@:children",
            "all",
            "@a|@b:all",
            "_x",
        ] {
            assert!(selector(&[]).push(valid).is_ok(), "{valid}");
        }

        for invalid in [
            "",
            "@",
            "~:children",
            "@a:cousins",
            "@a..b",
            "@.a",
            "@a.",
            "a b",
            "@a:all:all",
            "9a",
            "|@a",
        ] {
            assert!(selector(&[]).push(invalid).is_err(), "{invalid}");
        }
    }

    #[test]
    fn literals_compile_to_equality() {
        let sql = render(&selector(&["@sensor.temp"]), None, SqlDialect::SqliteText);
        assert!(sql.contains("\"address\" = '@sensor.temp'"), "{sql}");
    }

    #[test]
    fn modifiers_compile_per_backend() {
        let sql = render(&selector(&["@a:all"]), None, SqlDialect::Postgres);
        assert!(
            sql.contains("\"address\" = '@a' OR \"address\" LIKE '@a.%' ESCAPE '^'"),
            "{sql}"
        );

        let sql = render(&selector(&["@a:all"]), None, SqlDialect::SqliteText);
        assert!(
            sql.contains("\"address\" = '@a' OR (\"address\" GLOB '@a.*')"),
            "{sql}"
        );

        let sql = render(&selector(&["@a:children"]), None, SqlDialect::SqliteText);
        assert!(
            sql.contains("GLOB '@a.*'") && sql.contains("NOT") && sql.contains("GLOB '@a.*.*'"),
            "{sql}"
        );

        let sql = render(&selector(&["@a:children"]), None, SqlDialect::Postgres);
        assert!(
            sql.contains(
                "\"address\" LIKE '@a.%' ESCAPE '^' AND (NOT \"address\" LIKE '@a.%.%' ESCAPE '^')"
            ),
            "{sql}"
        );

        let sql = render(&selector(&["~:descendants"]), None, SqlDialect::SqliteText);
        assert!(sql.contains("\"address\" <> '~'"), "{sql}");

        let sql = render(&selector(&["@:children"]), None, SqlDialect::SqliteText);
        assert!(
            sql.contains("\"address\" LIKE '@%' AND \"address\" NOT LIKE '%.%'"),
            "{sql}"
        );
    }

    #[test]
    fn underscores_stay_literal_in_patterns() {
        let sql = render(&selector(&["@a_b:descendants"]), None, SqlDialect::Postgres);
        assert!(sql.contains("LIKE '@a^_b.%' ESCAPE '^'"), "{sql}");

        let sql = render(
            &selector(&["@a_b:descendants"]),
            None,
            SqlDialect::SqliteText,
        );
        assert!(sql.contains("GLOB '@a_b.*'"), "{sql}");
    }

    #[test]
    fn relative_segments_resolve_against_the_root() {
        let sql = render(&selector(&["motor"]), Some("@deck"), SqlDialect::SqliteText);
        assert!(sql.contains("\"address\" = '@deck.motor'"), "{sql}");

        let sql = render(
            &selector(&[":children"]),
            Some("@deck"),
            SqlDialect::SqliteText,
        );
        assert!(sql.contains("GLOB '@deck.*'"), "{sql}");

        let sql = render(&selector(&["motor"]), None, SqlDialect::SqliteText);
        assert!(sql.contains("\"address\" = '@motor'"), "{sql}");

        let sql = render(&selector(&["motor"]), Some("~"), SqlDialect::SqliteText);
        assert!(sql.contains("\"address\" = '@motor'"), "{sql}");
    }

    #[test]
    fn multiple_values_combine_as_segments() {
        let sql = render(
            &selector(&["@a", "@b:descendants"]),
            None,
            SqlDialect::SqliteText,
        );
        assert!(
            sql.contains("\"address\" = '@a' OR (\"address\" GLOB '@b.*')"),
            "{sql}"
        );
    }

    #[test]
    fn roots_validate_as_absolute_addresses() {
        for valid in ["~", "@a", "@a.b-c", "@x_y.z"] {
            assert!(valid_address(valid), "{valid}");
        }

        for invalid in ["", "@", "a", "a.b", "@a.", "@a:all", "~x"] {
            assert!(!valid_address(invalid), "{invalid}");
        }
    }
}
