//! The directory in a project that holds what Ceres writes for itself.

use std::path::{Path, PathBuf};

/// Name of the directory in a project that holds what Ceres writes for itself.
pub const STATE_DIRECTORY: &str = ".ceres";

/// Create the `.ceres` directory in `project` if needed, returning its path.
///
/// It ignores itself through its own `.gitignore`, so nothing in it reaches version control
/// whatever the project's own ignore rules say. A `.gitignore` already there is left as it
/// is. The engine creates the directory the same way.
pub fn create_state_directory(project: &Path) -> std::io::Result<PathBuf> {
    let directory = project.join(STATE_DIRECTORY);
    std::fs::create_dir_all(&directory)?;

    let ignore = directory.join(".gitignore");
    if !ignore.exists() {
        std::fs::write(&ignore, "*\n")?;
    }

    Ok(directory)
}

/// Create the directory that will hold `file`, along with the `.ceres` directory's
/// `.gitignore` when `file` lies inside one.
pub fn create_parent_directory(file: &Path) -> std::io::Result<()> {
    if let Some(state) = file
        .ancestors()
        .skip(1)
        .find(|ancestor| ancestor.file_name() == Some(STATE_DIRECTORY.as_ref()))
    {
        create_state_directory(state.parent().unwrap_or(Path::new("")))?;
    }

    match file.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => std::fs::create_dir_all(parent),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_state_directory_ignores_itself() {
        let directory = tempfile::tempdir().unwrap();

        let created = create_state_directory(directory.path()).unwrap();
        assert_eq!(created, directory.path().join(".ceres"));
        let ignore = created.join(".gitignore");
        assert_eq!(std::fs::read_to_string(&ignore).unwrap(), "*\n");

        // A `.gitignore` the user edited is left alone.
        std::fs::write(&ignore, "*\n!keep\n").unwrap();
        create_state_directory(directory.path()).unwrap();
        assert_eq!(std::fs::read_to_string(&ignore).unwrap(), "*\n!keep\n");
    }

    #[test]
    fn parents_inside_the_state_directory_ignore_it() {
        let directory = tempfile::tempdir().unwrap();
        create_parent_directory(&directory.path().join(".ceres/tls/server.crt")).unwrap();
        assert!(directory.path().join(".ceres/tls").is_dir());
        assert_eq!(
            std::fs::read_to_string(directory.path().join(".ceres/.gitignore")).unwrap(),
            "*\n"
        );

        create_parent_directory(&directory.path().join("certs/site.crt")).unwrap();
        assert!(directory.path().join("certs").is_dir());
        assert!(!directory.path().join("certs/.gitignore").exists());
    }
}
