//! The project files section, what the console's file browser serves.

use std::path::PathBuf;

use ceres_macros::kebab_aliases;
use globset::{Glob, GlobBuilder, GlobSet, GlobSetBuilder};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::values::ByteSize;

/// What the console's file browser serves.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerFilesConfig")]
pub struct RawServerFilesConfig {
    /// Directory the project root serves to administrators, the project directory when
    /// omitted. A relative path resolves against the project directory. On a network share each
    /// listed entry costs a round trip.
    pub root: Option<PathBuf>,

    /// Glob patterns naming entries that are never listed or served, in any root, such as
    /// `.venv` and `node_modules`. A pattern without a `/` matches an entry's name at any
    /// depth, and a pattern with one, or starting with one, matches the path from the root.
    pub exclude: Option<Vec<String>>,

    /// Largest file one upload may write, such as `2GiB`, unlimited when omitted.
    pub max_upload: Option<ByteSize>,
}

/// Validated configuration of the console's file browser.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct ServerFilesConfig {
    pub root: Option<PathBuf>,
    pub exclude: Vec<String>,
    pub max_upload: Option<ByteSize>,
}

impl TryFrom<RawServerFilesConfig> for ServerFilesConfig {
    type Error = Problems;

    fn try_from(raw: RawServerFilesConfig) -> Result<Self, Problems> {
        let exclude = raw.exclude.unwrap_or_default();
        let mut problems = Problems::default();
        for pattern in &exclude {
            if let Err(error) = FileExclusion::glob(pattern) {
                problems.push(Problem::new(
                    "exclude",
                    format!("{pattern:?} {}.", error.kind()),
                ));
            }
        }

        problems.into_result(Self {
            root: raw.root,
            exclude,
            max_upload: raw.max_upload,
        })
    }
}

/// The `exclude` patterns of the file browser, compiled to match root-relative paths.
#[derive(Debug, Clone, Default)]
pub struct FileExclusion {
    /// Patterns without a `/`, matched against each component of a path.
    names: GlobSet,
    /// Patterns with a `/`, matched against each leading run of components.
    anchored: GlobSet,
}

impl FileExclusion {
    /// Compile `patterns`, written as `exclude` takes them.
    pub fn new(
        patterns: impl IntoIterator<Item = impl AsRef<str>>,
    ) -> Result<Self, globset::Error> {
        let mut names = GlobSetBuilder::new();
        let mut anchored = GlobSetBuilder::new();
        for pattern in patterns {
            let pattern = pattern.as_ref();
            let glob = Self::glob(pattern)?;
            if pattern.contains('/') {
                anchored.add(glob);
            } else {
                names.add(glob);
            }
        }

        Ok(Self {
            names: names.build()?,
            anchored: anchored.build()?,
        })
    }

    /// Compile one pattern, a leading `/` dropped since every anchored pattern starts at
    /// the root.
    fn glob(pattern: &str) -> Result<Glob, globset::Error> {
        GlobBuilder::new(pattern.strip_prefix('/').unwrap_or(pattern))
            .literal_separator(true)
            .backslash_escape(true)
            .build()
    }

    /// Whether the entry at `relative`, its components joined by `/`, or any directory
    /// above it is excluded. The root itself, the empty path, never is.
    pub fn excludes(&self, relative: &str) -> bool {
        if relative.is_empty() {
            return false;
        }

        let mut end = 0;
        for name in relative.split('/') {
            end += name.len();
            if self.names.is_match(name) || self.anchored.is_match(&relative[..end]) {
                return true;
            }

            end += 1;
        }

        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn exclusion(patterns: &[&str]) -> FileExclusion {
        FileExclusion::new(patterns).unwrap()
    }

    #[test]
    fn a_name_pattern_matches_at_any_depth_and_hides_descendants() {
        let exclusion = exclusion(&[".venv", "*.key"]);
        assert!(exclusion.excludes(".venv"));
        assert!(exclusion.excludes("a/.venv/lib/site.py"));
        assert!(exclusion.excludes("tls/server.key"));
        assert!(!exclusion.excludes("venv"));
        assert!(!exclusion.excludes("a/b.keys"));
    }

    #[test]
    fn a_pattern_with_a_separator_matches_from_the_root() {
        for pattern in ["data/raw", "/data/raw"] {
            let exclusion = exclusion(&[pattern]);
            assert!(exclusion.excludes("data/raw"));
            assert!(exclusion.excludes("data/raw/a.csv"));
            assert!(!exclusion.excludes("data"));
            assert!(!exclusion.excludes("b/data/raw"));
        }

        assert!(exclusion(&["/node_modules"]).excludes("node_modules/a"));
        assert!(!exclusion(&["/node_modules"]).excludes("a/node_modules"));
    }

    #[test]
    fn a_wildcard_never_crosses_a_separator() {
        let exclusion = exclusion(&["data/*.csv"]);
        assert!(exclusion.excludes("data/a.csv"));
        assert!(!exclusion.excludes("data/b/a.csv"));
    }

    #[test]
    fn the_root_and_an_empty_exclusion_exclude_nothing() {
        assert!(!exclusion(&["*"]).excludes(""));
        assert!(!FileExclusion::default().excludes("a/b"));
    }

    #[test]
    fn an_invalid_pattern_is_a_problem() {
        let raw: RawServerFilesConfig =
            yaml_serde::from_str("exclude: ['a[', ok]\nroot: data\n").unwrap();
        let problems = ServerFilesConfig::try_from(raw).unwrap_err();
        assert_eq!(problems.0.len(), 1);
        assert_eq!(problems.0[0].location, "exclude");
    }
}
