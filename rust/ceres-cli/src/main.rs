//! The Ceres command line interface.

mod cli;
mod client;
mod commands;
mod error;
mod output;
mod project;
mod runtime;
mod selector;
mod service;

use std::ffi::OsString;
use std::path::Path;
use std::process::ExitCode;

use ceres_database::RecordTable;
use clap::{CommandFactory, Parser};

use crate::cli::{Cli, Command, ConsoleCommand, ServiceCommand};
use crate::client::Client;
use crate::commands::engine::Operation;
use crate::error::Result;
use crate::output::Output;
use crate::project::Project;

fn main() -> ExitCode {
    // Delegation replays the original arguments untouched, so capture them before parsing.
    let arguments: Vec<OsString> = std::env::args_os().skip(1).collect();
    let cli = Cli::parse();
    let output = Output::new(cli.color_override());

    match run(cli, arguments, &output) {
        Ok(()) => ExitCode::SUCCESS,
        Err(exit) => {
            if let Some(message) = &exit.message {
                output.write(message);
            }

            ExitCode::from(exit.status.clamp(0, 255) as u8)
        }
    }
}

fn run(cli: Cli, arguments: Vec<OsString>, output: &Output) -> Result<()> {
    if cli.version {
        output.put(cli::VERSION);
        return Ok(());
    }

    let config = cli.config.clone();
    let config = config.as_deref();

    let Some(command) = cli.command else {
        let _ = Cli::command().print_help();
        return Err(error::Exit::status(2));
    };

    match command {
        // Commands that load the engine or operate on the database run in the Python runtime.
        Command::Run(_)
        | Command::Check(_)
        | Command::Database(_)
        | Command::Generate(_)
        | Command::Settings(_)
        | Command::Users(_)
        | Command::Variables(_)
        | Command::Workspaces(_) => match runtime::delegate(arguments)? {},

        // A plain JSON select or count over a record table runs natively, everything
        // else delegates to the Python runtime.
        Command::Messages(args) => {
            records_or_delegate(RecordTable::Messages, config, &args.arguments, arguments)
        }
        Command::Particles(args) => {
            records_or_delegate(RecordTable::Particles, config, &args.arguments, arguments)
        }
        Command::Alerts(args) => {
            records_or_delegate(RecordTable::Alerts, config, &args.arguments, arguments)
        }
        Command::Logs(args) => {
            records_or_delegate(RecordTable::Logs, config, &args.arguments, arguments)
        }

        Command::Reload => {
            let project = Project::discover(config)?;
            commands::engine::reload(&project)
        }

        Command::Status(args) => {
            let project = Project::discover(config)?;

            // A stopped engine still has statuses, resolved from the database by the runtime.
            match Client::connect_alive(&project) {
                Some(client) => {
                    commands::engine::status(&project, output, &client, &args.addresses)
                }
                None => {
                    commands::engine::parse_selectors(&args.addresses)?;
                    match runtime::delegate(arguments)? {}
                }
            }
        }

        Command::Start(args) => operate(config, output, Operation::Start, &args.addresses),
        Command::Stop(args) => operate(config, output, Operation::Stop, &args.addresses),
        Command::Enable(args) => hybrid_operate(
            config,
            output,
            arguments,
            Operation::Enable,
            &args.addresses,
        ),
        Command::Disable(args) => hybrid_operate(
            config,
            output,
            arguments,
            Operation::Disable,
            &args.addresses,
        ),
        Command::Up(args) => operate(config, output, Operation::Up, &args.addresses),
        Command::Down(args) => operate(config, output, Operation::Down, &args.addresses),

        Command::Console(args) => {
            let project = Project::discover(config)?;
            match args.command {
                ConsoleCommand::Open => commands::console::open(&project),
                ConsoleCommand::Url => commands::console::url(&project, output),
            }
        }

        Command::Service(args) => {
            let project = Project::discover(config)?;
            match args.command {
                ServiceCommand::Generate(generate) => {
                    commands::service::generate(&project, output, generate.path.as_deref())
                }
                ServiceCommand::Start => commands::service::start(&project, output),
                ServiceCommand::Stop => commands::service::stop(&project, output),
                ServiceCommand::Status => commands::service::status(&project, output),
            }
        }
    }
}

/// Serve a record command natively when it fits the native subset, or delegate.
fn records_or_delegate(
    table: RecordTable,
    config: Option<&Path>,
    raw: &[OsString],
    arguments: Vec<OsString>,
) -> Result<()> {
    if commands::records::try_run(table, config, raw)? {
        return Ok(());
    }

    match runtime::delegate(arguments)? {}
}

/// Run an engine operation that requires a running engine.
fn operate(
    config: Option<&Path>,
    output: &Output,
    operation: Operation,
    addresses: &[String],
) -> Result<()> {
    let project = Project::discover(config)?;
    commands::engine::operate(&project, output, operation, addresses)
}

/// Run an engine operation, falling back to the runtime when no engine is running.
fn hybrid_operate(
    config: Option<&Path>,
    output: &Output,
    arguments: Vec<OsString>,
    operation: Operation,
    addresses: &[String],
) -> Result<()> {
    debug_assert!(operation.has_offline_fallback());

    let project = Project::discover(config)?;

    match Client::connect_alive(&project) {
        Some(_) => commands::engine::operate(&project, output, operation, addresses),
        None => {
            commands::engine::parse_selectors(addresses)?;
            match runtime::delegate(arguments)? {}
        }
    }
}
