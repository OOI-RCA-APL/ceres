//! The project files section, what the console's file browser serves.

use std::collections::BTreeMap;
use std::path::PathBuf;

use ceres_macros::kebab_aliases;
use globset::{Glob, GlobBuilder, GlobSet, GlobSetBuilder};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::{Problem, Problems};
use crate::types::Name;
use crate::values::ByteSize;

/// What the console's file browser serves.
#[kebab_aliases]
#[derive(Debug, Clone, Default, PartialEq, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields, rename_all = "kebab-case")]
#[schemars(title = "ServerFilesConfig")]
pub struct RawServerFilesConfig {
    /// Directories the file browser serves besides component mounts, keyed by name, each a
    /// path or a mapping of `path`, `access`, `layout`, and `zone`. A relative path resolves
    /// against the project directory. On a network share each listed entry costs a round trip.
    pub mounts: Option<BTreeMap<String, RawEngineMount>>,

    /// Glob patterns naming entries that are never listed or served, in any mount, such as
    /// `.venv` and `node_modules`. A pattern without a `/` matches an entry's name at any
    /// depth, and a pattern with one, or starting with one, matches the path from the root.
    pub exclude: Option<Vec<String>>,

    /// Largest file one upload may write, such as `2GiB`, unlimited when omitted.
    pub max_upload: Option<ByteSize>,

    /// Most any caller may do with any mount, `edit` when omitted. `view` makes every mount
    /// read-only and `none` turns the file browser off.
    pub access: Option<MountAccess>,

    /// Whether the console may show where an entry lives on the server, `true` when omitted.
    pub reveal_paths: Option<bool>,
}

/// What the files API may do with a mount, each level implying every level below it.
#[derive(
    Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, JsonSchema,
)]
#[serde(rename_all = "lowercase")]
pub enum MountAccess {
    /// The mount is unlisted and every route answers 404.
    None,
    /// Callers may list, preview, and download files.
    View,
    /// Callers may also upload, rename, move, and delete files.
    #[default]
    Edit,
}

/// A directory the file browser serves on the engine's behalf, as `server.files.mounts`
/// writes it.
#[derive(Debug, Clone, PartialEq, Deserialize, JsonSchema)]
#[serde(untagged)]
pub enum RawEngineMount {
    /// The directory alone.
    Path(PathBuf),
    /// The directory and the most the files API may do with it.
    Setting(RawEngineMountSetting),
}

/// The mapping form of an engine mount.
// Mirrors `MountSetting` in `ceres/mount.py`, which a component's mount field parses, so the
// two keep the same fields.
#[derive(Debug, Clone, PartialEq, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct RawEngineMountSetting {
    /// The mount's root directory.
    pub path: PathBuf,
    /// Most the files API may do with the mount, `edit` when omitted.
    pub access: Option<MountAccess>,
    /// Dated folders below the root, such as `{yyyy}/{MM}`. The engine checks it when it starts.
    pub layout: Option<String>,
    /// Time zone the layout reads in, `utc`, `local`, or an IANA name, `utc` when omitted.
    pub zone: Option<String>,
}

/// A validated engine mount.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct EngineMount {
    pub path: PathBuf,
    pub access: Option<MountAccess>,
    pub layout: Option<String>,
    pub zone: Option<String>,
}

impl From<RawEngineMount> for EngineMount {
    fn from(raw: RawEngineMount) -> Self {
        match raw {
            RawEngineMount::Path(path) => Self {
                path,
                ..Self::default()
            },
            RawEngineMount::Setting(RawEngineMountSetting {
                path,
                access,
                layout,
                zone,
            }) => Self {
                path,
                access,
                layout,
                zone,
            },
        }
    }
}

/// Validated configuration of the console's file browser.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ServerFilesConfig {
    pub mounts: BTreeMap<String, EngineMount>,
    pub exclude: Vec<String>,
    pub max_upload: Option<ByteSize>,
    pub access: MountAccess,
    pub reveal_paths: bool,
}

impl Default for ServerFilesConfig {
    fn default() -> Self {
        Self {
            mounts: BTreeMap::new(),
            exclude: Vec::new(),
            max_upload: None,
            access: MountAccess::default(),
            reveal_paths: true,
        }
    }
}

