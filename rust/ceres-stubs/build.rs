//! Generate `ceres_core.pyi` whenever the extension module's sources change.
//!
//! `ceres-core` is a build dependency, so this script links the compiled module, gathers its
//! stub inventory, writes the polished stubs next to the extension crate's pyproject.toml,
//! and formats them with the project's ruff. Building the workspace keeps the stubs current,
//! and CI fails when a committed stub drifts.

use std::path::{Path, PathBuf};
use std::process::Command;

// The polish pass is shared with the library, where its unit tests live.
include!("src/polish.rs");

fn main() {
    println!("cargo::rerun-if-changed=src/polish.rs");
    println!("cargo::rerun-if-changed=../ceres-core/src");
    println!("cargo::rerun-if-changed=../ceres-config/src");

    let manifest = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("cargo sets this"));
    let stub_path = manifest.join("../ceres-core/ceres_core.pyi");

    let stub = ceres_core::stub_info().expect("the stub inventory gathers");
    stub.generate().expect("the stubs generate");

    let content = std::fs::read_to_string(&stub_path).expect("the generated stubs are readable");
    std::fs::write(&stub_path, polish(&content)).expect("the polished stubs write");

    format_with_ruff(&manifest, &stub_path);
}

/// Format the stubs with the project's ruff, silently skipping when ruff is unavailable.
///
/// Ruff is invoked directly rather than through `uv run`, because this script may itself be
/// running inside a `uv` invocation holding the environment lock.
fn format_with_ruff(manifest: &Path, stub_path: &Path) {
    let venv_ruff = manifest.join("../../.venv/bin/ruff");
    let ruff = if venv_ruff.is_file() {
        venv_ruff
    } else {
        PathBuf::from("ruff")
    };

    for arguments in [vec!["check", "--fix"], vec!["format"]] {
        let status = Command::new(&ruff).args(&arguments).arg(stub_path).status();
        if !status.map(|status| status.success()).unwrap_or(false) {
            println!(
                "cargo::warning=ruff {} did not run on {}, format the stubs with `make fix`",
                arguments.join(" "),
                stub_path.display()
            );
            return;
        }
    }
}
