//! The Python runtime hosting the engine.
//!
//! Components are authored in Python, so every command that loads the engine or operates on
//! the database runs inside the Python runtime. The CLI hands those commands off by executing
//! `python -m ceres.__internal__.cli` with the original arguments, replacing the current
//! process so signals and exit codes flow through untouched. That module path goes straight
//! to the Python CLI, while `python -m ceres` execs this binary, so the handoff cannot loop.

use std::ffi::OsString;
use std::path::PathBuf;
use std::process::Command;

#[cfg(not(unix))]
use crate::error::Exit;
use crate::error::{Result, failure};

/// Replace the current process with the runtime running the given CLI arguments.
///
/// Only returns on failure. On platforms without `exec`, wait for the child and exit with
/// its status.
pub fn delegate(arguments: Vec<OsString>) -> Result<std::convert::Infallible> {
    let python = find_python()?;

    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("ceres.__internal__.cli")
        .args(&arguments);

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;

        let error = command.exec();
        Err(failure!("Failed to execute {}. {error}", python.display()))
    }

    #[cfg(not(unix))]
    {
        let status = command
            .status()
            .map_err(|error| failure!("Failed to execute {}. {error}", python.display()))?;

        Err(Exit::status(status.code().unwrap_or(1)))
    }
}

/// Locate the Python interpreter of the environment Ceres is installed in.
///
/// Search order:
///
/// 1. The `CERES_PYTHON` environment variable.
/// 2. A `python` executable next to this binary, which covers installs into a virtual
///    environment's `bin` directory.
/// 3. The active virtual environment's interpreter via `VIRTUAL_ENV`.
/// 4. `python3`, then `python`, on `PATH`.
fn find_python() -> Result<PathBuf> {
    if let Some(python) = std::env::var_os("CERES_PYTHON") {
        return Ok(PathBuf::from(python));
    }

    if let Ok(current) = std::env::current_exe()
        && let Ok(current) = current.canonicalize()
        && let Some(directory) = current.parent()
    {
        let sibling = directory.join("python");
        if sibling.is_file() {
            return Ok(sibling);
        }
    }

    if let Some(environment) = std::env::var_os("VIRTUAL_ENV") {
        let python = PathBuf::from(environment).join("bin").join("python");
        if python.is_file() {
            return Ok(python);
        }
    }

    for name in ["python3", "python"] {
        if let Some(python) = which(name) {
            return Ok(python);
        }
    }

    Err(failure!(
        "No Python interpreter found for the Ceres runtime. Set CERES_PYTHON to the \
         interpreter of the environment Ceres is installed in."
    ))
}

/// Find an executable by name on `PATH`.
fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for directory in std::env::split_paths(&path) {
        let candidate = directory.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    None
}
