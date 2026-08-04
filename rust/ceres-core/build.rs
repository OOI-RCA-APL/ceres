use std::env;
use std::fs;
use std::path::PathBuf;
use std::process;

/// Stage the native CLI binary where maturin's data-directory convention picks it up.
///
/// The binary arrives as an artifact dependency, already compiled for the same target as
/// the extension module, so wheels built from CI, a checkout, or an sdist all carry the
/// `ceres` command without a staging step outside the build. The copy lands in
/// `<repository root>/ceres.__internal__.core.data/scripts/`, which maturin folds into
/// the wheel's data scripts and installers unpack onto the environment's `bin`.
fn main() {
    let artifact = PathBuf::from(
        env::var_os("CARGO_BIN_FILE_CERES_CLI_ceres")
            .expect("cargo provided no `ceres-cli` artifact, `bindeps` may be disabled"),
    );

    let manifest = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let root = manifest.parent().unwrap().parent().unwrap();
    let scripts = root.join("ceres.__internal__.core.data").join("scripts");
    fs::create_dir_all(&scripts).expect("failed to create the wheel data scripts directory");

    // The artifact arrives under a hashed file name, so the staged copy takes the command
    // name itself, suffixed for the target the binary was built for rather than the host
    // running this script.
    let name = if env::var_os("CARGO_CFG_WINDOWS").is_some() {
        "ceres.exe"
    } else {
        "ceres"
    };

    // The sdist ships a `.keep` marker so extracting it creates this directory, which
    // maturin requires to exist before the build starts. The marker's job is done once
    // the build is running, and removing it keeps it out of the wheel, where anything
    // under `scripts/` would land on the user's `bin`.
    let _ = fs::remove_file(scripts.join(".keep"));

    // The stub generator builds a second copy of this crate for the host, so two build
    // scripts can stage concurrently. Writing to a per-process name and renaming keeps
    // the staged binary whole no matter how the two interleave.
    let staged = scripts.join(name);
    let partial = scripts.join(format!(".{}.{}.partial", name, process::id()));
    fs::copy(&artifact, &partial).expect("failed to copy the CLI binary into the wheel data");
    fs::rename(&partial, &staged).expect("failed to move the CLI binary into place");
}
