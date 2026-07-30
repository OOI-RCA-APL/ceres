//! Native record dumps.
//!
//! A plain JSON `select` or `count` over a record table runs entirely natively, the
//! filter parses into the native subset, the database opens read-only through the
//! native store, and the output renders in one pass, so the interpreter never starts.
//! Anything else, an unrecognized flag, a construct outside the filter subset, a
//! non-JSON format, colorized terminal output, or a database the native store cannot
//! join, delegates to the Python runtime, which either serves it or produces the
//! canonical error. Failures follow the same rule, the native attempt renders its whole
//! output before writing anything, and any error along the way delegates rather than
//! surfacing a message of its own.

use std::io::Write;
use std::path::{Path, PathBuf};

use ceres_config::DatabaseConfig;
use ceres_database::{RecordFilter, RecordStore, RecordTable};
use clap::Parser;

use crate::error::Result;
use crate::project::Project;

/// The record subcommands the native path serves.
#[derive(Debug, Parser)]
#[command(no_binary_name = true, disable_help_flag = true)]
enum RecordCommand {
    Select(SelectArgs),
    Count(SelectArgs),
}

/// The strict flag surface of a native record query.
///
/// Filter values stay text here, the native filter parser is the single authority on
/// what parses and what delegates, so the CLI and the server admit exactly the same
/// subset.
#[derive(Debug, Parser)]
struct SelectArgs {
    #[arg(long)]
    id: Vec<String>,
    #[arg(long)]
    address: Option<String>,
    #[arg(long)]
    timestamp: Vec<String>,
    #[arg(long)]
    after: Option<String>,
    #[arg(long)]
    before: Option<String>,
    #[arg(long)]
    timespan: Option<String>,
    #[arg(long)]
    max_age: Option<String>,
    #[arg(long)]
    min_age: Option<String>,
    #[arg(long)]
    order: Vec<String>,
    #[arg(long)]
    limit: Option<String>,
    #[arg(long)]
    offset: Option<String>,
    #[arg(long)]
    connection: Vec<String>,
    #[arg(long)]
    direction: Vec<String>,
    #[arg(long = "type")]
    kind: Vec<String>,
    #[arg(long)]
    level: Vec<String>,
    #[arg(long)]
    min_level: Option<String>,
    #[arg(long)]
    max_level: Option<String>,
    #[arg(long)]
    content: Vec<String>,

    /// Output destination and rendering, matching the Python command's surface.
    #[arg(long)]
    output: Option<PathBuf>,
    #[arg(long)]
    data_format: Option<String>,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    color: bool,
    #[arg(long)]
    no_color: bool,
    /// Field projection, positional or by flag, which always delegates.
    #[arg(long)]
    field: Vec<String>,
    fields: Vec<String>,
}

impl SelectArgs {
    /// The filter's wire pairs, in flag order per key.
    fn pairs(&self) -> Vec<(String, String)> {
        let mut pairs = Vec::new();
        let mut many = |key: &str, values: &[String]| {
            for value in values {
                pairs.push((key.to_string(), value.clone()));
            }
        };

        many("id", &self.id);
        many("timestamp", &self.timestamp);
        many("order", &self.order);
        many("connection", &self.connection);
        many("direction", &self.direction);
        many("type", &self.kind);
        many("level", &self.level);
        many("content", &self.content);
        let mut one = |key: &str, value: &Option<String>| {
            if let Some(value) = value {
                pairs.push((key.to_string(), value.clone()));
            }
        };

        one("address", &self.address);
        one("after", &self.after);
        one("before", &self.before);
        one("timespan", &self.timespan);
        one("max_age", &self.max_age);
        one("min_age", &self.min_age);
        one("limit", &self.limit);
        one("offset", &self.offset);
        one("min_level", &self.min_level);
        one("max_level", &self.max_level);
        pairs
    }

    /// Whether output is plain JSON with no projection and no color, the shape the
    /// native path renders. Mirrors the Python command's color resolution.
    fn plain_json_output(&self) -> bool {
        if !self.fields.is_empty() || !self.field.is_empty() {
            return false;
        }

        if self
            .data_format
            .as_deref()
            .is_some_and(|format| format != "json")
        {
            return false;
        }

        if self.color {
            return false;
        }

        if !self.no_color {
            if std::env::var_os("FORCE_COLOR").is_some() {
                return false;
            }

            if std::env::var_os("NO_COLOR").is_none()
                && self.output.is_none()
                && std::io::IsTerminal::is_terminal(&std::io::stdout())
            {
                return false;
            }
        }

        true
    }
}

/// Attempt one record command natively, `false` meaning the caller delegates.
pub fn try_run(
    table: RecordTable,
    config: Option<&Path>,
    raw: &[std::ffi::OsString],
) -> Result<bool> {
    let Ok(command) = RecordCommand::try_parse_from(raw) else {
        return Ok(false);
    };

    let (arguments, counting) = match &command {
        RecordCommand::Select(arguments) => (arguments, false),
        RecordCommand::Count(arguments) => (arguments, true),
    };
    if !arguments.plain_json_output() {
        return Ok(false);
    }

    let Some(filter) = RecordFilter::parse(table, &arguments.pairs()) else {
        return Ok(false);
    };

    let config = arguments.config.as_deref().or(config);
    let Ok(project) = Project::discover(config) else {
        return Ok(false);
    };
    let Ok(meta) = project.load_meta() else {
        return Ok(false);
    };
    // Pool construction spawns maintenance tasks, so the runtime has to exist first.
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("the runtime always builds");
    let guard = runtime.enter();
    let Some(store) = open_store(&meta.database) else {
        return Ok(false);
    };

    drop(guard);

    // The whole result renders before anything writes, so a failure here can still
    // delegate without having produced partial output.
    let rendered = runtime.block_on(async {
        if counting {
            store
                .count_filter(table, &filter)
                .await
                .map(|count| format!("{count}\n").into_bytes())
        } else {
            let records = store.fetch_filter(table, &filter).await?;
            records
                .to_json_lines()
                .map_err(|error| ceres_database::Error::Decode(error.to_string()))
        }
    });
    let Ok(rendered) = rendered else {
        return Ok(false);
    };

    write_output(arguments.output.as_deref(), &rendered)
}

