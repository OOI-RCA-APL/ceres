//! Native record dumps.
//!
//! A plain JSON `select` or `count` over a record table runs entirely natively, the
//! filter parses into the native subset, the database opens read-only through the
//! native store, and the output renders in one pass, so the interpreter never starts.
//!
//! The command carries no filter flag surface of its own. Every `--key value` token
//! pair lexes into the same wire pairs the server parses, and the native filter subset,
//! which the entities' `Filterable` derives generate, is the single authority on what
//! is admitted. Anything else, an unknown key, a construct outside the subset, a
//! non-JSON format, colorized terminal output, or a database the native store cannot
//! join, delegates to the Python runtime, which either serves it or produces the
//! canonical error. Failures follow the same rule, the native attempt renders its whole
//! output before writing anything, and any error along the way delegates rather than
//! surfacing a message of its own.

use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};

use ceres_config::DatabaseConfig;
use ceres_database::{RecordFilter, RecordStore, RecordTable};

use crate::error::Result;
use crate::project::Project;

/// What a record invocation asked for, lexed without a declared flag surface.
#[derive(Debug, Default, PartialEq)]
struct Invocation {
    counting: bool,
    /// The filter's wire pairs, every flag that is not an output control.
    pairs: Vec<(String, String)>,
    output: Option<PathBuf>,
    data_format: Option<String>,
    config: Option<PathBuf>,
    /// The explicit color choice, `--color` or `--no-color`.
    color: Option<bool>,
    /// Whether fields were projected, positionally or by flag, which always delegates.
    projecting: bool,
}

impl Invocation {
    /// Lex raw arguments, `None` for anything the native path cannot represent.
    fn lex(raw: &[OsString]) -> Option<Self> {
        let mut tokens = raw.iter().map(|token| token.to_str());
        let mut invocation = Self {
            counting: match tokens.next()?? {
                "select" => false,
                "count" => true,
                _ => return None,
            },
            ..Self::default()
        };

        let mut tokens = tokens.peekable();
        while let Some(token) = tokens.next() {
            let token = token?;
            let Some(flag) = token.strip_prefix("--") else {
                // A bare token is positional field projection.
                invocation.projecting = true;
                continue;
            };

            // `--flag=value` and `--flag value` both lex, a flag at the end or before
            // another flag carries no value and delegates.
            let (flag, mut value) = match flag.split_once('=') {
                Some((flag, value)) => (flag, Some(value.to_string())),
                None => (flag, None),
            };

            match flag {
                "color" => invocation.color = Some(true),
                "no-color" => invocation.color = Some(false),
                _ => {
                    if value.is_none() {
                        let next = tokens.peek()?.as_ref()?;
                        if next.starts_with("--") {
                            return None;
                        }

                        value = Some((*next).to_string());
                        tokens.next();
                    }

                    let value = value?;
                    match flag {
                        "output" => invocation.output = Some(PathBuf::from(value)),
                        "data-format" => invocation.data_format = Some(value),
                        "config" => invocation.config = Some(PathBuf::from(value)),
                        "field" => invocation.projecting = true,
                        key => invocation.pairs.push((key.replace('-', "_"), value)),
                    }
                }
            }
        }

        Some(invocation)
    }

    /// Whether output is plain JSON with no projection and no color, the shape the
    /// native path renders. Mirrors the Python command's color resolution.
    fn plain_json_output(&self) -> bool {
        if self.projecting {
            return false;
        }

        if self
            .data_format
            .as_deref()
            .is_some_and(|format| format != "json")
        {
            return false;
        }

        match self.color {
            Some(true) => false,
            Some(false) => true,
            None => {
                if std::env::var_os("FORCE_COLOR").is_some() {
                    return false;
                }

                std::env::var_os("NO_COLOR").is_some()
                    || self.output.is_some()
                    || !std::io::IsTerminal::is_terminal(&std::io::stdout())
            }
        }
    }
}

/// Attempt one record command natively, `false` meaning the caller delegates.
pub fn try_run(table: RecordTable, config: Option<&Path>, raw: &[OsString]) -> Result<bool> {
    let Some(invocation) = Invocation::lex(raw) else {
        return Ok(false);
    };
    if !invocation.plain_json_output() {
        return Ok(false);
    }

    let Ok(filter) = RecordFilter::parse(table, &invocation.pairs) else {
        return Ok(false);
    };

    let config = invocation.config.as_deref().or(config);
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
        if invocation.counting {
            store
                .count_filter(&filter)
                .await
                .map(|count| format!("{count}\n").into_bytes())
        } else {
            let records = store.fetch_filter(&filter).await?;
            records
                .to_json_lines()
                .map_err(|error| ceres_database::Error::Decode(error.to_string()))
        }
    });
    let Ok(rendered) = rendered else {
        return Ok(false);
    };

    write_output(invocation.output.as_deref(), &rendered)
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
    use super::*;

    fn raw(arguments: &[&str]) -> Vec<OsString> {
        arguments.iter().map(OsString::from).collect()
    }

    #[test]
    fn only_select_and_count_lex() {
        assert!(Invocation::lex(&raw(&["select"])).is_some());
        assert!(Invocation::lex(&raw(&["count", "--limit", "5"])).is_some());
        assert!(Invocation::lex(&raw(&["create"])).is_none());
        assert!(Invocation::lex(&raw(&[])).is_none());
    }

    #[test]
    fn every_unclaimed_flag_becomes_a_wire_pair() {
        let invocation = Invocation::lex(&raw(&[
            "select",
            "--address",
            "@sensor.temp",
            "--max-age=2h",
            "--order",
            "timestamp:desc",
            "--limit",
            "10",
        ]))
        .unwrap();

        assert!(
            invocation
                .pairs
                .contains(&("max_age".to_string(), "2h".to_string()))
        );
        assert!(RecordFilter::parse(RecordTable::Messages, &invocation.pairs).is_ok());

        // Unknown keys lex into pairs too, and the filter is what refuses them.
        let unknown = Invocation::lex(&raw(&["select", "--nope", "x"])).unwrap();
        assert!(RecordFilter::parse(RecordTable::Messages, &unknown.pairs).is_err());
    }

    #[test]
    fn valueless_flags_delegate() {
        assert!(Invocation::lex(&raw(&["select", "--help"])).is_none());
        assert!(Invocation::lex(&raw(&["select", "--limit"])).is_none());
        assert!(Invocation::lex(&raw(&["select", "--limit", "--offset", "2"])).is_none());
    }

    #[test]
    fn projection_format_and_color_gate_the_native_path() {
        let lex = |arguments: &[&str]| Invocation::lex(&raw(arguments)).unwrap();

        assert!(!lex(&["select", "--field", "id", "--no-color"]).plain_json_output());
        assert!(!lex(&["select", "id", "--no-color"]).plain_json_output());
        assert!(!lex(&["select", "--data-format", "csv", "--no-color"]).plain_json_output());
        assert!(!lex(&["select", "--color"]).plain_json_output());
        assert!(lex(&["select", "--no-color"]).plain_json_output());
        assert!(lex(&["select", "--output", "out.json", "--no-color"]).plain_json_output());
    }
}
