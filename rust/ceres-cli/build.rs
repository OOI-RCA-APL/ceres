//! Read the Ceres package version from pyproject.toml at the repository root.
//!
//! The binary reports the same version as the Python package, so the version lives in exactly
//! one place. The crate's own version stays a placeholder.

use std::path::Path;

fn main() {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set");
    let pyproject = Path::new(&manifest).join("../../pyproject.toml");
    println!("cargo::rerun-if-changed={}", pyproject.display());

    let content = std::fs::read_to_string(&pyproject)
        .unwrap_or_else(|error| panic!("failed to read {}: {error}", pyproject.display()));
    let version = parse_version(&content)
        .unwrap_or_else(|| panic!("no version line found in {}", pyproject.display()));

    println!("cargo::rustc-env=CERES_VERSION={version}");
}

/// Return the value of the first top-level `version = "..."` line.
fn parse_version(pyproject: &str) -> Option<String> {
    for line in pyproject.lines() {
        let Some(rest) = line.strip_prefix("version") else {
            continue;
        };

        let rest = rest.trim_start();
        let Some(rest) = rest.strip_prefix('=') else {
            continue;
        };

        return Some(rest.trim().trim_matches('"').to_string());
    }

    None
}
