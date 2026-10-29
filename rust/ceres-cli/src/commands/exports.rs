//! Export runs and playbacks, started in a running engine and followed until they end.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::time::Duration;

use ceres_entities::{Address, Records, Timestamp};
use chrono::{DurationRound, TimeDelta};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::cli::RangeArgs;
use crate::client::{Client, encode};
use crate::error::{Result, fail, failure};
use crate::output::Output;
use crate::project::Project;

/// How often a started run's state is read while it runs.
const POLL_INTERVAL: Duration = Duration::from_millis(500);

/// The file in the state directory a load leaves its spans in when no engine runs,
/// named the same in `ceres/__internal__/pending_exports.py`.
const PENDING_EXPORTS_FILE: &str = "pending-exports.jsonl";

/// The ID the engine answers a started run or playback with.
#[derive(Debug, Deserialize)]
struct Started {
    id: String,
}

/// The part of an exporter's description this command reads.
#[derive(Debug, Deserialize)]
struct Exporter {
    name: String,
    merges: bool,
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
            let exporters: Vec<Exporter> =
                parse(&client.get(&format!("{component}/exporters"), &[])?)?;
            if exporters.is_empty() {
                fail!("Component '{address}' has no exporters.");
            }

            // A format that cannot merge only runs as a replace, which a run of every exporter
            // must not choose for it.
            let mut names = Vec::new();
            for exporter in exporters {
                if exporter.merges || replace {
                    names.push(exporter.name);
                } else {
                    output.warn(format!(
                        "Skipping exporter '{}', which cannot merge. Pass --replace to rewrite \
                         its files.",
                        exporter.name
                    ));
                }
            }

