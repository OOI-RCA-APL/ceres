//! Export runs and playbacks, started in a running engine and followed until they end.

use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::io::Write;
use std::time::Duration;

use ceres_entities::{Address, Records, Timestamp};
use chrono::{DurationRound, TimeDelta};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::cli::{ExportArgs, ExportConflict, ExportRangeMode, PlaybackArgs, RangeArgs};
use crate::client::{Client, encode};
use crate::error::{Result, fail, failure};
use crate::output::{Cell, Output, Table};
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
}

/// Run one exporter of a component, or every one when the arguments name none, and wait for
/// each run to end. A dry run prints what each would do instead.
pub fn export(project: &Project, output: &Output, args: &ExportArgs) -> Result<()> {
    let client = Client::connect(project)?;
    let address = &args.address;
    let component = format!("components/{}", encode(address));
    let names = match &args.exporter {
        Some(name) => vec![name.clone()],
        None => {
            let exporters: Vec<Exporter> =
                parse(&client.get(&format!("{component}/exporters"), &[])?)?;
            if exporters.is_empty() {
                fail!("Component '{address}' has no exporters.");
            }

            exporters
                .into_iter()
                .map(|exporter| exporter.name)
                .collect()
        }
    };

    let runs = |name: &str| format!("{component}/exporters/{}/runs", encode(name));
    let body = |dry_run: bool| {
        args.range.body(json!({
            "on_conflict": args.on_conflict,
            "range_mode": args.range_mode,
            "dry_run": dry_run,
        }))
    };

    if args.dry_run {
        for name in &names {
            let plan: Value = parse(&client.post(&runs(name), &[], Some(&body(true)))?)?;
            output.put(plan.to_string());
            describe_export_plan(output, &plan);
        }

        return Ok(());
    }

    // A conflict refuses every run before any writes, so `error` leaves all the files alone.
    if args.on_conflict == ExportConflict::Error && names.len() > 1 {
        for name in &names {
            client
                .post(&runs(name), &[], Some(&body(true)))
                .map_err(|error| failure!("Exporter '{name}' would not run. {error}"))?;
        }
    }

    // Every run starts before any is followed, so a run the engine refuses leaves the others
    // running.
    let mut failed = false;
    let mut started = Vec::new();
    for name in names {
        let path = runs(&name);
        match client
            .post(&path, &[], Some(&body(false)))
            .and_then(|body| parse::<Started>(&body))
        {
            Ok(run) => started.push((name, path, run.id)),
            Err(error) => {
                output.warn(format!("Exporter '{name}' did not start. {error}"));
                failed = true;
            }
        }
    }

    for (name, path, id) in started {
        let run = follow(&client, output, &path, &id, |run| {
            describe_export(&name, run)
        })?;
        failed |= report(output, &format!("Exporter '{name}'"), &run, |run| {
            export_outcome(&name, run)
        });
    }

    if failed {
        fail!("An export run failed.");
    }

    Ok(())
}

