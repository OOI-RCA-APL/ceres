//! The Ceres command line interface.

mod cli;
mod client;
mod commands;
mod error;
mod highlight;
mod output;
mod project;
mod runtime;
mod selector;
mod service;

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::{CommandFactory, FromArgMatches};

use crate::cli::{Cli, Command, ConsoleCommand, ServiceCommand};
use crate::client::Client;
use crate::commands::engine::Operation;
use crate::error::Result;
use crate::output::Output;
use crate::project::Project;

fn main() -> ExitCode {
    // Delegation replays the original arguments untouched, so capture them before parsing.
    let arguments: Vec<OsString> = std::env::args_os().skip(1).collect();
    let command = commands::surface::augment(Cli::command());
    let matches = command.get_matches();

    // A table group's whole surface is generated, so it is dispatched from the matches
    // directly. Everything else is declared and reads back into its own type.
    if let Some((name, verb)) = matches.subcommand()
        && let Some(table) = commands::surface::table(name)
    {
        let color = color_override(&matches);
        let output = Output::new(color);
        return report(table_command(table, &matches, color, verb), &output);
    }

    let cli = match Cli::from_arg_matches(&matches) {
        Ok(cli) => cli,
        Err(error) => error.exit(),
    };
    let output = Output::new(cli.color_override());
    report(run(cli, arguments, &output), &output)
}

/// Turn a command's outcome into the process's exit status, reporting as it goes.
fn report(outcome: Result<()>, output: &Output) -> ExitCode {
    match outcome {
        Ok(()) => ExitCode::SUCCESS,
        Err(exit) => {
            if let Some(message) = &exit.message {
                output.write(message);
            }

            ExitCode::from(exit.status.clamp(0, 255) as u8)
        }
    }
}

/// The color choice the global flags made, read off the matches the groups share.
fn color_override(matches: &clap::ArgMatches) -> Option<bool> {
    let flag = |id| matches.try_get_one::<bool>(id).ok().flatten().copied();
    match (flag("color"), flag("no_color")) {
        (Some(true), _) => Some(true),
        (_, Some(true)) => Some(false),
        _ => None,
    }
}

/// Run one verb of a table command group.
fn table_command(
    table: commands::surface::Table,
    matches: &clap::ArgMatches,
    color: Option<bool>,
    verb: &clap::ArgMatches,
) -> Result<()> {
    use commands::surface::Table;

    let config = matches
        .try_get_one::<std::path::PathBuf>("config")
        .ok()
        .flatten();
    let config = config.map(PathBuf::as_path);
    let (name, verb) = verb.subcommand().expect("a group requires its verb");
    let named = commands::dump::Verb::parse(name).expect("a declared verb");

    match table {
        Table::Record(table) => commands::records::run(table, config, color, named, verb),
        Table::Entity(table) => commands::entities::run(table, config, color, named, verb),
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
        Command::Run(_) | Command::Check(_) | Command::Database(_) | Command::Generate(_) => {
            match runtime::delegate(arguments)? {}
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
