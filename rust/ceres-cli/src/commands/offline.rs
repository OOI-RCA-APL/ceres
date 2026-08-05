//! Engine operations served from the database while nothing is running.
//!
//! Enabling and disabling flip a component's enablement variable, and a stopped
//! engine's status reads the configuration's component tree beside those variables, so
//! all three commands answer without starting a runtime.

use std::collections::HashSet;
use std::path::Path;

use ceres_database::{EntityFilter, EntityTable, RecordStore};
use ceres_entities::Entities;

use crate::commands::dump::open_store;
use crate::commands::engine::{Status, parse_selectors, write_status};
use crate::error::{Exit, Result};
use crate::output::Output;
use crate::project::Project;

/// The variables row naming whether a component starts with the engine.
///
/// Written by the engine's own enable and disable handlers, lazily, so a component that
/// was never toggled has no row and reads as disabled.
const ENABLED_VARIABLE: &str = "__enabled__";

/// Toggle enablement for the components matching `addresses`, straight in the database.
///
/// Only rows holding the opposite state flip, so the reported list names exactly the
/// components whose state changed, the way the engine's own handler reports them. A
/// component that has never been toggled has no row and stays untouched, since creating
/// enablement is the engine's job on load.
pub fn set_enabled(
    project: &Project,
    output: &Output,
    addresses: &[String],
    enabled: bool,
) -> Result<()> {
    parse_selectors(addresses)?;

    // Each address folds into the filter's selector, exactly as repeated --address
    // flags would, and the value condition keeps already-correct rows out of the write.
    let mut pairs: Vec<(String, String)> = addresses
        .iter()
        .map(|address| ("address".to_string(), address.clone()))
        .collect();
    pairs.push(("name".to_string(), ENABLED_VARIABLE.to_string()));
    pairs.push(("value".to_string(), (!enabled).to_string()));
    let filter = EntityFilter::parse(EntityTable::Variables, &pairs)
        .map_err(|_| Exit::failed("The addresses do not form a valid selector."))?;

    let meta = project.load_meta()?;
    let (runtime, store) = open(&meta.database, project.directory(), true)?;

    let assign = format!("{{\"value\": {enabled}}}");
    let written = runtime
        .block_on(store.update_entity_filter_returning(&filter, &assign, None))
        .map_err(|error| Exit::failed(error.to_string()))?;
    let Entities::Variables(variables) = written else {
        unreachable!("a variables filter returns variables");
    };

    let mut affected: Vec<&str> = variables
        .iter()
        .map(|variable| variable.address.as_str())
        .collect();
    affected.sort_unstable();

    let key = if enabled { "enabled" } else { "disabled" };
    output.put(serde_json::json!({ key: affected }).to_string());
    Ok(())
}

/// Show engine and component statuses for a stopped engine.
///
/// The components come from the configuration's own tree and their enablement from the
/// database, with nothing running. A database that cannot be reached lists no
/// components rather than failing, because the engine's state is the answer and an
/// unreachable database holds none.
pub fn status(project: &Project, output: &Output, addresses: &[String]) -> Result<()> {
    parse_selectors(addresses)?;

    let meta = project.load_meta()?;
    let components = component_addresses(project.config_path())?;

    let statuses = match read_enabled(&meta.database, project.directory()) {
        Ok(enabled) => components
            .into_iter()
            .map(|address| Status {
                enabled: Some(enabled.contains(&address)),
                address,
                running: false,
            })
            .collect(),
        Err(_) => Vec::new(),
    };

    write_status(project, output, false, &statuses)
}

/// Every component address the configuration declares, parents before children.
///
/// This walks the raw tree rather than loading the configuration, because listing
/// addresses needs only the names, and a project whose component classes will not
/// import still has a status.
fn component_addresses(config_path: &Path) -> Result<Vec<String>> {
    let text = std::fs::read_to_string(config_path)
        .map_err(|error| Exit::failed(format!("Cannot read the configuration. {error}")))?;
    let root: serde_yaml_ng::Value = serde_yaml_ng::from_str(&text)
        .map_err(|error| Exit::failed(format!("Cannot parse the configuration. {error}")))?;

    fn walk(components: Option<&serde_yaml_ng::Value>, parent: &str, addresses: &mut Vec<String>) {
        let Some(serde_yaml_ng::Value::Sequence(entries)) = components else {
            return;
        };

        for entry in entries {
            let Some(name) = entry.get("name").and_then(serde_yaml_ng::Value::as_str) else {
                continue;
            };

            let address = if parent.is_empty() {
                format!("@{name}")
            } else {
                format!("{parent}.{name}")
            };
            addresses.push(address.clone());
            walk(entry.get("components"), &address, addresses);
        }
    }

    let mut addresses = Vec::new();
    walk(root.get("components"), "", &mut addresses);
    Ok(addresses)
}

/// The addresses whose enablement variable is stored true.
fn read_enabled(
    config: &ceres_config::DatabaseConfig,
    directory: &Path,
) -> std::result::Result<HashSet<String>, String> {
    let pairs = [
        ("name".to_string(), ENABLED_VARIABLE.to_string()),
        ("value".to_string(), "true".to_string()),
    ];
    let filter = EntityFilter::parse(EntityTable::Variables, &pairs)
        .expect("the enablement filter always parses");

    let (runtime, store) = open(config, directory, false).map_err(|exit| {
        exit.message
            .unwrap_or_else(|| "the database did not open".to_string())
    })?;

    let mut enabled = HashSet::new();
    runtime
        .block_on(store.stream_entity_filter(&filter, &mut |entities| {
            if let Entities::Variables(variables) = entities {
                enabled.extend(
                    variables
                        .into_iter()
                        .map(|variable| variable.address.as_str().to_string()),
                );
            }

            Ok(())
        }))
        .map_err(|error| error.to_string())?;
    Ok(enabled)
}

/// Open the project's store on a runtime of its own.
fn open(
    config: &ceres_config::DatabaseConfig,
    directory: &Path,
    writing: bool,
) -> Result<(tokio::runtime::Runtime, RecordStore)> {
    // Pool construction spawns maintenance tasks, so the runtime has to exist first.
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("the runtime always builds");
    let guard = runtime.enter();
    let store = open_store(config, directory, writing).map_err(Exit::failed)?;
    drop(guard);
    Ok((runtime, store))
}
