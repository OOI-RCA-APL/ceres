//! Generate `ceres/__internal__/models/` whenever the entity definitions change.
//!
//! `ceres-database` is a build dependency, so this script reads the same table schemas
//! the compiler uses, renders one module per public entity module, and formats them
//! with the project's ruff. Building the workspace keeps the models current, and CI
//! fails when a committed module drifts.

include!("src/render.rs");

fn main() {
    println!("cargo::rerun-if-changed=src/render.rs");
    println!("cargo::rerun-if-changed=../ceres-entities/src");
    println!("cargo::rerun-if-changed=../ceres-database/src");

    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    generate(&root);
}
