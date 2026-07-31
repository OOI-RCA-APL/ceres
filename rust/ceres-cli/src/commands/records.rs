//! Native record dumps.
//!
//! An uncolored `select`, `count`, or `any` over a record table runs entirely natively,
//! the filter parses into the native subset, the database opens read-only through the
//! native store, and the output renders in one pass, projected or not, so the
//! interpreter never starts. An `any` reports through its exit status as well as its
//! output, one for no match, the way the Python command does.
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

/// The record verbs a native pass can serve.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
enum Verb {
    #[default]
    Select,
    Count,
    /// An existence check, which reports through its exit status as well as its output.
    Any,
    Update,
    Delete,
}

impl Verb {
    /// Whether the verb carries an output surface, which only `select` does.
    fn renders_records(self) -> bool {
        matches!(self, Self::Select)
    }

    /// Whether the verb writes, which decides the confirmation and transaction rules.
    fn writes(self) -> bool {
        matches!(self, Self::Update | Self::Delete)
    }
}

/// What a record invocation asked for, lexed without a declared flag surface.
#[derive(Debug, Default, PartialEq)]
struct Invocation {
    verb: Verb,
    /// The filter's wire pairs, every flag that is not an output control.
    pairs: Vec<(String, String)>,
    output: Option<PathBuf>,
    data_format: Option<String>,
    config: Option<PathBuf>,
    /// The explicit color choice, `--color` or `--no-color`.
    color: Option<bool>,
    /// The explicit header choice, `--header` or `--no-header`.
    header: Option<bool>,
    /// The explicit confirmation choice, `--confirm` or `--no-confirm`.
    confirm: Option<bool>,
    /// Whether `--collect` asked for the affected records instead of a count.
    collect: bool,
    /// The `--assign` object an update carries, as its raw YAML or JSON text.
    assign: Option<String>,
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
            verb: match tokens.next()?? {
                "select" => Verb::Select,
                "count" => Verb::Count,
                "any" => Verb::Any,
                "update" => Verb::Update,
                "delete" => Verb::Delete,
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
                "header" => invocation.header = Some(true),
                "no-header" => invocation.header = Some(false),
                "confirm" => invocation.confirm = Some(true),
                "no-confirm" => invocation.confirm = Some(false),
                "collect" => invocation.collect = true,
                "no-collect" => invocation.collect = false,
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
                        "assign" => invocation.assign = Some(value),
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
        // Only `select` renders records. Every other verb prints one scalar, so a field
        // selection, an output file, a format, or a header choice on one either is an
        // argument error Python owns or is a rendering the native path has no reason to
        // reproduce.
        if !self.verb.renders_records()
            && (!self.positional_fields.is_empty()
                || self.flag_field.is_some()
                || self.output.is_some()
                || self.data_format.is_some()
                || self.header.is_some())
        {
            return None;
        }

        if self.verb.writes() {
            // An `update` needs its assignments, and only an `update` takes them.
            if self.assign.is_some() != matches!(self.verb, Verb::Update) {
                return None;
            }

            // Confirmation prompts and `--collect` streams both stay in Python. The
            // prompt would duplicate a user interaction the binary has no business
            // reproducing, and it costs a counting round trip that dwarfs the startup
            // this path saves. Requiring `--no-confirm` also keeps the rollback rule
            // honest, since delegating after a rollback would otherwise re-prompt.
            if self.confirm != Some(false) || self.collect {
                return None;
            }
        } else if self.assign.is_some() || self.confirm.is_some() || self.collect {
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
    let Some(store) = open_store(&meta.database, invocation.verb.writes()) else {
        return Ok(false);
    };

    drop(guard);

    // The whole result renders before anything writes, so a failure here can still
    // delegate without having produced partial output.
    let projection = invocation.projection();
    let header = invocation.header.unwrap_or(true);
    let rendered = runtime.block_on(async {
        match invocation.verb {
            Verb::Count => store
                .count_filter(&filter)
                .await
                .map(|count| Rendered::Text(format!("{count}\n"))),
            Verb::Any => store.any_filter(&filter).await.map(Rendered::Exists),
            Verb::Delete => store
                .delete_filter(&filter)
                .await
                .map(|affected| Rendered::Text(format!("{affected}\n"))),
            Verb::Update => {
                let assign = invocation
                    .assign
                    .as_deref()
                    .expect("an update carries its assignments");
                store.update_filter(&filter, assign).await.map(|affected| {
                    // Assignments the encoder refuses leave the table untouched, so the
                    // command delegates and Python owns the outcome.
                    affected.map_or(Rendered::Delegate, |affected| {
                        Rendered::Text(format!("{affected}\n"))
                    })
                })
            }
            Verb::Select => {
                let records = store.fetch_filter(&filter).await?;
                let rendered = match (format, projection.is_empty()) {
                    (DumpFormat::Json, true) => records.to_json_lines(),
                    (DumpFormat::Json, false) => records.to_json_lines_projected(&projection),
                    (DumpFormat::Csv, true) => Ok(records.to_csv_lines(header).into_bytes()),
                    (DumpFormat::Csv, false) => records
                        .to_csv_lines_projected(&projection, header)
                        .map(String::into_bytes),
                };
                rendered
                    .map(Rendered::Bytes)
                    .map_err(|error| ceres_database::Error::Decode(error.to_string()))
            }
        }
    });
    let Ok(rendered) = rendered else {
        return Ok(false);
    };
    // A pass that decided mid-flight it cannot serve the command wrote nothing and
    // changed nothing, so it delegates like any other refusal.
    if matches!(rendered, Rendered::Delegate) {
        return Ok(false);
    }

    // An existence check reports through its exit status as well as its output, so it
    // writes first and then carries the status out.
    let exists = rendered.exists();
    write_output(invocation.output.as_deref(), &rendered.into_bytes())?;
    match exists {
        Some(false) => Err(crate::error::Exit::status(1)),
        _ => Ok(true),
    }
}

/// What a native pass produced, ahead of writing it.
enum Rendered {
    Bytes(Vec<u8>),
    Text(String),
    /// An existence answer, which prints like Python's `bool` and sets the exit status.
    Exists(bool),
    /// The pass cannot serve the command after all, having changed nothing.
    Delegate,
}

impl Rendered {
    /// The existence answer, `None` for everything that is not an existence check.
    fn exists(&self) -> Option<bool> {
        match self {
            Self::Exists(exists) => Some(*exists),
            _ => None,
        }
    }

    fn into_bytes(self) -> Vec<u8> {
        match self {
            Self::Bytes(bytes) => bytes,
            Self::Text(text) => text.into_bytes(),
            Self::Exists(true) => b"true\n".to_vec(),
            Self::Exists(false) => b"false\n".to_vec(),
            Self::Delegate => Vec::new(),
        }
    }
}

/// Open the native store for a configured database, `None` when it cannot join.
///
/// The rules mirror the Python layer's own native-pool gating, an in-memory or
/// unpathed file database is private to its instance, and a PostgreSQL configuration
/// carrying driver-specific connection arguments cannot be reproduced faithfully.
fn open_store(config: &DatabaseConfig, writing: bool) -> Option<RecordStore> {
    match config {
        DatabaseConfig::Sqlite(sqlite) => {
            if sqlite.is_memory() {
                return None;
            }

            let path = absolute_existing(sqlite.path.as_deref()?)?;
            if writing {
                RecordStore::sqlite_writable(&path).ok()
            } else {
                RecordStore::sqlite(&path).ok()
            }
        }
        DatabaseConfig::Turso(turso) => {
            // Turso keeps the Python write path until its native writer is wired.
            if writing {
                return None;
            }

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
    fn only_the_read_verbs_lex() {
        assert_eq!(
            Invocation::lex(&raw(&["select"])).unwrap().verb,
            Verb::Select
        );
        assert_eq!(
            Invocation::lex(&raw(&["count", "--limit", "5"]))
                .unwrap()
                .verb,
            Verb::Count
        );
        assert_eq!(Invocation::lex(&raw(&["any"])).unwrap().verb, Verb::Any);
        assert!(Invocation::lex(&raw(&["create"])).is_none());
        assert!(Invocation::lex(&raw(&[])).is_none());
    }

    #[test]
    fn write_verbs_require_no_confirm_and_a_matching_assignment() {
        let lex = |arguments: &[&str]| Invocation::lex(&raw(arguments)).unwrap();

        // The bare booleans lex as flags rather than swallowing the next token.
        let invocation = lex(&["delete", "--no-confirm", "--limit", "5", "--no-color"]);
        assert_eq!(invocation.confirm, Some(false));
        assert!(!invocation.collect);
        assert_eq!(
            invocation.pairs,
            vec![("limit".to_string(), "5".to_string())]
        );
        assert_eq!(invocation.dump_format(), Some(DumpFormat::Json));

        // A prompt or a collected stream stays in Python.
        assert_eq!(lex(&["delete", "--no-color"]).dump_format(), None);
        assert_eq!(
            lex(&["delete", "--confirm", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(
            lex(&["delete", "--no-confirm", "--collect", "--no-color"]).dump_format(),
            None
        );

        // An update needs assignments, and only an update takes them.
        assert_eq!(
            lex(&["update", "--no-confirm", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(
            lex(&[
                "update",
                "--no-confirm",
                "--assign",
                "{\"connection\": \"usb\"}",
                "--no-color",
            ])
            .dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&[
                "delete",
                "--no-confirm",
                "--assign",
                "{\"connection\": \"usb\"}",
                "--no-color",
            ])
            .dump_format(),
            None
        );
        assert_eq!(
            lex(&["select", "--assign", "{\"a\": 1}", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(
            lex(&["select", "--no-confirm", "--no-color"]).dump_format(),
            None
        );
    }

    #[test]
    fn an_existence_answer_prints_like_python_and_carries_a_status() {
        assert_eq!(Rendered::Exists(true).exists(), Some(true));
        assert_eq!(Rendered::Exists(false).exists(), Some(false));
        assert_eq!(Rendered::Text("3\n".to_string()).exists(), None);
        assert_eq!(Rendered::Exists(true).into_bytes(), b"true\n");
        assert_eq!(Rendered::Exists(false).into_bytes(), b"false\n");
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

        // Neither `count` nor `any` has an output surface, so fields, an output file, a
        // format, or a header choice on one delegates.
        for verb in ["count", "any"] {
            assert_eq!(
                lex(&[verb, "--field", "id", "--no-color"]).dump_format(),
                None
            );
            assert_eq!(lex(&[verb, "id", "--no-color"]).dump_format(), None);
            assert_eq!(lex(&[verb, "--output", "rows.json"]).dump_format(), None);
            assert_eq!(
                lex(&[verb, "--data-format", "csv", "--no-color"]).dump_format(),
                None
            );
            assert_eq!(
                lex(&[verb, "--no-header", "--no-color"]).dump_format(),
                None
            );
            assert_eq!(
                lex(&[verb, "--limit", "5", "--no-color"]).dump_format(),
                Some(DumpFormat::Json)
            );
        }

        // The header choice lexes as a bare boolean flag and stays native on select.
        let invocation = lex(&["select", "--no-header", "--output", "rows.csv"]);
        assert_eq!(invocation.header, Some(false));
        assert_eq!(invocation.dump_format(), Some(DumpFormat::Csv));
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