/// Replay a component's stored messages and wait for the playback to end. A dry run prints
/// what it would do instead.
pub fn playback(project: &Project, output: &Output, args: &PlaybackArgs) -> Result<()> {
    let client = Client::connect(project)?;
    let address = &args.address;
    let playbacks = format!("components/{}/playbacks", encode(address));
    let mut body = args.range.body(json!({
        "level": args.level,
        "export": args.export,
        "dry_run": args.dry_run,
    }));
    if let Some(mode) = args.on_export_conflict {
        body["on_export_conflict"] = json!(mode);
    }
    if let Some(mode) = args.export_range_mode {
        body["export_range_mode"] = json!(mode);
    }

    let answer = client.post(&playbacks, &[], Some(&body))?;
    if args.dry_run {
        let plan: Value = parse(&answer)?;
        output.put(plan.to_string());
        describe_playback_plan(output, address, &plan);
        return Ok(());
    }

    let started: Started = parse(&answer)?;
    let run = follow(&client, output, &playbacks, &started.id, |run| {
        describe_playback(address, run)
    })?;
    if report(output, "Playback", &run, playback_outcome) {
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

/// Read the runs listed at `path` until the one with `id` leaves the running state, showing
/// the progress line `describe` makes of it meanwhile.
fn follow(
    client: &Client,
    output: &Output,
    path: &str,
    id: &str,
    describe: impl Fn(&Value) -> String,
) -> Result<Value> {
    let mut progress = output.progress();
    loop {
        let runs: Vec<Value> = parse(&client.get(path, &[])?)?;
        let Some(run) = runs.into_iter().find(|run| run["id"] == id) else {
            fail!("Run {id} left the engine's list of recent runs before it ended.");
        };

        if run["state"] != "running" {
            return Ok(run);
        }

        progress.show(describe(&run));
        std::thread::sleep(POLL_INTERVAL);
    }
}

/// An export run's progress line.
fn describe_export(name: &str, run: &Value) -> String {
    format!(
        "Exporting '{name}': {} of {}, {}",
        number(&run["periods_done"]),
        counted(&run["periods"], "file"),
        counted(&run["count"], "record"),
    )
}

/// A playback's progress line. A playback whose sieves are all done is running the export
/// runs that rewrite its particles' files.
fn describe_playback(address: &str, run: &Value) -> String {
    if run["sieves_done"] == run["sieves"] {
        return format!(
            "Playing back {address}: exporting {}",
            counted(&run["particles"], "particle")
        );
    }

    let percent = (run["progress"].as_f64().unwrap_or(0.0) * 100.0).floor();
    let sieve = match run["sieve"].as_str() {
        Some(sieve) => format!(", sieve '{sieve}'"),
        None => String::new(),
    };
    format!(
        "Playing back {address}: {percent}%{sieve}, {}, {}",
        counted(&run["messages"], "message"),
        counted(&run["particles"], "particle"),
    )
}

/// Print an ended run, its record to stdout and a line about it to stderr, and return
/// whether it failed. `outcome` says what a completed run did.
fn report(output: &Output, what: &str, run: &Value, outcome: impl Fn(&Value) -> String) -> bool {
    output.put(run.to_string());
    match run["exception"].as_str() {
        Some(exception) => {
            output.warn(format!("{what} failed. {exception}"));
            true
        }
        None => {
            output.write(outcome(run));
            false
        }
    }
}

/// What a completed export run did.
fn export_outcome(name: &str, run: &Value) -> String {
    let mut line = format!(
        "Exporter '{name}' wrote {} to {}",
        counted(&run["count"], "record"),
        counted(&json!(run["files"].as_array().map_or(0, Vec::len)), "file"),
    );
    for (field, verb) in [("kept", "kept"), ("removed", "removed")] {
        if run[field].as_u64().is_some_and(|count| count > 0) {
            line.push_str(&format!(", {verb} {}", counted(&run[field], "file")));
        }
    }

    line.push('.');
    line
}

/// What a completed playback did.
fn playback_outcome(run: &Value) -> String {
    let mut line = format!(
        "Playback replayed {} into {}",
        counted(&run["messages"], "message"),
        counted(&run["particles"], "particle"),
    );
    if run["deleted"].as_u64().is_some_and(|count| count > 0) {
        line.push_str(&format!(
            ", replacing {}",
            counted(&run["deleted"], "stored particle")
        ));
    }

    if let Some(runs) = run["export_runs"]
        .as_array()
        .filter(|runs| !runs.is_empty())
    {
        line.push_str(&format!(
            ", and ran {}",
            counted(&json!(runs.len()), "export")
        ));
    }

    line.push('.');
    if run["after"] != run["before"]
        && (run["after"] != run["requested_after"] || run["before"] != run["requested_before"])
    {
        line.push_str(&format!(
            " It covered {} to {}, where the request named {} to {}.",
            time(&run["after"]),
            time(&run["before"]),
            time(&run["requested_after"]),
            time(&run["requested_before"]),
        ));
    }

    line
}

/// Print an export dry run's plan to stderr, a table of the files it covers.
fn describe_export_plan(output: &Output, plan: &Value) {
    let name = plan["exporter"].as_str().unwrap_or_default();
    if plan["covered"] == false {
        output.write(format!(
            "Exporter '{name}' would write nothing, since no whole file fits the range."
        ));
        return;
    }

    let files = plan["files"].as_array().map_or(&[][..], Vec::as_slice);
    output.write(format!(
        "Exporter '{name}' would write {} from {} to {}.",
        counted(&plan["count"], "record"),
        time(&plan["effective_after"]),
        time(&plan["effective_before"]),
    ));
    if plan["effective_after"] != plan["after"] || plan["effective_before"] != plan["before"] {
        output.write(format!(
            "The request named {} to {}, which range mode '{}' aligns to the files.",
            time(&plan["after"]),
            time(&plan["before"]),
            plan["range_mode"].as_str().unwrap_or_default(),
        ));
    }
    if files.is_empty() {
        return;
    }

    let reasons = files.iter().any(|file| !file["reason"].is_null());
    let mut table = Table::new(None);
    table.column("File").column("Action").column("Records");
    if reasons {
        table.column("Reason");
    }

    for file in files {
        let mut cells = vec![
            Cell::from(file["path"].as_str().unwrap_or_default().to_string()),
            Cell::from(file["action"].as_str().unwrap_or_default().to_string()),
            Cell::from(number(&file["records"])),
        ];
        if reasons {
            cells.push(Cell::from(keep_reason(&file["reason"]).to_string()));
        }

        table.row(cells);
    }

    output.write_table(&table);
}

/// Print a playback dry run's plan to stderr, its sieves, the exports it would run, and what
/// its sieves logged.
fn describe_playback_plan(output: &Output, address: &str, plan: &Value) {
    output.write(format!(
        "Playback of {address} would replay {} to {}, replacing {}.",
        time(&plan["after"]),
        time(&plan["before"]),
        counted(&plan["deleted"], "stored particle"),
    ));
    if plan["after"] != plan["requested_after"] || plan["before"] != plan["requested_before"] {
        output.write(format!(
            "The request named {} to {}.",
            time(&plan["requested_after"]),
            time(&plan["requested_before"]),
        ));
    }

    let sieves = plan["sieves"].as_array().map_or(&[][..], Vec::as_slice);
    if !sieves.is_empty() {
        let stopped = sieves.iter().any(|sieve| !sieve["exception"].is_null());
        let mut table = Table::new(None);
        table.column("Sieve").column("Messages").column("Particles");
        if stopped {
            table.column("Stopped");
        }

        for sieve in sieves {
            let mut cells = vec![
                Cell::from(sieve["name"].as_str().unwrap_or_default().to_string()),
                Cell::from(number(&sieve["messages"])),
                Cell::from(number(&sieve["particles"])),
            ];
            if stopped {
                cells.push(Cell::from(
                    sieve["exception"].as_str().unwrap_or_default().to_string(),
                ));
            }

            table.row(cells);
        }

        output.write_table(&table);
    }

    for export in plan["exports"].as_array().into_iter().flatten() {
        describe_export_plan(output, export);
    }

    if let Some(counts) = plan["log_counts"]
        .as_object()
        .filter(|counts| !counts.is_empty())
    {
        let counts: Vec<String> = counts
            .iter()
            .map(|(level, count)| format!("{level} {}", number(count)))
            .collect();
        output.write(format!(
            "Sieve log entries by level: {}.",
            counts.join(", ")
        ));

        // A sieve repeats one complaint per bad message, so each distinct entry shows once.
        let mut distinct: Vec<(String, &str, u64)> = Vec::new();
        for entry in plan["logs"].as_array().into_iter().flatten() {
            let level = entry["level"].as_str().unwrap_or_default().to_uppercase();
            let content = entry["content"].as_str().unwrap_or_default();
            match distinct
                .iter_mut()
                .find(|(shown, text, _)| *shown == level && *text == content)
            {
                Some((_, _, repeats)) => *repeats += 1,
                None => distinct.push((level, content, 1)),
            }
        }

        for (level, content, repeats) in &distinct {
            match repeats {
                1 => output.write(format!("  {level} {content}")),
                _ => output.write(format!("  {level} {content} ({repeats} times)")),
            }
        }

        if plan["logs_truncated"] == true {
            let shown = plan["logs"].as_array().map_or(0, Vec::len);
            output.write(format!("  Only the first {shown} entries are shown."));
        }
    }

    if plan["complete"] == false {
        output.warn("A sieve stopped early, so the counts cover only the messages before it.");
    }
}

/// Why a plan keeps a file, in words.
fn keep_reason(reason: &Value) -> &'static str {
    match reason.as_str() {
        Some("skip") => "exists",
        Some("history") => "starts before the stored records",
        Some("partial") => "only part of it is in range",
        Some("empty") => "no stored records",
        _ => "",
    }
}

/// A time from a run or plan, an open bound in words.
fn time(value: &Value) -> String {
    match value.as_str() {
        Some(time) => time.to_string(),
        None => "the open end".to_string(),
    }
}

/// A count with its noun, plural unless it is one.
fn counted(value: &Value, noun: &str) -> String {
    let count = number(value);
    if count == "1" {
        format!("1 {noun}")
    } else {
        format!("{count} {noun}s")
    }
}

/// A count as text, 0 when it is missing.
fn number(value: &Value) -> String {
    value.as_u64().unwrap_or(0).to_string()
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

    /// The spans in the shape the engine reads, one object per kind and address, each carrying
    /// the modes `export` names.
    fn entries(&self, export: &LoadExport) -> Vec<Value> {
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
                    let mut entry = json!({
                        "kind": kind,
                        "address": address,
                        "first": floor(first),
                        "last": ceiling,
                    });
                    if let Some(mode) = export.on_conflict {
                        entry["on_conflict"] = json!(mode);
                    }
                    if let Some(mode) = export.range_mode {
                        entry["range_mode"] = json!(mode);
                    }

                    entry
                })
            })
            .collect()
    }
}

