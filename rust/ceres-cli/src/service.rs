//! Background service management.
//!
//! Runs the project's engine as a user-level service, through systemd on Linux and launchd on
//! macOS. The service definition executes this binary's `run` command from the project
//! directory.

use std::path::{Path, PathBuf};
use std::process::Command;

use ceres_config::ServiceConfig;

use crate::error::{Result, failure};
use crate::output::Output;
use crate::project::Project;

/// The current running state of a service.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServiceState {
    Running,
    Stopped,
}

impl ServiceState {
    pub fn title(&self) -> &'static str {
        match self {
            Self::Running => "Running",
            Self::Stopped => "Stopped",
        }
    }
}

/// A platform service manager for one project.
pub trait Service {
    /// The current running state of the service.
    fn state(&self) -> ServiceState;

    /// The filesystem path of the service definition file.
    fn location(&self) -> PathBuf;

    /// Generate the service definition file contents.
    fn generate(&self) -> Result<Vec<u8>>;

    /// Start the service, creating the definition file as needed.
    fn start(&self) -> Result<()>;

    /// Stop the service and remove its definition file.
    fn stop(&self) -> Result<()>;

    /// The service name registered with the operating system.
    fn name(&self) -> String;

    /// The user the service runs as.
    fn user(&self) -> String;
}

/// Shared naming and path resolution for the platform implementations.
pub struct ServiceContext {
    project: Project,
    config: ServiceConfig,
    output: Output,
}

impl ServiceContext {
    pub fn new(project: Project, config: ServiceConfig, output: Output) -> Self {
        Self {
            project,
            config,
            output,
        }
    }

    /// The service name, falling back to a hash-based name.
    fn name(&self) -> String {
        self.config
            .name
            .as_ref()
            .map(ToString::to_string)
            .unwrap_or_else(|| format!("ceres-{}", self.project.directory_hash()))
    }

    /// The user the service runs as, defaulting to the current user.
    fn user(&self) -> String {
        self.config
            .user
            .as_ref()
            .map(ToString::to_string)
            .unwrap_or_else(current_user)
    }

    /// The absolute path standard output is appended to, when configured.
    fn stdout(&self) -> Option<PathBuf> {
        self.resolve(self.config.stdout.as_deref())
    }

    /// The absolute path standard error is appended to, when configured.
    fn stderr(&self) -> Option<PathBuf> {
        self.resolve(self.config.stderr.as_deref())
    }

    fn resolve(&self, path: Option<&Path>) -> Option<PathBuf> {
        let path = path?;
        if path.is_absolute() {
            return Some(path.to_path_buf());
        }

        Some(self.project.directory().join(path))
    }

    /// The command line the service executes, this binary's `run` command.
    fn command(&self) -> Result<Vec<String>> {
        let current = std::env::current_exe()
            .and_then(|path| path.canonicalize())
            .map_err(|error| failure!("Failed to resolve the CLI path. {error}"))?;

        Ok(vec![
            current.to_string_lossy().into_owned(),
            "run".to_string(),
        ])
    }

    fn log(&self, message: impl AsRef<str>) {
        self.output.write(message);
    }
}

/// Build the platform service manager from the project configuration.
pub fn service_for(project: &Project, output: &Output) -> Result<Box<dyn Service>> {
    let meta = project.load_meta()?;
    let context = ServiceContext::new(project.clone(), meta.service, *output);

    if cfg!(target_os = "linux") {
        return Ok(Box::new(SystemDService { context }));
    }

    if cfg!(target_os = "macos") {
        return Ok(Box::new(LaunchDService { context }));
    }

    Err(failure!(
        "Services are not supported on this platform: {}.",
        std::env::consts::OS
    ))
}

/// Return the current user name from the environment.
fn current_user() -> String {
    std::env::var("USER")
        .or_else(|_| std::env::var("LOGNAME"))
        .unwrap_or_else(|_| "unknown".to_string())
}

/// Run a command silently and return its exit status code.
fn execute(program: &str, arguments: &[&str]) -> Result<i32> {
    let result = Command::new(program)
        .args(arguments)
        .output()
        .map_err(|error| failure!("Failed to execute {program}. {error}"))?;

    Ok(result.status.code().unwrap_or(1))
}

/// Write a definition file when its contents changed, returning whether a write happened.
fn write_if_changed(path: &Path, data: &[u8]) -> Result<bool> {
    let current = std::fs::read(path).ok();
    if current.as_deref() == Some(data) {
        return Ok(false);
    }

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|error| failure!("Failed to create {}. {error}", parent.display()))?;
    }

    std::fs::write(path, data)
        .map_err(|error| failure!("Failed to write {}. {error}", path.display()))?;
    Ok(true)
}

/// Remove a definition file when it exists.
fn remove_if_exists(path: &Path) -> Result<()> {
    if path.exists() {
        std::fs::remove_file(path)
            .map_err(|error| failure!("Failed to remove {}. {error}", path.display()))?;
    }

    Ok(())
}

