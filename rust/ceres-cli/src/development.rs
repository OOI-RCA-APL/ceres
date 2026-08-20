//! Development-source delegation.
//!
//! `--development-source` runs the whole stack from a Ceres source checkout. The invoking
//! binary builds the checkout's CLI, points the current Python environment at an editable
//! install of the checkout, and replaces itself with the checkout's binary. An environment
//! marker stops the delegated binary from delegating again.

use std::convert::Infallible;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::error::{Result, fail, failure};
use crate::output::Output;
use crate::runtime;

/// The flag spelling, shared by the scanner and the stripper.
const FLAG: &str = "--development-source";

/// The disabling flag, winning over the flag and the environment variable.
const NO_FLAG: &str = "--no-development-source";

/// The environment variable providing a standing development source.
const VARIABLE: &str = "CERES_DEVELOPMENT_SOURCE";

/// The environment variable disabling the standing development source.
const NO_VARIABLE: &str = "CERES_NO_DEVELOPMENT_SOURCE";

/// Marks a process the delegation already replaced, stopping a second hop.
const DELEGATED: &str = "CERES_DEVELOPMENT_SOURCE_DELEGATED";

/// The development source in effect.
///
/// Either flag beats both environment variables, and the disabling side wins within each
/// pair, so `--no-development-source` turns a standing source off for one command and
/// `CERES_NO_DEVELOPMENT_SOURCE` turns it off for a whole session.
pub fn resolve(arguments: &[OsString]) -> Option<PathBuf> {
    if arguments.iter().any(|argument| argument == NO_FLAG) {
        return None;
    }

    if let Some(source) = source_from(arguments) {
        return Some(source);
    }

    if std::env::var_os(NO_VARIABLE).is_some_and(|value| !value.is_empty()) {
        return None;
    }

    std::env::var_os(VARIABLE)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

/// The `--development-source` value, read from the raw arguments.
pub fn source_from(arguments: &[OsString]) -> Option<PathBuf> {
    crate::cli::flag_value(arguments, FLAG)
}

/// Whether the current process was already delegated to the development source.
pub fn delegated() -> bool {
    std::env::var_os(DELEGATED).is_some()
}

/// Build the checkout's CLI, wire the environment to it, and replace this process.
///
/// Only returns on failure. A single warning line on stderr says the source is in use,
/// and the build and install underneath speak only when they have something to report.
pub fn delegate(source: &Path, arguments: Vec<OsString>, output: &Output) -> Result<Infallible> {
    let source = source.canonicalize().map_err(|error| {
        failure!(
            "Cannot resolve the development source {}. {error}",
            source.display()
        )
    })?;
    let rust = source.join("rust");
    if !rust.join("ceres-cli").is_dir() {
        fail!(
            "{} is not a Ceres source tree, expected rust/ceres-cli inside it.",
            source.display()
        );
    }

    output.warn(format!("Ceres Source (Development): {}", source.display()));

    // Handed to the replacement, whose own directory holds no interpreter to find. Left
    // to search again it would land on whatever `PATH` offers.
    let python = runtime::find_python()?;
    let binary = rust.join("target").join("debug").join("ceres");
    if !binary_is_current(&source, &rust, &binary) {
        let status = Command::new("cargo")
            .args(["build", "-q", "-p", "ceres-cli"])
            .current_dir(&rust)
            .status()
            .map_err(|error| {
                failure!("Failed to run cargo to build the development source. {error}")
            })?;
        if !status.success() {
            fail!("Building the development source CLI failed, see the cargo output above.");
        }
    }

    sync_environment(&python, &source)?;

    if !binary.is_file() {
        fail!("The built CLI is missing at {}.", binary.display());
    }

    let mut command = Command::new(&binary);
    command
        .args(&arguments)
        .env(DELEGATED, "1")
        .env(runtime::PYTHON, &python);

    runtime::replace(command)
}

/// Whether the built CLI is at least as new as every input under the checkout.
///
/// A current binary skips the cargo invocation, whose no-op freshness check costs an
/// order of magnitude more than this scan. The judgment is by file timestamps alone, so
/// a change arriving only through the environment, such as `RUSTFLAGS`, still needs the
/// binary deleted or a source touched. Any doubt falls back to cargo.
fn binary_is_current(source: &Path, rust: &Path, binary: &Path) -> bool {
    let Ok(built) = binary.metadata().and_then(|metadata| metadata.modified()) else {
        return false;
    };

    // The build directory configuration lives at the checkout root rather than under
    // `rust/`, and moving it relocates every artifact the scan is judging.
    let configuration = source.join(".cargo").join("config.toml");
    if configuration.is_file() && !older(&configuration, built) {
        return false;
    }

    tree_is_older(rust, built)
}

/// Whether everything under `directory` predates `built`, judged conservatively.
///
/// Directory timestamps count too, because a deletion or rename touches only its parent
/// directory. Build output and hidden entries are skipped, and anything unreadable reads
/// as newer.
fn tree_is_older(directory: &Path, built: std::time::SystemTime) -> bool {
    if !older(directory, built) {
        return false;
    }

    let Ok(entries) = std::fs::read_dir(directory) else {
        return false;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name == "target" || name.starts_with('.') {
            continue;
        }

        let path = entry.path();
        if path.is_dir() {
            if !tree_is_older(&path, built) {
                return false;
            }
        } else if !older(&path, built) {
            return false;
        }
    }

    true
}

/// Whether one path's modification time predates `built`.
fn older(path: &Path, built: std::time::SystemTime) -> bool {
    path.metadata()
        .and_then(|metadata| metadata.modified())
        .is_ok_and(|modified| modified < built)
}

/// Point the environment's `ceres-engine` at an editable install of the source.
///
/// An environment already tracking the source is left alone, so a delegated run only pays
/// for the install when the wiring is absent or points elsewhere.
fn sync_environment(python: &Path, source: &Path) -> Result<()> {
    // A bare system interpreter is never the right install target, so only an explicit
    // CERES_PYTHON skips the virtual environment check.
    let virtualenv = python
        .parent()
        .and_then(Path::parent)
        .is_some_and(|root| root.join("pyvenv.cfg").is_file());
    if !virtualenv && std::env::var_os(runtime::PYTHON).is_none() {
        fail!(
            "No virtual environment found to sync to the development source. Run from \
             the project's environment, or set CERES_PYTHON to its interpreter."
        );
    }

    if tracks_source(python, source) {
        return Ok(());
    }

    let status = installer(python, source, false)?
        .status()
        .map_err(|error| failure!("Failed to run the package installer. {error}"))?;
    if !status.success() {
        fail!("Installing the development source failed, see the installer output above.");
    }

    Ok(())
}

/// The installer command wiring the environment's `ceres-engine` to the source.
///
/// A reinstall forces the extension to rebuild even when the wiring already points at
/// the source, which is what a watch-mode Rust edit needs.
pub(crate) fn installer(python: &Path, source: &Path, reinstall: bool) -> Result<Command> {
    let mut command = if let Some(uv) = runtime::which("uv") {
        let mut command = Command::new(uv);
        command.args(["pip", "install", "--python"]).arg(python);
        if reinstall {
            command.args(["--reinstall-package", "ceres-engine"]);
        }

        command.arg("-e").arg(source);
        command
    } else {
        let mut command = Command::new(python);
        command.args(["-m", "pip", "install"]);
        if reinstall {
            command.args(["--force-reinstall", "--no-deps"]);
        }

        command.arg("-e").arg(source);
        command
    };

    // The PEP 517 backend builds optimized by default, which is the wrong trade for a
    // development loop, so an unset override defaults to the dev profile.
    if std::env::var_os("MATURIN_PEP517_ARGS").is_none() {
        command.env("MATURIN_PEP517_ARGS", "--profile dev");
    }

    Ok(command)
}

/// Whether the environment's `ceres-engine` is an editable install of the source.
fn tracks_source(python: &Path, source: &Path) -> bool {
    const PROBE: &str = "try:\n \
         from importlib.metadata import distribution\n \
         print(distribution('ceres-engine').read_text('direct_url.json') or '')\n\
         except Exception:\n pass";

    let Ok(output) = Command::new(python).arg("-c").arg(PROBE).output() else {
        return false;
    };
    let Ok(record) = serde_json::from_slice::<serde_json::Value>(&output.stdout) else {
        return false;
    };

    if record.pointer("/dir_info/editable") != Some(&serde_json::Value::Bool(true)) {
        return false;
    }

    // The URL is percent-encoded, so an exotic path re-installs harmlessly instead of
    // matching.
    let Some(path) = record
        .get("url")
        .and_then(|value| value.as_str())
        .and_then(|url| url.strip_prefix("file://"))
    else {
        return false;
    };

    Path::new(path).canonicalize().ok().as_deref() == Some(source)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn arguments(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    /// Backdate a tree's modification times, recursively.
    ///
    /// Filesystem timestamps are coarse enough that files written back to back can
    /// share one, and the scan treats a tie as stale, so freshness is staged
    /// explicitly rather than left to write order.
    fn backdate(path: &Path) {
        let past = std::time::SystemTime::now() - std::time::Duration::from_secs(60);
        std::fs::File::open(path)
            .unwrap()
            .set_modified(past)
            .unwrap();
        if path.is_dir() {
            for entry in std::fs::read_dir(path).unwrap().flatten() {
                backdate(&entry.path());
            }
        }
    }

    #[test]
    fn a_current_binary_skips_the_build_and_an_edit_forces_one() {
        let checkout = tempfile::tempdir().unwrap();
        let source = checkout.path();
        let rust = source.join("rust");
        let sources = rust.join("ceres-cli").join("src");
        std::fs::create_dir_all(&sources).unwrap();
        let main = sources.join("main.rs");
        std::fs::write(&main, "fn main() {}").unwrap();

        let debug = rust.join("target").join("debug");
        std::fs::create_dir_all(&debug).unwrap();
        let binary = debug.join("ceres");

        // No binary yet, so the build must run.
        assert!(!binary_is_current(source, &rust, &binary));

        std::fs::write(&binary, "built").unwrap();
        backdate(source);
        std::fs::write(&binary, "built").unwrap();
        assert!(binary_is_current(source, &rust, &binary));

        // An edit anywhere under the checkout makes the binary stale again, and so does
        // a deletion, which only its parent directory's timestamp records.
        std::fs::write(&main, "fn main() { }").unwrap();
        assert!(!binary_is_current(source, &rust, &binary));

        backdate(source);
        std::fs::write(&binary, "rebuilt").unwrap();
        assert!(binary_is_current(source, &rust, &binary));
        std::fs::remove_file(&main).unwrap();
        assert!(!binary_is_current(source, &rust, &binary));
    }

    #[test]
    fn a_source_reads_from_either_flag_form() {
        let split = arguments(&["run", "all", "--development-source", "../ceres"]);
        assert_eq!(source_from(&split), Some(PathBuf::from("../ceres")));

        let joined = arguments(&["--development-source=../ceres", "run"]);
        assert_eq!(source_from(&joined), Some(PathBuf::from("../ceres")));

        assert_eq!(source_from(&arguments(&["run", "all"])), None);
    }

    #[test]
    fn a_disabling_flag_beats_a_source_flag() {
        let both = arguments(&[
            "--development-source",
            "../ceres",
            "--no-development-source",
        ]);
        assert_eq!(resolve(&both), None);
    }

    // The environment-sensitive cases share one test, running sequentially, so the
    // variables never leak into a concurrent assertion.
    #[test]
    fn a_source_resolves_flags_over_the_environment() {
        assert_eq!(resolve(&arguments(&["run", "all"])), None);

        // SAFETY: no other test reads or writes the variables.
        unsafe { std::env::set_var(VARIABLE, "/environment") };
        let flagged = arguments(&["--development-source", "../flag", "run"]);
        assert_eq!(resolve(&flagged), Some(PathBuf::from("../flag")));
        assert_eq!(
            resolve(&arguments(&["run", "all"])),
            Some(PathBuf::from("/environment"))
        );

        // The disabling variable turns the standing source off, and a flag still wins.
        unsafe { std::env::set_var(NO_VARIABLE, "1") };
        assert_eq!(resolve(&arguments(&["run", "all"])), None);
        assert_eq!(resolve(&flagged), Some(PathBuf::from("../flag")));

        unsafe { std::env::remove_var(NO_VARIABLE) };
        unsafe { std::env::remove_var(VARIABLE) };
    }
}
