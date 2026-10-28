//! Export runs and playbacks, started in a running engine and followed until they end.

use std::time::Duration;

use serde::Deserialize;
use serde_json::{Value, json};

use crate::cli::RangeArgs;
use crate::client::{Client, encode};
use crate::error::{Result, fail, failure};
use crate::output::Output;
use crate::project::Project;

/// How often a started run's state is read while it runs.
const POLL_INTERVAL: Duration = Duration::from_millis(500);

/// The ID the engine answers a started run or playback with.
#[derive(Debug, Deserialize)]
struct Started {
    id: String,
}

/// The part of an exporter's description this command reads.
#[derive(Debug, Deserialize)]
struct Exporter {
    name: String,
}

/// Run one exporter of a component over `[after, before)`, or every one when `exporter` is
/// `None`, and wait for each run to end.
pub fn export(
    project: &Project,
    output: &Output,
    address: &str,
    exporter: Option<&str>,
    range: &RangeArgs,
    replace: bool,
) -> Result<()> {
    let client = Client::connect(project)?;
    let component = format!("components/{}", encode(address));
    let names = match exporter {
        Some(name) => vec![name.to_string()],
        None => {
            let exporters: Vec<Exporter> = parse(&client.get(&format!("{component}/exporters"), &[])?)?;
            if exporters.is_empty() {
                fail!("Component '{address}' has no exporters.");
            }

            exporters.into_iter().map(|exporter| exporter.name).collect()
        }
    };

    let body = range.body(json!({ "replace": replace }));
    let mut failed = false;
    for name in names {
        let runs = format!("{component}/exporters/{}/runs", encode(&name));
        let started: Started = parse(&client.post(&runs, &[], Some(&body))?)?;
        let run = follow(&client, &runs, &started.id)?;
        failed |= report(output, &format!("Exporter '{name}'"), &run);
    }

    if failed {
        fail!("An export run failed.");
    }

    Ok(())
}

/// Replay a component's stored messages over `[after, before)` and wait for it to end.
pub fn playback(
    project: &Project,
    output: &Output,
    address: &str,
    range: &RangeArgs,
    level: &str,
    export: bool,
) -> Result<()> {
    let client = Client::connect(project)?;
    let playbacks = format!("components/{}/playbacks", encode(address));
    let body = range.body(json!({ "level": level, "export": export }));
    let started: Started = parse(&client.post(&playbacks, &[], Some(&body))?)?;
    let run = follow(&client, &playbacks, &started.id)?;
    if report(output, "Playback", &run) {
        fail!("The playback failed.");
    }

    Ok(())
}

impl RangeArgs {
    /// Add the range to a request body, in the fields the engine reads.
    fn body(&self, mut body: Value) -> Value {
        body["after"] = json!(self.after);
        if let Some(before) = &self.before {
            body["before"] = json!(before);
        }

        body
    }
}

/// Read the runs listed at `path` until the one with `id` leaves the running state.
fn follow(client: &Client, path: &str, id: &str) -> Result<Value> {
    loop {
        let runs: Vec<Value> = parse(&client.get(path, &[])?)?;
        let Some(run) = runs.into_iter().find(|run| run["id"] == id) else {
            fail!("Run {id} left the engine's list of recent runs before it ended.");
        };

        if run["state"] != "running" {
            return Ok(run);
        }

        std::thread::sleep(POLL_INTERVAL);
    }
}

/// Print an ended run, its record to stdout and a line about it to stderr, and return
/// whether it failed.
fn report(output: &Output, what: &str, run: &Value) -> bool {
    output.put(run.to_string());
    match run["exception"].as_str() {
        Some(exception) => {
            output.warn(format!("{what} failed. {exception}"));
            true
        }
        None => {
            output.write(format!("{what} completed."));
            false
        }
    }
}

fn parse<T: serde::de::DeserializeOwned>(body: &str) -> Result<T> {
    serde_json::from_str(body).map_err(|error| failure!("Received an invalid response. {error}"))
}