/// Service manager for Linux systems using systemd user units.
pub struct SystemDService {
    context: ServiceContext,
}

impl SystemDService {
    /// The systemd unit name, including the `.service` suffix.
    fn label(&self) -> String {
        format!("{}.service", self.context.name())
    }

    /// The path of the unit file under `~/.config/systemd/user/`.
    fn path(&self) -> PathBuf {
        home_directory()
            .join(".config/systemd/user")
            .join(self.label())
    }

    fn systemctl(&self, arguments: &[&str]) -> Result<i32> {
        execute("systemctl", arguments)
    }

    /// Enable `loginctl` linger so the service persists after logout.
    fn enable_linger(&self) {
        let user = self.context.user();
        self.context
            .log(format!("Enabling loginctl linger for user '{user}'..."));

        if execute("loginctl", &["enable-linger", &user]).unwrap_or(1) != 0 {
            self.context.log(format!(
                "WARNING: Failed to enable loginctl linger. Execute 'loginctl enable-linger \
                 {user}' to persist the service after logout."
            ));
        }
    }

    /// Create or update the unit file and register the service.
    fn create(&self) -> Result<()> {
        if write_if_changed(&self.path(), &self.generate()?)? {
            self.systemctl(&["daemon-reload", "--user"])?;
        }

        self.systemctl(&["enable", "--user", &self.label()])?;
        Ok(())
    }

    /// Remove the unit file.
    fn delete(&self) -> Result<()> {
        remove_if_exists(&self.path())
    }
}

impl Service for SystemDService {
    fn state(&self) -> ServiceState {
        match self.systemctl(&["is-active", "--user", &self.label()]) {
            Ok(0) => ServiceState::Running,
            _ => ServiceState::Stopped,
        }
    }

    fn location(&self) -> PathBuf {
        self.path()
    }

    fn generate(&self) -> Result<Vec<u8>> {
        let command = self.context.command()?.join(" ");
        let mut unit = format!(
            "[Unit]\nDescription=\"{}\"\n\n[Service]\nExecStart={}\nWorkingDirectory={}\n\
             Restart=always\n",
            self.label(),
            command,
            self.context.project.directory().display(),
        );

        if let Some(stdout) = self.context.stdout() {
            unit.push_str(&format!("StandardOutput=append:{}\n", stdout.display()));
        }

        if let Some(stderr) = self.context.stderr() {
            unit.push_str(&format!("StandardError=append:{}\n", stderr.display()));
        }

        unit.push_str("\n[Install]\nWantedBy=default.target\n");
        Ok(unit.into_bytes())
    }

    fn start(&self) -> Result<()> {
        if self.state() == ServiceState::Running {
            return Ok(());
        }

        self.create()?;
        self.systemctl(&["daemon-reload", "--user"])?;
        self.systemctl(&["start", "--user", &self.label()])?;
        self.systemctl(&["enable", "--user", &self.label()])?;
        self.enable_linger();
        Ok(())
    }

    fn stop(&self) -> Result<()> {
        if self.state() == ServiceState::Stopped {
            return Ok(());
        }

        self.systemctl(&["stop", "--user", &self.label()])?;
        self.systemctl(&["disable", "--user", &self.label()])?;
        self.delete()
    }

    fn name(&self) -> String {
        self.context.name()
    }

    fn user(&self) -> String {
        self.context.user()
    }
}

/// Service manager for macOS systems using launchd user agents.
pub struct LaunchDService {
    context: ServiceContext,
}

impl LaunchDService {
    /// The launchd job label.
    fn label(&self) -> String {
        self.context.name()
    }

    /// The path of the plist file under `~/Library/LaunchAgents/`.
    fn path(&self) -> PathBuf {
        home_directory()
            .join("Library/LaunchAgents")
            .join(format!("{}.plist", self.label()))
    }

    /// The launchd target specifier for this user-level service.
    fn target(&self) -> String {
        format!("user/{}/{}", user_id(), self.label())
    }

    fn launchctl(&self, arguments: &[&str]) -> Result<i32> {
        execute("launchctl", arguments)
    }

    /// Build the plist definition for the launchd agent.
    fn plist(&self) -> Result<plist::Dictionary> {
        let command = self.context.command()?;

        let mut data = plist::Dictionary::new();
        data.insert("Label".to_string(), self.label().into());
        data.insert("UserName".to_string(), self.context.user().into());
        data.insert(
            "ProgramArguments".to_string(),
            plist::Value::Array(command.into_iter().map(plist::Value::from).collect()),
        );
        data.insert(
            "WorkingDirectory".to_string(),
            self.context
                .project
                .directory()
                .to_string_lossy()
                .into_owned()
                .into(),
        );
        data.insert("RunAtLoad".to_string(), true.into());

        if let Some(stdout) = self.context.stdout() {
            data.insert(
                "StandardOutPath".to_string(),
                stdout.to_string_lossy().into_owned().into(),
            );
        }

        if let Some(stderr) = self.context.stderr() {
            data.insert(
                "StandardErrorPath".to_string(),
                stderr.to_string_lossy().into_owned().into(),
            );
        }

        Ok(data)
    }

