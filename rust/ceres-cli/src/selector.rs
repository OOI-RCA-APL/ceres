//! Component address selectors.
//!
//! A selector consists of one or more pipe-separated segments where each segment is either a
//! literal address (e.g. `@sensor`), the special base `~` (engine), or a base followed by a
//! modifier (`:all`, `:children`, `:descendants`). The engine resolves and matches selectors,
//! the CLI validates their form and passes them through.

use std::sync::LazyLock;

use regex_lite::Regex;

use crate::error::{Result, fail};

static SEGMENT_REGEX: LazyLock<Regex> = LazyLock::new(|| {
    let name = r"[a-zA-Z_\-][a-zA-Z0-9_\-]*";
    let modifier = r":(all|children|descendants)";
    let path = format!(r"@?{name}(\.{name})*");
    let segment = format!(r"\~(:(all|descendants))?|{path}({modifier})?|@{modifier}|{modifier}");

    Regex::new(&format!(r"^(?:{segment})(\|(?:{segment}))*$")).expect("the pattern compiles")
});

/// A validated address selector in textual form.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Selector(String);

impl Selector {
    /// Validate a selector's textual form.
    pub fn parse(text: &str) -> Result<Self> {
        if !SEGMENT_REGEX.is_match(text) {
            fail!(
                "Invalid address selector {text:?}. If your shell expanded a wildcard, quote \
                 the selector."
            );
        }

        Ok(Self(text.to_string()))
    }

    /// Join selectors into a single pipe-separated selector.
    ///
    /// Returns the selector matching every component when `selectors` is empty.
    pub fn join(selectors: &[Selector]) -> Selector {
        if selectors.is_empty() {
            return Selector("all".to_string());
        }

        Selector(
            selectors
                .iter()
                .map(|selector| selector.0.as_str())
                .collect::<Vec<_>>()
                .join("|"),
        )
    }

    pub fn text(&self) -> &str {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_selectors_parse() {
        for text in [
            "all",
            ":all",
            "sensor",
            "sensor.child",
            "@sensor",
            "@sensor.child:descendants",
            "~",
            "~:all",
            "@:children",
            "a|b.c|~:descendants",
        ] {
            assert!(Selector::parse(text).is_ok(), "{text} failed to parse");
        }
    }

    #[test]
    fn invalid_selectors_fail() {
        for text in [
            "",
            "sensor..child",
            "sensor.*",
            "1sensor",
            "a||b",
            "~:children",
        ] {
            assert!(Selector::parse(text).is_err(), "{text} parsed");
        }
    }

    #[test]
    fn empty_selector_lists_join_to_all() {
        assert_eq!(Selector::join(&[]).text(), "all");

        let selectors = [Selector::parse("a").unwrap(), Selector::parse("b").unwrap()];
        assert_eq!(Selector::join(&selectors).text(), "a|b");
    }
}
