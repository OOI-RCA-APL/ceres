//! The Ceres command line interface.

mod cli;
mod client;
mod commands;
mod development;
mod error;
mod highlight;
mod output;
mod project;
#[cfg(test)]
mod reference;
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

/// Rust allocations go through mimalloc, matching the extension module, so both
/// artifacts behave the same under allocation-heavy dumps and loads.
#[global_allocator]
static ALLOCATOR: mimalloc::MiMalloc = mimalloc::MiMalloc;

fn main() -> ExitCode {
    // Delegation replays the original arguments untouched, so capture them before parsing.
    let arguments: Vec<OsString> = std::env::args_os().skip(1).collect();

    // The project's .env applies to everything that follows, including the delegation
    // resolution below and every delegated child.
    project::load_env(cli::flag_value(&arguments, "--config").as_deref());

    // A development source takes over before any parsing, since the delegated commands'
    // trailing capture hides the flag from clap. The color flags are read off the raw
    // arguments the same way, with the same precedence as `color_override`.
    if let Some(source) = development::resolve(&arguments)
        && !development::delegated()
    {
        let output = Output::new(raw_color_override(&arguments));
        let outcome =
            development::delegate(&source, arguments, &output).map(|never| match never {});
        return report(outcome, &output);
    }

    // clap resolves color on its own, so the flags reach it here or its errors and help
    // ignore them.
    let command = commands::surface::augment(Cli::command());
    let command = match raw_color_override(&arguments) {
        Some(true) => command.color(clap::ColorChoice::Always),
        Some(false) => command.color(clap::ColorChoice::Never),
        None => command,
    };
    let matches = match command.try_get_matches() {
        Ok(matches) => matches,
        Err(error) => suggest_equals(error, &arguments).exit(),
    };

    // A table group's whole surface is generated, so it is dispatched from the matches
    // directly. Everything else is declared and reads back into its own type.
    if let Some((name, verb)) = matches.subcommand()
        && let Some(table) = commands::surface::Table::from_group(name)
    {
        let color = color_override(&matches);
        let output = Output::new(color);
        return report(table_command(table, &matches, color, verb), &output);
    }

    let cli = match Cli::from_arg_matches(&matches) {
        Ok(cli) => cli,
        Err(error) => error.exit(),
    };
    let output = Output::new(color_override(&matches));
    report(run(cli, arguments, &output), &output)
}

/// Add an equals-form tip to a missing-value error whose next token was a flag.
///
/// An option never swallows a flag-shaped token as its value, so `--contains --no-color`
/// fails, and the tip names the `--contains=--no-color` spelling that passes it through.
/// An unknown flag-shaped token in a value position gets the same tip beside clap's own,
/// since only the reader knows whether it was a typoed flag or a literal value.
fn suggest_equals(mut error: clap::Error, arguments: &[OsString]) -> clap::Error {
    use clap::error::{ContextKind, ContextValue, ErrorKind};

    let Some(ContextValue::String(invalid)) = error.get(ContextKind::InvalidArg) else {
        return error;
    };
    let invalid = invalid.clone();

    let tip = match error.kind() {
        ErrorKind::InvalidValue => invalid
            .split_whitespace()
            .next()
            .filter(|option| option.starts_with("--"))
            .and_then(|option| {
                let value = token_after(arguments, option)?;
                value
                    .starts_with('-')
                    .then(|| format!("to pass '{value}' as the value, write '{option}={value}'"))
            }),
        ErrorKind::UnknownArgument => value_taking_option_before(arguments, &invalid)
            .map(|option| format!("to pass '{invalid}' as the value, write '{option}={invalid}'")),
        _ => None,
    };

    if let Some(tip) = tip {
        let mut tips = match error.get(ContextKind::Suggested) {
            Some(ContextValue::StyledStrs(existing)) => existing.clone(),
            _ => Vec::new(),
        };
        tips.push(tip.into());
        error.insert(ContextKind::Suggested, ContextValue::StyledStrs(tips));
    }

    error
}

/// The raw token following the given one.
fn token_after<'a>(arguments: &'a [OsString], token: &str) -> Option<&'a str> {
    let index = arguments
        .iter()
        .position(|argument| argument.to_str() == Some(token))?;
    arguments.get(index + 1)?.to_str()
}

/// The long option directly before the given token, when that option takes a value.
///
/// Resolved against the real command tree, walking the subcommand path the arguments
/// name, so a boolean flag before the token never earns the tip.
fn value_taking_option_before(arguments: &[OsString], token: &str) -> Option<String> {
    let index = arguments
        .iter()
        .position(|argument| argument.to_str() == Some(token))?;
    let previous = arguments.get(index.checked_sub(1)?)?.to_str()?;
    if !previous.starts_with("--") || previous.contains('=') {
        return None;
    }

    let mut node = commands::surface::augment(Cli::command());
    for argument in &arguments[..index - 1] {
        let Some(name) = argument.to_str() else {
            continue;
        };

        if !name.starts_with('-')
            && let Some(subcommand) = node.find_subcommand(name)
        {
            node = subcommand.clone();
        }
    }

    let long = &previous[2..];
    let takes_value = node
        .get_arguments()
        .find(|argument| argument.get_long() == Some(long))
        .is_some_and(|argument| argument.get_action().takes_values());

    takes_value.then(|| previous.to_string())
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

/// The color choice the raw arguments made, read before clap has parsed anything.
fn raw_color_override(arguments: &[OsString]) -> Option<bool> {
    if arguments.iter().any(|argument| argument == "--color") {
        Some(true)
    } else if arguments.iter().any(|argument| argument == "--no-color") {
        Some(false)
    } else {
        None
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
        Table::Record(table) => commands::dump::run(table, config, color, named, verb),
        Table::Entity(table) => commands::dump::run(table, config, color, named, verb),
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
        // Run keeps the development-source flag for its console dev server, the others have
        // no Python-side parameter for it.
        Command::Run(_) => match runtime::delegate(development::normalize_run(arguments))? {},
        Command::Check(_) | Command::Database(_) | Command::Generate(_) => {
            match runtime::delegate(development::strip(&arguments))? {}
        }

        Command::Reload => {
            let project = Project::discover(config)?;
            commands::engine::reload(&project)
        }

        Command::Status(args) => {
            let project = Project::discover(config)?;

            // A stopped engine still has statuses, read from the configuration and the
            // database.
            match Client::connect_alive(&project) {
                Some(client) => {
                    commands::engine::status(&project, output, &client, &args.addresses)
                }
                None => commands::offline::status(&project, output, &args.addresses),
            }
        }

        Command::Start(args) => operate(config, output, Operation::Start, &args.addresses),
        Command::Stop(args) => operate(config, output, Operation::Stop, &args.addresses),
        Command::Enable(args) => toggle_enabled(config, output, &args.addresses, true),
        Command::Disable(args) => toggle_enabled(config, output, &args.addresses, false),
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

/// Toggle enablement through the engine, or straight in the database when none runs.
fn toggle_enabled(
    config: Option<&Path>,
    output: &Output,
    addresses: &[String],
    enabled: bool,
) -> Result<()> {
    let project = Project::discover(config)?;

    match Client::connect_alive(&project) {
        Some(_) => {
            let operation = if enabled {
                Operation::Enable
            } else {
                Operation::Disable
            };
            commands::engine::operate(&project, output, operation, addresses)
        }
        None => commands::offline::set_enabled(&project, output, addresses, enabled),
    }
}