    /// Create or update the plist file and register the service.
    fn create(&self) -> Result<()> {
        write_if_changed(&self.path(), &self.generate()?)?;
        self.launchctl(&["enable", &self.target()])?;
        Ok(())
    }

    /// Remove the plist file.
    fn delete(&self) -> Result<()> {
        remove_if_exists(&self.path())
    }
}

impl Service for LaunchDService {
    fn state(&self) -> ServiceState {
        if !self.path().exists() {
            return ServiceState::Stopped;
        }

        match self.launchctl(&["list", &self.label()]) {
            Ok(0) => ServiceState::Running,
            _ => ServiceState::Stopped,
        }
    }

    fn location(&self) -> PathBuf {
        self.path()
    }

    fn generate(&self) -> Result<Vec<u8>> {
        let mut buffer = Vec::new();
        plist::Value::Dictionary(self.plist()?)
            .to_writer_xml(&mut buffer)
            .map_err(|error| failure!("Failed to serialize the plist. {error}"))?;

        Ok(buffer)
    }

    fn start(&self) -> Result<()> {
        if self.state() == ServiceState::Running {
            return Ok(());
        }

        self.create()?;

        let path = self.path().to_string_lossy().into_owned();
        self.launchctl(&["load", "-w", &path])?;
        self.launchctl(&["enable", &self.target()])?;
        let _ = self.launchctl(&["start", &self.target()]);
        Ok(())
    }

    fn stop(&self) -> Result<()> {
        if self.state() == ServiceState::Stopped {
            return Ok(());
        }

        let path = self.path().to_string_lossy().into_owned();
        self.launchctl(&["unload", "-w", &path])?;
        self.delete()
    }

    fn name(&self) -> String {
        self.context.name()
    }

    fn user(&self) -> String {
        self.context.user()
    }
}

/// Return the current user's home directory.
fn home_directory() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/"))
}

/// Return the current numeric user ID.
#[cfg(unix)]
fn user_id() -> u32 {
    // SAFETY: getuid has no preconditions and cannot fail.
    unsafe { libc::getuid() }
}

#[cfg(not(unix))]
fn user_id() -> u32 {
    0
}

#[cfg(test)]
mod tests {
    use ceres_config::Name;

    use super::*;

    fn name(text: &str) -> Option<Name> {
        Some(Name::parse(text).unwrap())
    }

    fn context(config: ServiceConfig) -> ServiceContext {
        ServiceContext::new(
            Project::at("/opt/project/ceres.yaml"),
            config,
            Output::new(Some(false)),
        )
    }

    #[test]
    fn systemd_units_keep_output_settings_in_the_service_section() {
        let config = ServiceConfig {
            name: name("probe"),
            stdout: Some(PathBuf::from("logs/out.log")),
            stderr: Some(PathBuf::from("/var/log/err.log")),
            ..ServiceConfig::default()
        };
        let service = SystemDService {
            context: context(config),
        };

        let unit = String::from_utf8(service.generate().unwrap()).unwrap();
        let service_section = unit
            .split("\n[Install]")
            .next()
            .expect("the unit has an install section");

        // Relative output paths resolve against the project directory, and both settings land
        // in [Service] rather than trailing the unit.
        assert!(service_section.contains("StandardOutput=append:/opt/project/logs/out.log"));
        assert!(service_section.contains("StandardError=append:/var/log/err.log"));
        assert!(unit.contains("WorkingDirectory=/opt/project"));
        assert!(unit.ends_with("[Install]\nWantedBy=default.target\n"));
    }

    #[test]
    fn launchd_plists_describe_the_run_command() {
        let config = ServiceConfig {
            name: name("probe"),
            user: name("worker"),
            ..ServiceConfig::default()
        };
        let service = LaunchDService {
            context: context(config),
        };

        let plist = String::from_utf8(service.generate().unwrap()).unwrap();
        assert!(plist.contains("<key>Label</key>"));
        assert!(plist.contains("<string>probe</string>"));
        assert!(plist.contains("<string>worker</string>"));
        assert!(plist.contains("<string>run</string>"));
        assert!(plist.contains("<string>/opt/project</string>"));
    }

    #[test]
    fn service_names_fall_back_to_the_directory_hash() {
        let service = SystemDService {
            context: context(ServiceConfig::default()),
        };
        assert_eq!(service.name(), "ceres-8d1253");
        assert_eq!(service.label(), "ceres-8d1253.service");
    }
}