const MICROSECOND: TimeDelta = TimeDelta::microseconds(1);

/// The export a record load asked for with `--export`, each mode `None` for the engine's
/// default.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub(crate) struct LoadExport {
    pub(crate) on_conflict: Option<ExportConflict>,
    pub(crate) range_mode: Option<ExportRangeMode>,
}

/// Hand a load's spans to the running engine to export, or leave them in the project's
/// state directory for the engine to export when it next starts.
pub(crate) fn export_loaded(
    project: &Project,
    output: &Output,
    spans: &LoadedSpans,
    export: &LoadExport,
) -> Result<()> {
    let entries = spans.entries(export);
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
            "Exporting 'messages': 12 of 48 files, 1204 records"
        );

        let playback = json!({
            "sieves": 2, "sieves_done": 0, "sieve": "abc", "progress": 0.406,
            "messages": 3000, "particles": 1,
        });
        assert_eq!(
            describe_playback("@abc", &playback),
            "Playing back @abc: 40%, sieve 'abc', 3000 messages, 1 particle"
        );

        let waiting = json!({ "sieves": 1, "sieves_done": 0, "sieve": null, "progress": 0.0 });
        assert_eq!(
            describe_playback("@abc", &waiting),
            "Playing back @abc: 0%, 0 messages, 0 particles"
        );

        let exporting = json!({ "sieves": 1, "sieves_done": 1, "particles": 2100 });
        assert_eq!(
            describe_playback("@abc", &exporting),
            "Playing back @abc: exporting 2100 particles"
        );
    }

    #[test]
    fn a_completed_run_says_what_it_did() {
        let run = json!({ "count": 12, "files": ["abc.csv"], "kept": 2, "removed": 0 });
        assert_eq!(
            export_outcome("abc", &run),
            "Exporter 'abc' wrote 12 records to 1 file, kept 2 files."
        );

        let playback = json!({
            "requested_after": "2026-01-01T00:00:00Z", "after": "2026-01-01T01:00:00Z",
            "requested_before": "2026-01-02T00:00:00Z",
            "before": "2026-01-02T00:00:00Z", "messages": 5, "particles": 4, "deleted": 3,
            "export_runs": ["abcd"],
        });
        assert_eq!(
            playback_outcome(&playback),
            "Playback replayed 5 messages into 4 particles, replacing 3 stored particles, and \
             ran 1 export. It covered 2026-01-01T01:00:00Z to 2026-01-02T00:00:00Z, where the \
             request named 2026-01-01T00:00:00Z to 2026-01-02T00:00:00Z."
        );

        let nothing = json!({
            "requested_after": "2026-01-01T00:00:00Z", "after": "2026-01-02T00:00:00Z",
            "before": "2026-01-02T00:00:00Z", "messages": 0, "particles": 0, "deleted": 0,
            "export_runs": [],
        });
        assert_eq!(
            playback_outcome(&nothing),
            "Playback replayed 0 messages into 0 particles."
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
            spans.entries(&LoadExport::default()),
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
            spans.entries(&LoadExport::default()),
            [span(
                "@abc",
                "2026-01-01T01:00:00Z",
                "2026-01-01T01:00:00.000002Z"
            )]
        );
    }

    #[test]
    fn a_span_carries_the_export_modes() {
        let mut spans = LoadedSpans::default();
        spans.cover(&messages(&[("@abc", "2026-01-01T01:00:00Z")]));
        let export = LoadExport {
            on_conflict: Some(ExportConflict::Skip),
            range_mode: Some(ExportRangeMode::Exact),
        };

        let mut entry = span("@abc", "2026-01-01T01:00:00Z", "2026-01-01T01:00:00Z");
        entry["on_conflict"] = json!("skip");
        entry["range_mode"] = json!("exact");
        assert_eq!(spans.entries(&export), [entry]);
    }

    #[test]
    fn a_load_with_no_engine_leaves_its_spans_for_the_next_start() {
        let directory = tempfile::tempdir().unwrap();
        let project = Project::at(directory.path().join("ceres.yaml"));
        let mut spans = LoadedSpans::default();
        spans.cover(&messages(&[("@abc", "2026-01-01T01:00:00Z")]));

        let output = Output::new(Some(false));
        let export = LoadExport::default();
        export_loaded(&project, &output, &spans, &export).unwrap();
        export_loaded(&project, &output, &spans, &export).unwrap();

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

        let output = Output::new(Some(false));
        export_loaded(
            &project,
            &output,
            &LoadedSpans::default(),
            &LoadExport::default(),
        )
        .unwrap();

        assert!(!project.state_directory().exists());
    }
}