impl TryFrom<RawServerFilesConfig> for ServerFilesConfig {
    type Error = Problems;

    fn try_from(raw: RawServerFilesConfig) -> Result<Self, Problems> {
        let exclude = raw.exclude.unwrap_or_default();
        let mut problems = Problems::default();
        let mut mounts = BTreeMap::new();
        for (name, mount) in raw.mounts.unwrap_or_default() {
            if let Err(problem) = Name::parse(&name) {
                problems.push(Problem::new("mounts", problem.message));
                continue;
            }

            mounts.insert(name, mount.into());
        }

        for pattern in &exclude {
            if let Err(error) = FileExclusion::glob(pattern) {
                problems.push(Problem::new(
                    "exclude",
                    format!("{pattern:?} {}.", error.kind()),
                ));
            }
        }

        problems.into_result(Self {
            mounts,
            exclude,
            max_upload: raw.max_upload,
            access: raw.access.unwrap_or_default(),
            reveal_paths: raw.reveal_paths.unwrap_or(true),
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

    /// Whether no pattern was given, so nothing is ever excluded.
    pub fn is_empty(&self) -> bool {
        self.names.is_empty() && self.anchored.is_empty()
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
        assert!(FileExclusion::default().is_empty());
        assert!(!exclusion(&["/a"]).is_empty());
        assert!(!exclusion(&["a"]).is_empty());
    }

    #[test]
    fn an_invalid_pattern_is_a_problem() {
        let raw: RawServerFilesConfig =
            yaml_serde::from_str("exclude: ['a[', ok]\nmounts: {data: data}\n").unwrap();
        let problems = ServerFilesConfig::try_from(raw).unwrap_err();
        assert_eq!(problems.0.len(), 1);
        assert_eq!(problems.0[0].location, "exclude");
    }

    #[test]
    fn a_mount_is_a_path_or_a_mapping_under_a_valid_name() {
        let parse = |yaml: &str| {
            let raw: RawServerFilesConfig = yaml_serde::from_str(yaml).unwrap();
            ServerFilesConfig::try_from(raw)
        };
        let mount = |path: &str, access| EngineMount {
            path: PathBuf::from(path),
            access,
            ..EngineMount::default()
        };
        let config = parse(
            "mounts: {a: ./a, b: {path: /b, access: view}, c: {path: c, layout: '{yyyy}', zone: local}}",
        )
        .unwrap();
        assert_eq!(
            config.mounts.into_iter().collect::<Vec<_>>(),
            [
                ("a".to_string(), mount("./a", None)),
                ("b".to_string(), mount("/b", Some(MountAccess::View))),
                (
                    "c".to_string(),
                    EngineMount {
                        layout: Some("{yyyy}".into()),
                        zone: Some("local".into()),
                        ..mount("c", None)
                    }
                ),
            ]
        );
        assert!(parse("{}").unwrap().mounts.is_empty());

        let problems = parse("mounts: {'@a': ./a}").unwrap_err();
        assert_eq!(problems.0[0].location, "mounts");
        assert!(
            yaml_serde::from_str::<RawServerFilesConfig>("mounts: {a: {path: a, b: c}}").is_err()
        );
    }

    #[test]
    fn access_defaults_to_edit_and_orders_by_what_it_permits() {
        let access = |yaml: &str| {
            let raw: RawServerFilesConfig = yaml_serde::from_str(yaml).unwrap();
            ServerFilesConfig::try_from(raw).unwrap().access
        };
        assert_eq!(access("{}"), MountAccess::Edit);
        assert_eq!(access("access: view"), MountAccess::View);
        assert_eq!(access("access: none"), MountAccess::None);
        assert!(MountAccess::None < MountAccess::View && MountAccess::View < MountAccess::Edit);
    }

    #[test]
    fn paths_are_revealed_unless_turned_off() {
        let reveal_paths = |yaml: &str| {
            let raw: RawServerFilesConfig = yaml_serde::from_str(yaml).unwrap();
            ServerFilesConfig::try_from(raw).unwrap().reveal_paths
        };
        assert!(reveal_paths("{}"));
        assert!(!reveal_paths("reveal-paths: false"));
        assert!(ServerFilesConfig::default().reveal_paths);
    }
}
