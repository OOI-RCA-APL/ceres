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

/// The value of a long flag, read from the raw arguments.
///
/// The delegated commands capture trailing arguments wholesale, which hides their flags
/// from clap, so the raw arguments are the one place every position of a flag is visible.
pub fn flag_value(arguments: &[OsString], flag: &str) -> Option<PathBuf> {
    let mut iterator = arguments.iter();
    while let Some(argument) = iterator.next() {
        if argument == flag {
            return iterator.next().map(PathBuf::from);
        }

        if let Some(value) = argument
            .to_str()
            .and_then(|text| text.strip_prefix(flag))
            .and_then(|text| text.strip_prefix('='))
        {
            return Some(PathBuf::from(value));
        }
    }

    None
}

#[derive(Debug, Parser)]
// The banner carries the header style's own codes so it matches the section headings.
// Help renders through anstream, which strips them whenever color is off.
#[command(
    name = "ceres",
    about = concat!("\x1b[1m\x1b[4mCeres:\x1b[0m ", env!("CERES_VERSION")),
    disable_version_flag = true
)]
pub struct Cli {
    /// Show the current Ceres version number and exit.
    #[arg(long)]
    pub version: bool,

    /// Use a specific Ceres configuration file, possibly outside the current working directory.
    #[arg(long, global = true, value_name = "PATH")]
    pub config: Option<PathBuf>,

    /// Run against a Ceres source checkout, building its CLI, pointing this environment at
    /// an editable install of it, and delegating the command to its binary. Defaults to the
    /// CERES_DEVELOPMENT_SOURCE environment variable. Development tooling, so hidden from
    /// help and documented on the Development page instead.
    #[arg(long, global = true, value_name = "PATH", hide = true)]
    pub development_source: Option<PathBuf>,

    /// Ignore any configured development source and run this installed Ceres. The
    /// CERES_NO_DEVELOPMENT_SOURCE environment variable does the same for a whole session.
    #[arg(
        long,
        global = true,
        overrides_with = "development_source",
        hide = true
    )]
    pub no_development_source: bool,

    /// Enable colorized output.
    #[arg(long, global = true, overrides_with = "no_color")]
    pub color: bool,

    /// Disable colorized output.
    #[arg(long, global = true, overrides_with = "color")]
    pub no_color: bool,

    #[command(subcommand)]
    pub command: Option<Command>,
}

/// Arguments the `run` command takes.
#[derive(Debug, Args)]
pub struct RunArgs {
    /// Addresses of components to run on startup.
    #[arg(value_name = "ADDRESSES")]
    pub addresses: Vec<String>,

    /// Automatically restart the engine on code changes.
    #[arg(long)]
    pub watch: bool,

    /// Serve the development console on this port instead of in place of the built-in
    /// one, so that both are available. Development tooling, so hidden from help and
    /// documented on the Development page instead.
    #[arg(long, value_name = "PORT", hide = true)]
    pub development_console_port: Option<u16>,
}

/// Define [`Args`] structs holding positional component address selectors.
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
    Run(RunArgs),

    /// Validate project configuration (ceres.yaml) for errors.
    Check,

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
    Database(DatabaseArgs),

    /// Generate various project resources.
    Generate(GenerateArgs),
    // The table command groups are not declared here. Their whole surface is
    // generated from the entity definitions at startup, which keeps the flags a
    // table accepts and the filter keys its compiler serves from ever disagreeing.
}

#[derive(Debug, Args)]
pub struct DatabaseArgs {
    #[command(subcommand)]
    pub command: DatabaseCommand,
}

#[derive(Debug, Subcommand)]
pub enum DatabaseCommand {
    /// Show DDL commands used to initialize the database.
    Ddl,

    /// Open an interactive database shell (psql or sqlite3) for the project database.
    Shell,

    /// Remove all data from the database. Tables and indexes are not removed, only truncated.
    Clear,

    /// Apply pending database migrations.
    Migrate(MigrateArgs),

    /// Show applied and pending database migrations.
    Migrations,
}

#[derive(Debug, Args)]
pub struct MigrateArgs {
    /// Apply without prompting for confirmation.
    #[arg(long)]
    pub yes: bool,
}

#[derive(Debug, Args)]
pub struct GenerateArgs {
    #[command(subcommand)]
    pub command: GenerateCommand,
}

#[derive(Debug, Subcommand)]
pub enum GenerateCommand {
    /// Generate up-to-date OpenAPI schema for the Ceres Rest API.
    Openapi(OpenapiArgs),
}

#[derive(Debug, Args)]
pub struct OpenapiArgs {
    /// File path to write to. Standard output is used if not specified.
    #[arg(long, value_name = "PATH")]
    pub output: Option<PathBuf>,

    /// Specify the output file format.
    #[arg(long, value_enum, default_value_t = SchemaFormat::Yaml)]
    pub format: SchemaFormat,

    /// Specify indentation size of output.
    #[arg(long, default_value_t = 2)]
    pub indent: u64,
}

/// Supported output formats for the OpenAPI schema.
#[derive(Clone, Copy, Debug, clap::ValueEnum)]
pub enum SchemaFormat {
    Yaml,
    Json,
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
