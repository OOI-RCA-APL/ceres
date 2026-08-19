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
use crate::runtime;

/// The flag spelling, shared by the scanner and the stripper.
const FLAG: &str = "--development-source";

/// The environment variable providing a standing development source.
const VARIABLE: &str = "CERES_DEVELOPMENT_SOURCE";

/// Marks a process the delegation already replaced, stopping a second hop.
const DELEGATED: &str = "CERES_DEVELOPMENT_SOURCE_DELEGATED";

/// The development source in effect, the flag overriding the environment variable.
pub fn resolve(arguments: &[OsString]) -> Option<PathBuf> {
    source_from(arguments).or_else(|| {
        std::env::var_os(VARIABLE)
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
    })
}

/// The `--development-source` value, read from the raw arguments.
pub fn source_from(arguments: &[OsString]) -> Option<PathBuf> {
    crate::cli::flag_value(arguments, FLAG)
}

/// Whether the current process was already delegated to the development source.
pub fn delegated() -> bool {
    std::env::var_os(DELEGATED).is_some()
}

/// Remove every `--development-source` flag and value from the arguments.
pub fn strip(arguments: &[OsString]) -> Vec<OsString> {
    let mut result = Vec::with_capacity(arguments.len());
    let mut iterator = arguments.iter();
    while let Some(argument) = iterator.next() {
        if argument == FLAG {
            iterator.next();
            continue;
        }

        if let Some(text) = argument.to_str()
            && text.starts_with(FLAG)
            && text[FLAG.len()..].starts_with('=')
        {
            continue;
        }

        result.push(argument.clone());
    }

    result
}

/// Rewrite the run arguments to carry the resolved development source at the end.
///
/// The Python `run` command consumes the flag for its console dev server but only parses
/// it after the subcommand, so a flag given before `run`, or one implied by the
/// environment variable, is placed there.
pub fn normalize_run(arguments: Vec<OsString>) -> Vec<OsString> {
    let Some(source) = resolve(&arguments) else {
        return arguments;
    };

    let mut result = strip(&arguments);
    result.push(FLAG.into());
    result.push(source.into());
    result
}

/// Build the checkout's CLI, wire the environment to it, and replace this process.
///
/// Only returns on failure. Each step announces itself on stderr so a delegated run says
/// what it is doing.
pub fn delegate(source: &Path, arguments: Vec<OsString>) -> Result<Infallible> {
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

    eprintln!("Building the Ceres CLI in {}.", rust.display());
    let status = Command::new("cargo")
        .args(["build", "-p", "ceres-cli"])
        .current_dir(&rust)
        .status()
        .map_err(|error| {
            failure!("Failed to run cargo to build the development source. {error}")
        })?;
    if !status.success() {
        fail!("Building the development source CLI failed, see the cargo output above.");
    }

    sync_environment(&source)?;

    let binary = rust.join("target").join("debug").join("ceres");
    if !binary.is_file() {
        fail!("The built CLI is missing at {}.", binary.display());
    }

    eprintln!("Delegating to {}.", binary.display());
    let mut command = Command::new(&binary);
    command.args(&arguments).env(DELEGATED, "1");
    runtime::replace(command)
}

/// Point the environment's `ceres-engine` at an editable install of the source.
///
/// An environment already tracking the source is left alone, so a delegated run only pays
/// for the install when the wiring is absent or points elsewhere.
fn sync_environment(source: &Path) -> Result<()> {
    let python = runtime::find_python()?;

    // A bare system interpreter is never the right install target, so only an explicit
    // CERES_PYTHON skips the virtual environment check.
    let virtualenv = python
        .parent()
        .and_then(Path::parent)
        .is_some_and(|root| root.join("pyvenv.cfg").is_file());
    if !virtualenv && std::env::var_os("CERES_PYTHON").is_none() {
        fail!(
            "No virtual environment found to sync to the development source. Run from \
             the project's environment, or set CERES_PYTHON to its interpreter."
        );
    }

    if tracks_source(&python, source) {
        return Ok(());
    }

    eprintln!(
        "Installing {} into the environment as an editable package.",
        source.display()
    );
    let mut command = if let Some(uv) = runtime::which("uv") {
        let mut command = Command::new(uv);
        command
            .args(["pip", "install", "--python"])
            .arg(&python)
            .arg("-e")
            .arg(source);
        command
    } else {
        let mut command = Command::new(&python);
        command.args(["-m", "pip", "install", "-e"]).arg(source);
        command
    };

    // The PEP 517 backend builds optimized by default, which is the wrong trade for a
    // development loop, so an unset override defaults to the dev profile.
    if std::env::var_os("MATURIN_PEP517_ARGS").is_none() {
        command.env("MATURIN_PEP517_ARGS", "--profile dev");
    }

    let status = command
        .status()
        .map_err(|error| failure!("Failed to run the package installer. {error}"))?;
    if !status.success() {
        fail!("Installing the development source failed, see the installer output above.");
    }

    Ok(())
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

    #[test]
    fn a_source_reads_from_either_flag_form() {
        let split = arguments(&["run", "all", "--development-source", "../ceres"]);
        assert_eq!(source_from(&split), Some(PathBuf::from("../ceres")));

        let joined = arguments(&["--development-source=../ceres", "run"]);
        assert_eq!(source_from(&joined), Some(PathBuf::from("../ceres")));

        assert_eq!(source_from(&arguments(&["run", "all"])), None);
    }

    #[test]
    fn a_strip_removes_both_flag_forms() {
        let split = arguments(&["database", "migrate", "--development-source", "../ceres"]);
        assert_eq!(strip(&split), arguments(&["database", "migrate"]));

        let joined = arguments(&["--development-source=../ceres", "check"]);
        assert_eq!(strip(&joined), arguments(&["check"]));
    }

    #[test]
    fn a_run_normalization_moves_the_flag_to_the_end() {
        let leading = arguments(&["--development-source", "../ceres", "run", "all"]);
        assert_eq!(
            normalize_run(leading),
            arguments(&["run", "all", "--development-source", "../ceres"])
        );
    }

    // The environment-sensitive cases share one test, running sequentially, so the
    // variable never leaks into a concurrent assertion.
    #[test]
    fn a_source_resolves_the_flag_over_the_environment() {
        let absent = arguments(&["run", "all"]);
        assert_eq!(normalize_run(absent.clone()), absent);

        // SAFETY: no other test reads or writes the variable.
        unsafe { std::env::set_var(VARIABLE, "/environment") };
        let flagged = arguments(&["--development-source", "../flag", "run"]);
        assert_eq!(resolve(&flagged), Some(PathBuf::from("../flag")));
        assert_eq!(
            normalize_run(arguments(&["run", "all"])),
            arguments(&["run", "all", "--development-source", "/environment"])
        );
        unsafe { std::env::remove_var(VARIABLE) };
    }
}