            names
        }
    };

    // Every run starts before any is followed, so a run the engine refuses leaves the others
    // running.
    let body = range.body(json!({ "replace": replace }));
    let mut failed = false;
    let mut started = Vec::new();
    for name in names {
        let runs = format!("{component}/exporters/{}/runs", encode(&name));
        match client
            .post(&runs, &[], Some(&body))
            .and_then(|body| parse::<Started>(&body))
        {
            Ok(run) => started.push((name, runs, run.id)),
            Err(error) => {
                output.warn(format!("Exporter '{name}' did not start. {error}"));
                failed = true;
            }
        }
    }

    for (name, runs, id) in started {
        let run = follow(&client, output, &runs, &id, |run| {
            describe_export(&name, run)
        })?;
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
    let run = follow(&client, output, &playbacks, &started.id, describe_playback)?;
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

/// Read the runs listed at `path` until the one with `id` leaves the running state, writing
/// a line of its progress to stderr each time the line `describe` makes of it changes.
fn follow(
    client: &Client,
    output: &Output,
    path: &str,
    id: &str,
    describe: impl Fn(&Value) -> String,
) -> Result<Value> {
    let mut shown = String::new();
    loop {
        let runs: Vec<Value> = parse(&client.get(path, &[])?)?;
        let Some(run) = runs.into_iter().find(|run| run["id"] == id) else {
            fail!("Run {id} left the engine's list of recent runs before it ended.");
        };

        if run["state"] != "running" {
            return Ok(run);
        }

        let line = describe(&run);
        if line != shown {
            output.write(&line);
            shown = line;
        }

        std::thread::sleep(POLL_INTERVAL);
    }
}

/// An export run's progress, as `follow` writes it.
fn describe_export(name: &str, run: &Value) -> String {
    format!(
        "{name}: {}/{} periods, {} records",
        run["periods_done"], run["periods"], run["count"]
    )
}

/// A playback's progress, as `follow` writes it. A playback whose sieves are all done is
/// running the export runs that rewrite its particles' files.
fn describe_playback(run: &Value) -> String {
    if run["sieves_done"] == run["sieves"] {
        return format!("playback: exporting, {} particles", run["particles"]);
    }

    let percent = (run["progress"].as_f64().unwrap_or(0.0) * 100.0).floor();
    let sieve = run["sieve"].as_str().unwrap_or("none");
    format!(
        "playback: {percent}%, sieve '{sieve}', {} messages, {} particles",
        run["messages"], run["particles"]
    )
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

/// The first and last time a load wrote for each record kind and address.
#[derive(Debug, Default)]
pub(crate) struct LoadedSpans {
    /// One entry per kind and address in the loaded file, so it grows with the file's
    /// distinct addresses rather than its rows.
    spans: BTreeMap<&'static str, BTreeMap<String, (Timestamp, Timestamp)>>,
}

impl LoadedSpans {
    /// Widen the spans to cover one batch of loaded records.
    pub(crate) fn cover(&mut self, records: &Records) {
        match records {
            Records::Messages(rows) => self.cover_rows(
                "message",
                rows.iter().map(|row| (&row.address, row.timestamp)),
            ),
            Records::Particles(rows) => self.cover_rows(
                "particle",
                rows.iter().map(|row| (&row.address, row.timestamp)),
            ),
            Records::Alerts(rows) => {
                self.cover_rows(
                    "alert",
                    rows.iter().map(|row| (&row.address, row.timestamp)),
                );
            }
            Records::LogEntries(rows) => self.cover_rows(
                "log-entry",
                rows.iter().map(|row| (&row.address, row.timestamp)),
            ),
        }
    }

    fn cover_rows<'a>(
        &mut self,
        kind: &'static str,
        rows: impl Iterator<Item = (&'a Address, Timestamp)>,
    ) {
        let addresses = self.spans.entry(kind).or_default();
        for (address, timestamp) in rows {
            match addresses.get_mut(address.as_str()) {
                Some((first, last)) => {
                    *first = (*first).min(timestamp);
                    *last = (*last).max(timestamp);
                }
                None => {
                    addresses.insert(address.as_str().to_owned(), (timestamp, timestamp));
                }
            }
        }
    }

    /// The spans in the shape the engine reads, one object per kind and address.
    fn entries(&self) -> Vec<Value> {
        self.spans
            .iter()
            .flat_map(|(kind, addresses)| {
                addresses.iter().map(move |(address, (first, last))| {
                    // A file may carry nanoseconds, which a database rounds or truncates to
                    // the microsecond, so the span widens to whole microseconds either way.
                    let floor = |time: &Timestamp| {
                        Timestamp(time.0.duration_trunc(MICROSECOND).unwrap_or(time.0))
                    };
                    let ceiling = match floor(last) {
                        floor if floor == *last => floor,
                        floor => Timestamp(floor.0 + MICROSECOND),
                    };
                    json!({
                        "kind": kind,
                        "address": address,
                        "first": floor(first),
                        "last": ceiling,
                    })
                })
            })
            .collect()
    }
}

const MICROSECOND: TimeDelta = TimeDelta::microseconds(1);

/// Hand a load's spans to the running engine to export, or leave them in the project's
/// state directory for the engine to export when it next starts.
pub(crate) fn export_loaded(project: &Project, output: &Output, spans: &LoadedSpans) -> Result<()> {
    let entries = spans.entries();
    if entries.is_empty() {
        return Ok(());
    }

    if let Some(client) = Client::connect_alive(project) {
        client.post("exports/pending", &[], Some(&json!({ "entries": entries })))?;
        output.write("Exporting the loaded records in the running engine.");
        return Ok(());
    }

    let path = project.state_directory().join(PENDING_EXPORTS_FILE);
    let mut lines = String::new();
    for entry in entries {
        lines.push_str(&entry.to_string());
        lines.push('\n');
    }

    std::fs::create_dir_all(project.state_directory())
        .and_then(|()| {
            OpenOptions::new()
                .create(true)
                .append(true)
                .open(&path)?
                .write_all(lines.as_bytes())
        })
        .map_err(|error| failure!("Failed to write '{}'. {error}", path.display()))?;
    output.write("No engine is running, so the next one to start exports the loaded records.");

    Ok(())
}

fn parse<T: serde::de::DeserializeOwned>(body: &str) -> Result<T> {
    serde_json::from_str(body).map_err(|error| failure!("Received an invalid response. {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_run_describes_its_progress() {
        let run = json!({ "periods": 48, "periods_done": 12, "count": 1204 });
        assert_eq!(
            describe_export("messages", &run),
            "messages: 12/48 periods, 1204 records"
        );

        let playback = json!({
            "sieves": 2, "sieves_done": 0, "sieve": "abc", "progress": 0.406,
            "messages": 3000, "particles": 2100,
        });
        assert_eq!(
            describe_playback(&playback),
            "playback: 40%, sieve 'abc', 3000 messages, 2100 particles"
        );

        let exporting = json!({ "sieves": 1, "sieves_done": 1, "particles": 2100 });
        assert_eq!(
            describe_playback(&exporting),
            "playback: exporting, 2100 particles"
        );
    }

    /// Messages at each `(address, timestamp)`.
    fn messages(rows: &[(&str, &str)]) -> Records {
        Records::Messages(
            rows.iter()
                .map(|(address, timestamp)| {
                    serde_json::from_value(json!({
                        "id": "0198c0de-0000-7000-8000-000000000001",
                        "address": address,
                        "timestamp": timestamp,
                        "connection": null,
                        "direction": "receive",
                        "data": "abc",
                    }))
                    .unwrap()
                })
                .collect(),
        )
    }

    fn span(address: &str, first: &str, last: &str) -> Value {
        json!({ "kind": "message", "address": address, "first": first, "last": last })
    }

    #[test]
    fn a_load_spans_each_address_from_its_first_record_to_its_last() {
        let mut spans = LoadedSpans::default();
        spans.cover(&messages(&[
            ("@abc", "2026-01-01T02:00:00Z"),
            ("@abcd", "2026-01-01T05:00:00Z"),
        ]));
        spans.cover(&messages(&[
            ("@abc", "2026-01-01T03:00:00Z"),
            ("@abc", "2026-01-01T01:00:00Z"),
        ]));

        assert_eq!(
            spans.entries(),
            [
                span("@abc", "2026-01-01T01:00:00Z", "2026-01-01T03:00:00Z"),
                span("@abcd", "2026-01-01T05:00:00Z", "2026-01-01T05:00:00Z"),
            ]
        );
    }

    #[test]
    fn a_span_widens_to_whole_microseconds() {
        let mut spans = LoadedSpans::default();
        spans.cover(&messages(&[
            ("@abc", "2026-01-01T01:00:00.0000015Z"),
            ("@abc", "2026-01-01T01:00:00.0000005Z"),
        ]));

        assert_eq!(
            spans.entries(),
            [span(
                "@abc",
                "2026-01-01T01:00:00Z",
                "2026-01-01T01:00:00.000002Z"
            )]
        );
    }

    #[test]
    fn a_load_with_no_engine_leaves_its_spans_for_the_next_start() {
        let directory = tempfile::tempdir().unwrap();
        let project = Project::at(directory.path().join("ceres.yaml"));
        let mut spans = LoadedSpans::default();
        spans.cover(&messages(&[("@abc", "2026-01-01T01:00:00Z")]));

        let output = Output::new(Some(false));
        export_loaded(&project, &output, &spans).unwrap();
        export_loaded(&project, &output, &spans).unwrap();

        let path = project.state_directory().join(PENDING_EXPORTS_FILE);
        let lines: Vec<Value> = std::fs::read_to_string(path)
            .unwrap()
            .lines()
            .map(|line| serde_json::from_str(line).unwrap())
            .collect();
        let entry = span("@abc", "2026-01-01T01:00:00Z", "2026-01-01T01:00:00Z");
        assert_eq!(lines, [entry.clone(), entry]);
    }

    #[test]
    fn a_load_of_nothing_leaves_nothing() {
        let directory = tempfile::tempdir().unwrap();
        let project = Project::at(directory.path().join("ceres.yaml"));

        export_loaded(&project, &Output::new(Some(false)), &LoadedSpans::default()).unwrap();

        assert!(!project.state_directory().exists());
    }
}
