//! Native record dumps.
//!
//! An uncolored JSON or CSV `select` or `count` over a record table runs entirely
//! natively, the filter parses into the native subset, the database opens read-only
//! through the native store, and the output renders in one pass, projected or not, so
//! the interpreter never starts.
//!
//! The command carries no filter flag surface of its own. Every `--key value` token
//! pair lexes into the same wire pairs the server parses, and the native filter subset,
//! which the entities' `Filterable` derives generate, is the single authority on what
//! is admitted. Anything else, an unknown key, a construct outside the subset, an
//! unknown format, colorized terminal output, or a database the native store cannot
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
    /// Positional field specs, `field` or `field:alias`, in argument order.
    positional_fields: Vec<String>,
    /// The `--field` spec, a repeated flag keeping only its last value.
    flag_field: Option<String>,
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
                // A bare token is one positional field spec. The Python parser splits
                // positional lists on commas and reads bracketed values as JSON, so
                // only a plain spec lexes and anything fancier delegates.
                if token.contains(',') || token.starts_with('[') {
                    return None;
                }

                invocation.positional_fields.push(token.to_string());
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
                        "field" => invocation.flag_field = Some(value),
                        key => invocation.pairs.push((key.replace('-', "_"), value)),
                    }
                }
            }
        }

        Some(invocation)
    }

    /// The merged field projection as ordered `(field, alias)` pairs, empty when
    /// every field is output.
    ///
    /// Positional specs come first in argument order, then the `--field` spec, each
    /// splitting on its first colon and a repeated field name replacing the alias in
    /// place, which is how the Python command's dict merge behaves.
    fn projection(&self) -> Vec<(String, String)> {
        let mut projection: Vec<(String, String)> = Vec::new();
        let specs = self
            .positional_fields
            .iter()
            .chain(self.flag_field.as_ref());
        for spec in specs {
            let (field, alias) = match spec.split_once(':') {
                Some((field, alias)) => (field.to_string(), alias.to_string()),
                None => (spec.clone(), spec.clone()),
            };

            match projection.iter_mut().find(|(name, _)| *name == field) {
                Some((_, existing)) => *existing = alias,
                None => projection.push((field, alias)),
            }
        }

        projection
    }

    /// The format a native one-pass dump can render, `None` when the invocation must
    /// delegate, for an unknown format or colorized output. Mirrors the Python
    /// command's color resolution.
    fn dump_format(&self) -> Option<DumpFormat> {
        // A count carries no field surface, so a projection on one is an argument
        // error the Python command owns.
        if self.counting && (!self.positional_fields.is_empty() || self.flag_field.is_some()) {
            return None;
        }

        let format = match self.data_format.as_deref() {
            Some("json") => DumpFormat::Json,
            Some("csv") => DumpFormat::Csv,
            Some(_) => return None,
            None => match &self.output {
                Some(output) if output.extension().is_some_and(|suffix| suffix == "csv") => {
                    DumpFormat::Csv
                }
                _ => DumpFormat::Json,
            },
        };

        let plain = match self.color {
            Some(true) => false,
            Some(false) => true,
            None => {
                if std::env::var_os("FORCE_COLOR").is_some() {
                    return None;
                }

                std::env::var_os("NO_COLOR").is_some()
                    || self.output.is_some()
                    || !std::io::IsTerminal::is_terminal(&std::io::stdout())
            }
        };
        plain.then_some(format)
    }
}

/// The dump formats a native pass renders.
#[derive(Clone, Copy, Debug, PartialEq)]
enum DumpFormat {
    Json,
    Csv,
}

/// Attempt one record command natively, `false` meaning the caller delegates.
pub fn try_run(table: RecordTable, config: Option<&Path>, raw: &[OsString]) -> Result<bool> {
    let Some(invocation) = Invocation::lex(raw) else {
        return Ok(false);
    };
    let Some(format) = invocation.dump_format() else {
        return Ok(false);
    };

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
    let projection = invocation.projection();
    let rendered = runtime.block_on(async {
        if invocation.counting {
            store
                .count_filter(&filter)
                .await
                .map(|count| format!("{count}\n").into_bytes())
        } else {
            let records = store.fetch_filter(&filter).await?;
            let rendered = match (format, projection.is_empty()) {
                (DumpFormat::Json, true) => records.to_json_lines(),
                (DumpFormat::Json, false) => records.to_json_lines_projected(&projection),
                (DumpFormat::Csv, true) => Ok(records.to_csv_lines().into_bytes()),
                (DumpFormat::Csv, false) => records
                    .to_csv_lines_projected(&projection)
                    .map(String::into_bytes),
            };
            rendered.map_err(|error| ceres_database::Error::Decode(error.to_string()))
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
    fn projections_lex_and_merge_like_the_python_command() {
        let lex = |arguments: &[&str]| Invocation::lex(&raw(arguments)).unwrap();

        // Positional specs keep argument order, aliases split on the first colon.
        let invocation = lex(&["select", "content", "id:the id", "--no-color"]);
        assert_eq!(
            invocation.projection(),
            vec![
                ("content".to_string(), "content".to_string()),
                ("id".to_string(), "the id".to_string()),
            ]
        );
        assert_eq!(invocation.dump_format(), Some(DumpFormat::Json));

        // The last `--field` wins and overrides a positional alias in place.
        let invocation = lex(&[
            "select",
            "id:first",
            "level",
            "--field",
            "id",
            "--field=id:last",
            "--no-color",
        ]);
        assert_eq!(
            invocation.projection(),
            vec![
                ("id".to_string(), "last".to_string()),
                ("level".to_string(), "level".to_string()),
            ]
        );

        // The Python parser splits positional lists on commas and reads bracketed
        // values as JSON, so those delegate wholesale.
        assert!(Invocation::lex(&raw(&["select", "id,content"])).is_none());
        assert!(Invocation::lex(&raw(&["select", "[\"id\"]"])).is_none());

        // A count has no field surface, so projecting one delegates.
        assert_eq!(
            lex(&["count", "--field", "id", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(lex(&["count", "id", "--no-color"]).dump_format(), None);
    }

    #[test]
    fn projection_format_and_color_gate_the_native_path() {
        let lex = |arguments: &[&str]| Invocation::lex(&raw(arguments)).unwrap();

        assert_eq!(
            lex(&["select", "--field", "id", "--no-color"]).dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&["select", "id", "--no-color"]).dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&["select", "--data-format", "csv", "--no-color"]).dump_format(),
            Some(DumpFormat::Csv)
        );
        assert_eq!(
            lex(&["select", "--output", "rows.csv"]).dump_format(),
            Some(DumpFormat::Csv)
        );
        assert_eq!(
            lex(&["select", "--output", "rows.json"]).dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&["select", "--data-format", "yaml", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(lex(&["select", "--color"]).dump_format(), None);
        assert_eq!(
            lex(&["select", "--no-color"]).dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&["select", "--output", "out.json", "--no-color"]).dump_format(),
            Some(DumpFormat::Json)
        );
    }
}
