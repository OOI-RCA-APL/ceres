//! Commands that operate a running engine over its CLI server.

use serde::Deserialize;

use crate::client::Client;
use crate::error::{Result, fail, failure};
use crate::output::{Output, Table, strbool};
use crate::project::Project;
use crate::selector::Selector;

/// A component status, reported by the engine or read from the database.
#[derive(Debug, Deserialize)]
pub(crate) struct Status {
    pub(crate) address: String,
    pub(crate) running: bool,
    #[serde(default)]
    pub(crate) enabled: Option<bool>,
}

/// Parse and join raw address arguments into a single selector.
pub fn parse_selectors(addresses: &[String]) -> Result<Selector> {
    let selectors = addresses
        .iter()
        .map(|address| Selector::parse(address))
        .collect::<Result<Vec<_>>>()?;

    Ok(Selector::join(&selectors))
}

/// Apply configuration changes in the running engine.
pub fn reload(project: &Project) -> Result<()> {
    let client = Client::connect(project)?;
    client.post("reload", &[], None)?;
    Ok(())
}

/// An engine operation on the components matching a selector.
#[derive(Debug, Clone, Copy)]
pub enum Operation {
    Start,
    Stop,
    Enable,
    Disable,
    Up,
    Down,
}

impl Operation {
    fn path(&self) -> &'static str {
        match self {
            Self::Start => "start",
            Self::Stop => "stop",
            Self::Enable => "enable",
            Self::Disable => "disable",
            Self::Up => "up",
            Self::Down => "down",
        }
    }
}

/// Run an engine operation against the components matching `addresses` and print the result.
pub fn operate(
    project: &Project,
    output: &Output,
    operation: Operation,
    addresses: &[String],
) -> Result<()> {
    let selector = parse_selectors(addresses)?;
    let client = Client::connect(project)?;

    assert_matches(&client, &selector)?;

    let body = serde_json::json!({ "address": selector.text() });
    let result = client.post(operation.path(), &[], Some(&body))?;
    output.put(result);
    Ok(())
}

/// Fail with a quoting hint when a selector matches no components.
///
/// Shell glob expansion can silently rewrite selectors (for example `sensor.*` matching a
/// file named `sensor.yaml`), surfacing as a selector that matches nothing.
fn assert_matches(client: &Client, selector: &Selector) -> Result<()> {
    let statuses = get_statuses(client, selector)?;
    if statuses.is_empty() {
        fail!(
            "No components match '{}'. If your shell expanded a wildcard, quote the selector.",
            selector.text()
        );
    }

    Ok(())
}

/// Query the statuses of the components matching a selector.
fn get_statuses(client: &Client, selector: &Selector) -> Result<Vec<Status>> {
    let body = client.get("statuses", &[("address", selector.text())])?;
    serde_json::from_str(&body)
        .map_err(|error| failure!("Received an invalid status response. {error}"))
}

/// Show engine and component statuses for a running engine.
pub fn status(
    project: &Project,
    output: &Output,
    client: &Client,
    addresses: &[String],
) -> Result<()> {
    let selector = parse_selectors(addresses)?;
    let statuses = get_statuses(client, &selector)?;
    write_status(project, output, true, &statuses)
}

/// Render the engine and component status tables.
pub(crate) fn write_status(
    project: &Project,
    output: &Output,
    running: bool,
    statuses: &[Status],
) -> Result<()> {
    let meta = project.load_meta()?;

    let mut engine = Table::new(Some("Engine"));
    engine
        .column("Configuration")
        .column("Running")
        .column("Web Server Port")
        .column("CLI Server Port");
    engine.row([
        project.config_path().display().to_string(),
        strbool(running).to_string(),
        meta.server
            .port
            .map_or_else(|| "(Disabled)".to_string(), |port| port.to_string()),
        project
            .server_info()
            .map_or_else(|| "(Stopped)".to_string(), |info| info.port.to_string()),
    ]);
    output.write_table(&engine);

    if !statuses.is_empty() {
        let mut components = Table::new(Some("Components"));
        components
            .column("Address")
            .column("Enabled")
            .column("Running");
        for current in statuses {
            components.row([
                current.address.clone(),
                strbool(current.enabled.unwrap_or(false)).to_string(),
                strbool(current.running).to_string(),
            ]);
        }

        output.write_table(&components);
    }

    Ok(())
}
