//! The Python runtime hosting the engine.
//!
//! Components are written in Python, so the commands that load the engine run inside the
//! Python runtime. The CLI hands them off by executing `python -m ceres.__internal__.host`
//! with a single JSON payload argument, either replacing the current process so signals
//! and exit codes flow through untouched, or spawning it as a child a resident parent
//! watches over.

use std::path::PathBuf;
use std::process::Command;

#[cfg(not(unix))]
use crate::error::Exit;
use crate::error::{Result, failure};

/// The command running the host module with the given JSON payload.
pub fn host(payload: &str) -> Result<Command> {
    let python = find_python()?;

    let mut command = Command::new(&python);
    command
        .arg("-m")
        .arg("ceres.__internal__.host")
        .arg(payload);

    Ok(command)
}

/// Replace the current process with the given command.
///
/// Only returns on failure. On platforms without `exec`, wait for the child and exit with
/// its status.
pub(crate) fn replace(mut command: Command) -> Result<std::convert::Infallible> {
    let name = PathBuf::from(command.get_program());

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;

        let error = command.exec();
        Err(failure!("Failed to execute {}. {error}", name.display()))
    }

    #[cfg(not(unix))]
    {
        let status = command
            .status()
            .map_err(|error| failure!("Failed to execute {}. {error}", name.display()))?;

        Err(Exit::status(status.code().unwrap_or(1)))
    }
}

/// Locate the Python interpreter of the environment Ceres is installed in.
///
/// Search order:
///
/// 1. The `CERES_PYTHON` environment variable.
/// 2. A `python` executable next to the path this binary was invoked as, which covers
///    installs into a virtual environment's `bin` directory, including a symlinked
///    development binary that `current_exe` would resolve out of the environment.
/// 3. A `python` executable next to this binary's resolved path.
/// 4. The active virtual environment's interpreter via `VIRTUAL_ENV`.
/// 5. `python3`, then `python`, on `PATH`.
pub(crate) fn find_python() -> Result<PathBuf> {
    if let Some(python) = std::env::var_os("CERES_PYTHON") {
        return Ok(PathBuf::from(python));
    }

    let candidates = [
        invoked_executable(),
        std::env::current_exe()
            .and_then(|path| path.canonicalize())
            .ok(),
    ];
    for candidate in candidates.into_iter().flatten() {
        if let Some(directory) = candidate.parent() {
            let sibling = directory.join("python");
            if sibling.is_file() {
                return Ok(sibling);
            }
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

/// The absolute path this binary was invoked as, from its own argument zero.
///
/// Unlike `current_exe`, this keeps a symlink's own location, which is what places a
/// development binary inside the virtual environment that links it.
pub fn invoked_executable() -> Option<PathBuf> {
    let argument = PathBuf::from(std::env::args_os().next()?);
    let path = if argument.components().count() > 1 {
        std::env::current_dir().ok()?.join(argument)
    } else {
        which(argument.to_str()?)?
    };

    path.is_file().then_some(path)
}

/// Find an executable by name on `PATH`.
pub(crate) fn which(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for directory in std::env::split_paths(&path) {
        let candidate = directory.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    None
}
