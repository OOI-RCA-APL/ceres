//! The command line surface.
//!
//! Commands that talk to a running engine over its CLI server, manage services, or read only
//! the engine-level configuration are handled natively. Commands that load the engine or
//! operate on the database hand off to the Python runtime hosting the components.

use std::ffi::OsString;
use std::path::PathBuf;

use clap::{Args, Parser, Subcommand};

/// The Ceres package version, read from pyproject.toml at build time.
pub const VERSION: &str = env!("CERES_VERSION");

#[derive(Debug, Parser)]
#[command(
    name = "ceres",
    about = concat!("Ceres CLI Version ", env!("CERES_VERSION")),
    disable_version_flag = true
)]
pub struct Cli {
    /// Show the current Ceres version number and exit.
    #[arg(long)]
    pub version: bool,

    /// Use a specific Ceres configuration file, possibly outside the current working directory.
    #[arg(long, global = true, value_name = "PATH")]
    pub config: Option<PathBuf>,

    /// Enable colorized output.
    #[arg(long, global = true, overrides_with = "no_color")]
    pub color: bool,

    /// Disable colorized output.
    #[arg(long, global = true, overrides_with = "color")]
    pub no_color: bool,

    #[command(subcommand)]
    pub command: Option<Command>,
}

/// Arguments captured for a command that runs in the Python runtime.
///
/// The capture only exists so the command parses and appears in help. Delegation replays the
/// original process arguments untouched.
#[derive(Debug, Clone, Args)]
pub struct DelegatedArgs {
    #[arg(
        trailing_var_arg = true,
        allow_hyphen_values = true,
        hide = true,
        value_name = "ARGUMENTS"
    )]
    pub arguments: Vec<OsString>,
}

/// Define `Args` structs holding positional component address selectors.
macro_rules! address_args {
    ($($name:ident { $doc:literal, required: $required:literal })*) => {
        $(
            #[derive(Debug, Args)]
            pub struct $name {
                #[doc = $doc]
                #[arg(value_name = "ADDRESSES", required = $required)]
                pub addresses: Vec<String>,
            }
        )*
    };
}

address_args! {
    StatusArgs { "Addresses of components to show the status of.", required: false }
    StartArgs { "Addresses of components to start.", required: true }
    StopArgs { "Addresses of components to stop.", required: true }
    EnableArgs { "Addresses of components to enable.", required: true }
    DisableArgs { "Addresses of components to disable.", required: true }
    UpArgs { "Addresses of components to start and enable.", required: true }
    DownArgs { "Addresses of components to stop and disable.", required: true }
}

#[derive(Debug, Args)]
pub struct ConsoleArgs {
    #[command(subcommand)]
    pub command: ConsoleCommand,
}

#[derive(Debug, Args)]
pub struct ServiceArgs {
    #[command(subcommand)]
    pub command: ServiceCommand,
}

#[derive(Debug, Args)]
pub struct ServiceGenerateArgs {
    /// File path to write to. Standard output is used if not specified.
    #[arg(value_name = "PATH")]
    pub path: Option<PathBuf>,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Start the engine as a foreground process.
    #[command(disable_help_flag = true)]
    Run(DelegatedArgs),

    /// Validate project configuration (ceres.yaml) for errors.
    #[command(disable_help_flag = true)]
    Check(DelegatedArgs),

    /// Apply configuration changes.
    Reload,

    /// Show engine and component statuses.
    Status(StatusArgs),

    /// Start components at the provided addresses.
    Start(StartArgs),

    /// Stop components at the provided addresses.
    Stop(StopArgs),

    /// Enable components at the provided addresses.
    Enable(EnableArgs),

    /// Disable components at the provided addresses.
    Disable(DisableArgs),

    /// Start and enable components at the provided addresses.
    Up(UpArgs),

    /// Stop and disable components at the provided addresses.
    Down(DownArgs),

    /// Commands for interacting with a project's web console.
    Console(ConsoleArgs),

    /// Manage a user-level SystemD or LaunchD background service for this project.
    Service(ServiceArgs),

    /// Manage the project database.
    #[command(disable_help_flag = true)]
    Database(DelegatedArgs),

    /// Generate various project resources.
    #[command(disable_help_flag = true)]
    Generate(DelegatedArgs),
    // The table command groups are not declared here. Their whole surface is
    // generated from the entity definitions at startup, which is what keeps the flags a
    // table accepts and the filter keys its compiler serves from ever disagreeing.
}

#[derive(Debug, Subcommand)]
pub enum ConsoleCommand {
    /// Open the project's web console in a browser.
    Open,

    /// Write the project's web console URL to stdout.
    Url,
}

#[derive(Debug, Subcommand)]
pub enum ServiceCommand {
    /// Generate a service definition file for this project.
    Generate(ServiceGenerateArgs),

    /// Start the background service, creating and/or updating the service file as needed.
    Start,

    /// Stop the background service, deleting the service file afterwards.
    Stop,

    /// Show the status of the background service.
    Status,
}
