//! Dump the native command tree for the documentation's CLI reference page.
//!
//! This lives in the binary because half the tree is assembled at startup from the entity
//! definitions, and only a build of this crate can see the result. The dump is JSON rather
//! than the finished page, because two commands hand their arguments to the Python
//! runtime and only `scripts/update-reference.py` can describe those. It renders the page
//! from both halves and owns the comparison that fails when either drifts.

use std::path::PathBuf;

use clap::{Arg, ArgAction, Command};
use serde_json::{Value, json};

use crate::commands::surface;

/// Where the dump lands, for `scripts/update-reference.py` to read.
fn destination() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../target/reference/commands.json")
}

/// Collapse a help string onto one line.
fn flatten(help: Option<&clap::builder::StyledStr>) -> String {
    help.map(ToString::to_string)
        .unwrap_or_default()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// Describe one argument, in the terms someone typing it would use.
fn argument(argument: &Arg) -> Value {
    let takes_value = matches!(argument.get_action(), ArgAction::Set | ArgAction::Append);
    let values: Vec<String> = argument
        .get_value_names()
        .unwrap_or_default()
        .iter()
        .map(|value| value.as_str().to_string())
        .collect();

    json!({
        "long": argument.get_long(),
        "short": argument.get_short().map(|short| short.to_string()),
        "positional": argument.get_long().is_none() && argument.get_short().is_none(),
        "values": if takes_value || argument.is_positional() { values } else { Vec::new() },
        "required": argument.is_required_set(),
        "help": flatten(argument.get_help()),
    })
}

/// Describe one command and everything under it.
fn describe(command: &Command) -> Value {
    json!({
        "name": command.get_name(),
        "about": flatten(command.get_about()),
        "arguments": command
            .get_arguments()
            .filter(|found| !found.is_hide_set())
            .map(argument)
            .collect::<Vec<_>>(),
        "subcommands": command.get_subcommands().map(describe).collect::<Vec<_>>(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dump_the_command_tree_for_the_reference_page() {
        let path = destination();
        std::fs::create_dir_all(path.parent().expect("a parent directory"))
            .expect("creating the dump directory");
        let tree = describe(&surface::tree());
        let written = serde_json::to_string_pretty(&tree).expect("serializing the command tree");
        std::fs::write(&path, written + "\n").expect("writing the command tree");
    }
}