/// Open the native store for a configured database, `None` when it cannot join.
///
/// The rules mirror the Python layer's own native-pool gating, an in-memory or
/// unpathed file database is private to its instance, and a PostgreSQL configuration
/// carrying driver-specific connection arguments cannot be reproduced faithfully.
fn open_store(config: &DatabaseConfig) -> Option<RecordStore> {
    match config {
        DatabaseConfig::Sqlite(sqlite) => {
            if sqlite.is_memory() {
                return None;
            }

            let path = absolute_existing(sqlite.path.as_deref()?)?;
            RecordStore::sqlite(&path).ok()
        }
        DatabaseConfig::Turso(turso) => {
            let path = absolute_existing(turso.path.as_deref()?)?;
            Some(RecordStore::turso(&path, turso.mvcc))
        }
        DatabaseConfig::Postgres(postgres) => {
            if postgres.shared.query.is_some() {
                return None;
            }

            let mut settings = Vec::new();
            for (key, value) in &postgres.shared.engine {
                if key != "connect_args" {
                    return None;
                }

                let arguments = value.as_object()?;
                for (name, value) in arguments {
                    if name != "server_settings" {
                        return None;
                    }

                    for (setting, text) in value.as_object()? {
                        settings.push((setting.clone(), text.as_str()?.to_string()));
                    }
                }
            }

            RecordStore::postgres(
                &postgres.host,
                postgres.port,
                &postgres.database,
                &postgres.user,
                postgres.password.as_ref().map(|secret| secret.expose()),
                settings,
            )
            .ok()
        }
    }
}

/// Resolve a database path like the Python layer, absolute against the working
/// directory, and only when the file exists, a missing one delegates so the canonical
/// connection error comes from Python.
fn absolute_existing(path: &Path) -> Option<String> {
    let absolute = std::path::absolute(path).ok()?;
    if !absolute.is_file() {
        return None;
    }

    Some(absolute.to_string_lossy().into_owned())
}

/// Write the rendered output to the destination the command named.
fn write_output(output: Option<&Path>, rendered: &[u8]) -> Result<bool> {
    match output {
        Some(path) => {
            let Ok(mut file) = std::fs::File::create(path) else {
                // The Python command owns the failure message for an unwritable output.
                return Ok(false);
            };
            if file.write_all(rendered).is_err() {
                return Ok(false);
            }
        }
        None => {
            let stdout = std::io::stdout();
            let mut lock = stdout.lock();
            let _ = lock.write_all(rendered);
        }
    }

    Ok(true)
}

#[cfg(test)]
mod tests {
    use std::ffi::OsString;

    use super::*;

    fn raw(arguments: &[&str]) -> Vec<OsString> {
        arguments.iter().map(OsString::from).collect()
    }

    #[test]
    fn unknown_flags_and_subcommands_fail_the_strict_parse() {
        assert!(RecordCommand::try_parse_from(raw(&["select", "--contains", "x"])).is_err());
        assert!(RecordCommand::try_parse_from(raw(&["select", "--help"])).is_err());
        assert!(RecordCommand::try_parse_from(raw(&["create"])).is_err());
        assert!(RecordCommand::try_parse_from(raw(&["select", "--limit", "5"])).is_ok());
        assert!(RecordCommand::try_parse_from(raw(&["count", "--min-level", "error"])).is_ok());
    }

    #[test]
    fn flags_map_to_the_same_wire_pairs_the_server_parses() {
        let RecordCommand::Select(arguments) = RecordCommand::try_parse_from(raw(&[
            "select",
            "--address",
            "@sensor.temp",
            "--max-age",
            "2h",
            "--order",
            "timestamp:desc",
            "--limit",
            "10",
        ]))
        .unwrap() else {
            panic!("expected a select");
        };

        let pairs = arguments.pairs();
        assert!(RecordFilter::parse(RecordTable::Messages, &pairs).is_some());
        assert!(pairs.contains(&("max_age".to_string(), "2h".to_string())));
    }

    #[test]
    fn projection_format_and_color_gate_the_native_path() {
        let parse = |arguments: &[&str]| {
            let RecordCommand::Select(arguments) =
                RecordCommand::try_parse_from(raw(arguments)).unwrap()
            else {
                panic!("expected a select");
            };
            arguments
        };

        assert!(!parse(&["select", "--field", "id", "--no-color"]).plain_json_output());
        assert!(!parse(&["select", "id", "--no-color"]).plain_json_output());
        assert!(!parse(&["select", "--data-format", "csv", "--no-color"]).plain_json_output());
        assert!(!parse(&["select", "--color"]).plain_json_output());
        assert!(parse(&["select", "--no-color"]).plain_json_output());
        assert!(parse(&["select", "--output", "out.json", "--no-color"]).plain_json_output());
    }
}
