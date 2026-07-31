//! The shared surface of a native table command.
//!
//! Record and entity commands take the same seven verbs over the same flags, because the
//! CLI generates both command groups from one template. The lexing, the rules deciding
//! whether a native pass may serve an invocation, the store opening, and the output
//! writing are therefore shared, and each table family adds only what its own rows mean.
//!
//! The command carries no filter flag surface of its own. Every `--key value` token pair
//! lexes into the same wire pairs the server parses, and the native filter subset, which
//! the entities' `Filterable` derives generate, is the single authority on what is
//! admitted. Anything else, an unknown key, a construct outside the subset, an unknown
//! format, colorized terminal output, or a database the native store cannot join,
//! delegates to the Python runtime, which either serves it or produces the canonical
//! error. Failures follow the same rule, the native attempt renders its whole output
//! before writing anything, and any error along the way delegates rather than surfacing a
//! message of its own.

use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};

use ceres_config::DatabaseConfig;
use ceres_database::{Arity, Conflict, FilterKey, LoadFormat, RecordStore};

use crate::error::Result;

/// The verbs a native pass can serve.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub(crate) enum Verb {
    #[default]
    Select,
    Count,
    /// An existence check, which reports through its exit status as well as its output.
    Any,
    Create,
    Update,
    Delete,
    /// A bulk load, whose arguments are a file rather than a filter.
    Load,
    /// A live stream of new rows, which reads from a running engine rather than the
    /// database and never finishes on its own.
    Follow,
}

impl Verb {
    /// Whether the verb carries an output surface, which the row-producing verbs do.
    pub(crate) fn renders_rows(self) -> bool {
        matches!(self, Self::Select | Self::Create | Self::Follow)
    }

    /// Whether the verb's result is one value rather than rows.
    ///
    /// A scalar takes a destination and nothing else. Selecting fields, naming a data
    /// format, or asking for a header row means nothing for a count or an existence
    /// check, and the commands declare no such flags.
    pub(crate) fn renders_scalar(self) -> bool {
        matches!(self, Self::Count | Self::Any)
    }

    /// Whether the verb reads a live stream from a running engine rather than the
    /// database, which only `follow` does.
    pub(crate) fn streams(self) -> bool {
        matches!(self, Self::Follow)
    }

    /// Whether the verb writes, which decides the confirmation and transaction rules.
    pub(crate) fn writes(self) -> bool {
        matches!(
            self,
            Self::Create | Self::Update | Self::Delete | Self::Load
        )
    }

    /// Whether the verb takes a filter, which every verb but `create` and `load` does.
    pub(crate) fn filters(self) -> bool {
        !matches!(self, Self::Create | Self::Load)
    }

    /// Whether a confirmation prompt gates the verb, which only the filtered writes have.
    pub(crate) fn confirms(self) -> bool {
        matches!(self, Self::Update | Self::Delete)
    }
}

/// What an invocation asked for, lexed without a declared flag surface.
#[derive(Debug, Default, PartialEq)]
pub(crate) struct Invocation {
    pub(crate) verb: Verb,
    /// The filter's wire pairs, every flag that is not an output control.
    pub(crate) pairs: Vec<(String, String)>,
    pub(crate) output: Option<PathBuf>,
    pub(crate) data_format: Option<String>,
    pub(crate) config: Option<PathBuf>,
    /// The explicit color choice, `--color` or `--no-color`.
    color: Option<bool>,
    /// The explicit header choice, `--header` or `--no-header`.
    pub(crate) header: Option<bool>,
    /// The explicit confirmation choice, `--confirm` or `--no-confirm`.
    confirm: Option<bool>,
    /// Whether `--collect` asked for the affected rows instead of a count.
    collect: bool,
    /// The `--assign` object an update carries, as its raw YAML or JSON text.
    pub(crate) assign: Option<String>,
    /// The `--on-conflict` mode a load carries.
    on_conflict: Option<String>,
    /// Positional field specs, `field` or `field:alias`, in argument order.
    ///
    /// A load takes one positional argument too, the file it reads.
    positional_fields: Vec<String>,
    /// The `--field` spec, a repeated flag keeping only its last value.
    flag_field: Option<String>,
}

impl Invocation {
    /// Lex raw arguments, `None` for anything the native path cannot represent.
    ///
    /// `keys` is the table's filter surface, generated from the entity's fields, each
    /// carrying the argument form its family gives it. Every form is decided from that
    /// rather than guessed, because the Python CLI is generated from the same field
    /// definitions and a key's family is what decides how it arrives.
    pub(crate) fn lex(raw: &[OsString], keys: &[FilterKey]) -> Option<Self> {
        let mut tokens = raw.iter().map(|token| token.to_str());
        let mut invocation = Self {
            verb: match tokens.next()?? {
                "select" => Verb::Select,
                "count" => Verb::Count,
                "any" => Verb::Any,
                "create" => Verb::Create,
                "update" => Verb::Update,
                "delete" => Verb::Delete,
                "load" => Verb::Load,
                "follow" => Verb::Follow,
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
                    let key = flag.replace('-', "_");
                    let bare = key.strip_prefix("no_").unwrap_or(&key);
                    let arity = keys
                        .iter()
                        .find(|candidate| candidate.key == key || candidate.key == bare)
                        .map(|candidate| candidate.arity);

                    // A flag key is its own value, `--key` reading true and `--no-key`
                    // false. It never takes the argument that follows it, and it never
                    // takes an `=` value either, which its generated parser rejects.
                    if arity == Some(Arity::Flag) {
                        if value.is_some() {
                            return None;
                        }

                        let held = if key == bare { "true" } else { "false" };
                        invocation.pairs.push((bare.to_string(), held.to_string()));
                        continue;
                    }

                    if value.is_none() {
                        let next = tokens.peek()?.as_ref()?;
                        // A value is never another flag, and a lone hyphen leads one no
                        // more than a double one does.
                        if next.starts_with('-') {
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
                        "on-conflict" => invocation.on_conflict = Some(value),
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
    pub(crate) fn projection(&self) -> Vec<(String, String)> {
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

    /// The conflict mode a load resolves collisions with, `None` for a mode outside the
    /// three the command names.
    pub(crate) fn conflict(&self) -> Option<Conflict> {
        match self.on_conflict.as_deref() {
            Some(mode) => Conflict::parse(mode),
            None => Some(Conflict::Error),
        }
    }

    /// A load's input file, opened for reading, and the shape to read it in.
    ///
    /// The file is handed over open rather than read, because a load walks its source as
    /// it writes rather than holding the whole thing. `None` when the file will not open
    /// or the invocation names no format.
    pub(crate) fn load_source(&self) -> Option<(std::io::BufReader<std::fs::File>, LoadFormat)> {
        let path = Path::new(self.positional_fields.first()?);
        let format = match &self.data_format {
            Some(named) => LoadFormat::parse(named)?,
            // An unnamed format comes from the extension, and one naming no format is an
            // error the Python command owns.
            None => LoadFormat::infer(path.extension()?.to_str()?)?,
        };
        // A file the native path cannot open is the Python command's error to report,
        // whether it is missing or unreadable.
        let file = std::fs::File::open(path).ok()?;
        Some((std::io::BufReader::new(file), format))
    }

    /// The format a native one-pass dump can render, `None` when the invocation must
    /// delegate, for an unknown format or colorized output. Mirrors the Python
    /// command's color resolution.
    pub(crate) fn dump_format(&self) -> Option<DumpFormat> {
        // Only `select` takes its field selection positionally. A load takes one
        // positional argument of its own, the file it reads, and every other verb takes
        // none, so a stray one is an argument error Python owns.
        let positionals = match self.verb {
            Verb::Select | Verb::Follow => usize::MAX,
            Verb::Load => 1,
            _ => 0,
        };
        if self.positional_fields.len() > positionals {
            return None;
        }

        // `select` and `create` render rows, and `count` and `any` render one value,
        // which takes a destination and nothing else. Everything left prints a scalar it
        // gives no control over, so any output flag on one is an argument error Python
        // owns. A load is the exception among those, its `--data-format` naming the shape
        // of the file it reads rather than the shape of its output.
        if !self.verb.renders_rows()
            && (self.flag_field.is_some()
                || self.header.is_some()
                || (self.data_format.is_some() && self.verb != Verb::Load)
                || (self.output.is_some() && !self.verb.renders_scalar()))
        {
            return None;
        }

        // An `update` needs its assignments, a load needs its file, and only they take
        // them.
        if self.assign.is_some() != (self.verb == Verb::Update) {
            return None;
        }

        if self.on_conflict.is_some() && self.verb != Verb::Load {
            return None;
        }

        if self.verb.confirms() {
            // Confirmation prompts and `--collect` streams both stay in Python. The
            // prompt would duplicate a user interaction the binary has no business
            // reproducing, and it costs a counting round trip that dwarfs the startup
            // this path saves. Requiring `--no-confirm` also keeps the rollback rule
            // honest, since delegating after a rollback would otherwise re-prompt.
            if self.confirm != Some(false) || self.collect {
                return None;
            }
        } else if self.confirm.is_some() || self.collect {
            return None;
        }

        // A load carries no filter, so it names its file and nothing else.
        if self.verb == Verb::Load && (self.positional_fields.len() != 1 || !self.pairs.is_empty())
        {
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
pub(crate) enum DumpFormat {
    Json,
    Csv,
}

/// What a native pass produced, ahead of writing it.
pub(crate) enum Rendered {
    Bytes(Vec<u8>),
    Text(String),
    /// An existence answer, which prints like Python's `bool` and sets the exit status.
    Exists(bool),
    /// A stream that already reached the output, leaving nothing more to write.
    Written,
    /// A stream that failed after it had already written.
    ///
    /// This is the one place a native pass reports for itself, because delegating would
    /// mean Python writing a second copy of a dump the caller has already seen part of.
    Failed(String),
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
            Self::Written | Self::Failed(_) | Self::Delegate => Vec::new(),
        }
    }
}

/// A streaming output target that holds its first chunk back.
///
/// Chunks render and write as the driver yields them, so a dump of any size holds one
/// chunk rather than the whole table. The first one is kept rather than written, which
/// is what keeps the delegation rule intact. Everything that makes a native pass refuse
/// is known before any row arrives, and a result small enough to fit one chunk, which is
/// nearly every interactive dump, still reaches the end having written nothing, so it
/// delegates exactly as it did before anything streamed.
///
/// Past the first chunk there is no taking it back, and a failure there is a genuine
/// decode or write error rather than a refusal, which the caller reports as its own.
pub(crate) struct Sink<'a> {
    output: Option<&'a Path>,
    /// Whether the first chunk waits for a second before going out.
    ///
    /// A dump of a finished result holds it, so a refusal partway through still writes
    /// nothing. A live stream cannot, because the first row may be the only one for a
    /// long while and the point of following is seeing it arrive.
    hold: bool,
    /// The first chunk's bytes, until a second chunk forces them out.
    held: Option<Vec<u8>>,
    /// The destination, opened when the first write actually happens.
    destination: Option<Box<dyn Write>>,
    /// Whether a header row still has to be written, which only the first chunk does.
    heading: bool,
    /// Whether the reader went away, which ends the dump rather than failing it.
    broke: bool,
}

impl<'a> Sink<'a> {
    pub(crate) fn new(output: Option<&'a Path>, header: bool) -> Self {
        Self {
            output,
            hold: true,
            held: None,
            destination: None,
            heading: header,
            broke: false,
        }
    }

    /// A sink that writes each chunk as it arrives, for a live stream.
    pub(crate) fn live(output: Option<&'a Path>, header: bool) -> Self {
        Self {
            hold: false,
            ..Self::new(output, header)
        }
    }

    /// Whether this chunk should carry a header row, which only the first one does.
    pub(crate) fn heading(&mut self) -> bool {
        std::mem::take(&mut self.heading)
    }

    /// Whether anything has reached the output, past which a failure cannot delegate.
    pub(crate) fn wrote(&self) -> bool {
        self.destination.is_some()
    }

    /// Whether writing failed because the reader closed the pipe.
    ///
    /// A dump piped into something that stops reading, `head` being the usual one, ends
    /// where the reader stopped. That is the pipeline working, not the dump failing.
    pub(crate) fn broke(&self) -> bool {
        self.broke
    }

    /// Take one rendered chunk, writing the previous one out if there was one.
    pub(crate) fn push(&mut self, rendered: Vec<u8>) -> std::io::Result<()> {
        if !self.hold {
            return self.write(&rendered);
        }

        let Some(previous) = self.held.replace(rendered) else {
            return Ok(());
        };

        self.write(&previous)
    }

    /// Write the held chunk, if it was never forced out, and answer whether anything
    /// was written at all.
    ///
    /// A pass that only ever held one chunk has written nothing yet, so its caller is
    /// still free to delegate instead of finishing.
    pub(crate) fn finish(mut self) -> std::io::Result<Option<Vec<u8>>> {
        match self.destination {
            // Nothing went out, so the whole result is still the caller's to place.
            None => Ok(self.held),
            Some(_) => {
                if let Some(held) = self.held.take() {
                    self.write(&held)?;
                }

                Ok(None)
            }
        }
    }

    fn write(&mut self, bytes: &[u8]) -> std::io::Result<()> {
        if self.destination.is_none() {
            self.destination = Some(match self.output {
                Some(path) => Box::new(std::fs::File::create(path)?),
                None => Box::new(std::io::stdout()),
            });
        }

        let destination = self
            .destination
            .as_mut()
            .expect("the destination opened above");
        // A stream is read as it arrives, so each chunk leaves rather than waiting for
        // whatever the buffer would have collected behind it.
        let written = destination
            .write_all(bytes)
            .and_then(|()| destination.flush());
        if let Err(error) = &written
            && error.kind() == std::io::ErrorKind::BrokenPipe
        {
            self.broke = true;
        }

        written
    }
}

/// Wrap a write failure so it travels with the decode failures a stream can also hit.
pub(crate) fn written(error: std::io::Error) -> ceres_database::Error {
    ceres_database::Error::Decode(error.to_string())
}

/// Resolve a finished stream into what the caller should deliver.
///
/// A stream that failed having written nothing is a refusal like any other and hands the
/// whole command to Python. One that failed after writing cannot, so it reports, unless
/// what failed was the reader closing the pipe, which is where the dump was asked to end.
pub(crate) fn finish(
    sink: Sink<'_>,
    outcome: std::result::Result<(), ceres_database::Error>,
) -> std::result::Result<Rendered, ceres_database::Error> {
    match outcome {
        Ok(()) => match sink.finish() {
            // The whole result fit one chunk and is still unwritten, so it goes out the
            // way an unstreamed dump does, delegation included.
            Ok(Some(held)) => Ok(Rendered::Bytes(held)),
            Ok(None) => Ok(Rendered::Written),
            Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => Ok(Rendered::Written),
            Err(error) => Err(written(error)),
        },
        Err(_) if sink.broke() => Ok(Rendered::Written),
        Err(error) if sink.wrote() => Ok(Rendered::Failed(error.to_string())),
        Err(error) => Err(error),
    }
}

/// Write what a pass produced, and answer whether the command was served.
///
/// An existence check reports through its exit status as well as its output, so it
/// writes first and then carries the status out.
pub(crate) fn deliver(invocation: &Invocation, rendered: Rendered) -> Result<bool> {
    // A pass that decided mid-flight it cannot serve the command wrote nothing and
    // changed nothing, so it delegates like any other refusal.
    if matches!(rendered, Rendered::Delegate) {
        return Ok(false);
    }

    match rendered {
        // A stream placed its own output, so there is nothing left to write.
        Rendered::Written => return Ok(true),
        Rendered::Failed(message) => return Err(crate::error::Exit::failed(message)),
        _ => {}
    }

    let exists = rendered.exists();
    write_output(invocation.output.as_deref(), &rendered.into_bytes())?;
    match exists {
        Some(false) => Err(crate::error::Exit::status(1)),
        _ => Ok(true),
    }
}

/// Open the native store for a configured database, `None` when it cannot join.
///
/// The rules mirror the Python layer's own native-pool gating, an in-memory or
/// unpathed file database is private to its instance, and a PostgreSQL configuration
/// carrying driver-specific connection arguments cannot be reproduced faithfully.
pub(crate) fn open_store(config: &DatabaseConfig, writing: bool) -> Option<RecordStore> {
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

    /// Lex with no boolean keys, which is the record tables' surface.
    fn lex(arguments: &[&str]) -> Invocation {
        Invocation::lex(&raw(arguments), &[]).unwrap()
    }

    #[test]
    fn every_served_verb_lexes() {
        let verb = |arguments: &[&str]| lex(arguments).verb;

        assert_eq!(verb(&["select"]), Verb::Select);
        assert_eq!(verb(&["count", "--limit", "5"]), Verb::Count);
        assert_eq!(verb(&["any"]), Verb::Any);
        assert_eq!(verb(&["create", "--address", "@a"]), Verb::Create);
        assert_eq!(verb(&["load", "rows.jsonl"]), Verb::Load);
        assert_eq!(verb(&["follow"]), Verb::Follow);
        // A verb no command declares, and no verb at all.
        assert!(Invocation::lex(&raw(&["vacuum"]), &[]).is_none());
        assert!(Invocation::lex(&raw(&[]), &[]).is_none());
    }

    #[test]
    fn write_verbs_require_no_confirm_and_a_matching_assignment() {
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
    fn a_load_takes_one_file_and_a_conflict_mode() {
        let invocation = lex(&[
            "load",
            "rows.jsonl",
            "--on-conflict",
            "ignore",
            "--no-color",
        ]);
        assert_eq!(invocation.positional_fields, vec!["rows.jsonl".to_string()]);
        assert_eq!(invocation.conflict(), Some(Conflict::Ignore));
        assert_eq!(invocation.dump_format(), Some(DumpFormat::Json));

        // The default mode is the one the command declares, and an unnamed one delegates.
        assert_eq!(
            lex(&["load", "rows.jsonl"]).conflict(),
            Some(Conflict::Error)
        );
        assert_eq!(
            lex(&["load", "rows.jsonl", "--on-conflict", "replace"]).conflict(),
            None
        );

        // A load names its file and nothing else, so a filter, a second file, a missing
        // file, or an output surface all delegate.
        assert_eq!(lex(&["load", "--no-color"]).dump_format(), None);
        assert_eq!(
            lex(&["load", "one.jsonl", "two.jsonl", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(
            lex(&["load", "rows.jsonl", "--limit", "5", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(
            lex(&["load", "rows.jsonl", "--field", "id", "--no-color"]).dump_format(),
            None
        );
        assert_eq!(
            lex(&["load", "rows.jsonl", "--output", "out.json"]).dump_format(),
            None
        );

        // The input format names the shape of the file, so it stays native on a load
        // where it would be an argument error on the other scalar verbs.
        assert_eq!(
            lex(&["load", "rows.txt", "--data-format", "json", "--no-color"]).dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&["count", "--data-format", "json", "--no-color"]).dump_format(),
            None
        );

        // A conflict mode belongs to a load alone.
        assert_eq!(
            lex(&[
                "delete",
                "--no-confirm",
                "--on-conflict",
                "ignore",
                "--no-color"
            ])
            .dump_format(),
            None
        );
    }

    #[test]
    fn a_create_carries_its_field_values_and_an_output_surface() {
        let invocation = lex(&[
            "create",
            "--address",
            "@a",
            "--direction",
            "receive",
            "--data",
            "hi",
            "--no-color",
        ]);
        assert_eq!(
            invocation.pairs,
            vec![
                ("address".to_string(), "@a".to_string()),
                ("direction".to_string(), "receive".to_string()),
                ("data".to_string(), "hi".to_string()),
            ]
        );
        assert_eq!(invocation.dump_format(), Some(DumpFormat::Json));

        // The created row prints like a selected one, so the whole output surface
        // applies except the positional field list, which the create command lacks.
        assert_eq!(
            lex(&["create", "--address", "@a", "--field", "id", "--no-color"]).dump_format(),
            Some(DumpFormat::Json)
        );
        assert_eq!(
            lex(&["create", "--address", "@a", "--output", "row.csv"]).dump_format(),
            Some(DumpFormat::Csv)
        );
        assert_eq!(
            lex(&["create", "--address", "@a", "id", "--no-color"]).dump_format(),
            None
        );

        // A create writes one row without a prompt, so a confirmation choice on one is
        // an argument error Python owns.
        assert_eq!(
            lex(&["create", "--address", "@a", "--no-confirm", "--no-color"]).dump_format(),
            None
        );
    }

    #[test]
    fn a_sink_holds_one_chunk_so_a_small_dump_can_still_delegate() {
        // A result that fits one chunk never opens its destination, so the whole dump
        // comes back to the caller and a late refusal delegates exactly as it did
        // before anything streamed.
        let mut sink = Sink::new(None, true);
        sink.push(b"one\n".to_vec()).unwrap();
        assert!(!sink.wrote());
        assert_eq!(sink.finish().unwrap(), Some(b"one\n".to_vec()));

        // An empty result is the same, its rendered form being a header row or nothing.
        let sink = Sink::new(None, true);
        assert_eq!(sink.finish().unwrap(), None);
    }

    #[test]
    fn a_second_chunk_forces_the_first_one_out() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("rows.jsonl");

        let mut sink = Sink::new(Some(&path), true);
        sink.push(b"one\n".to_vec()).unwrap();
        sink.push(b"two\n".to_vec()).unwrap();
        // The first chunk went out to make room, so the pass is committed from here.
        assert!(sink.wrote());
        assert_eq!(std::fs::read(&path).unwrap(), b"one\n");

        // Finishing flushes whatever was still held, and leaves nothing for the caller.
        assert_eq!(sink.finish().unwrap(), None);
        assert_eq!(std::fs::read(&path).unwrap(), b"one\ntwo\n");
    }

    #[test]
    fn a_live_sink_writes_each_chunk_as_it_arrives() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("rows.jsonl");

        // A stream cannot hold its first row back, because it may be the only one for a
        // long while and seeing it arrive is the point of following.
        let mut sink = Sink::live(Some(&path), true);
        sink.push(b"one\n".to_vec()).unwrap();
        assert!(sink.wrote());
        assert_eq!(std::fs::read(&path).unwrap(), b"one\n");

        sink.push(b"two\n".to_vec()).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"one\ntwo\n");
        assert_eq!(sink.finish().unwrap(), None);
    }

    #[test]
    fn a_follow_lexes_with_the_selection_surface_a_select_has() {
        let invocation = lex(&["follow", "--address", "@a", "content", "--no-color"]);

        assert_eq!(invocation.verb, Verb::Follow);
        assert!(invocation.verb.streams());
        // It reads a running engine rather than the database, so it opens no store and
        // never takes the write path's confirmation rules.
        assert!(!invocation.verb.writes());
        assert!(invocation.verb.filters());
        assert!(!invocation.verb.confirms());
        assert_eq!(
            invocation.pairs,
            vec![("address".to_string(), "@a".to_string())]
        );
        assert_eq!(
            invocation.projection(),
            vec![("content".to_string(), "content".to_string())]
        );
        assert_eq!(invocation.dump_format(), Some(DumpFormat::Json));

        // The output surface a select has applies, and colorized output delegates.
        assert_eq!(
            lex(&["follow", "--data-format", "csv", "--no-color"]).dump_format(),
            Some(DumpFormat::Csv)
        );
        assert_eq!(lex(&["follow", "--color"]).dump_format(), None);
        // A confirmation or an assignment on a read is an argument error Python owns.
        assert_eq!(lex(&["follow", "--no-confirm"]).dump_format(), None);
        assert_eq!(
            lex(&["follow", "--assign", "{\"a\": 1}", "--no-color"]).dump_format(),
            None
        );
    }

    #[test]
    fn only_the_first_chunk_carries_a_header() {
        let mut sink = Sink::new(None, true);
        assert!(sink.heading());
        assert!(!sink.heading());

        // A dump that suppressed its header never asks for one.
        let mut sink = Sink::new(None, false);
        assert!(!sink.heading());
    }

    #[test]
    fn a_stream_delegates_before_its_first_write_and_reports_after() {
        let failure = || ceres_database::Error::Decode("unreadable row".to_string());

        // Nothing has been written, so the whole command is still Python's to serve.
        let sink = Sink::new(None, true);
        assert!(finish(sink, Err(failure())).is_err());

        // Past the first write there is no handing off, so the pass reports for itself
        // rather than letting Python print a second copy of a partial dump.
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("rows.jsonl");
        let mut sink = Sink::new(Some(&path), true);
        sink.push(b"one\n".to_vec()).unwrap();
        sink.push(b"two\n".to_vec()).unwrap();
        assert!(matches!(
            finish(sink, Err(failure())),
            Ok(Rendered::Failed(_))
        ));
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
        let invocation = lex(&[
            "select",
            "--address",
            "@sensor.temp",
            "--max-age=2h",
            "--order",
            "timestamp:desc",
            "--limit",
            "10",
        ]);

        assert!(
            invocation
                .pairs
                .contains(&("max_age".to_string(), "2h".to_string()))
        );
    }

    #[test]
    fn valueless_flags_delegate() {
        assert!(Invocation::lex(&raw(&["select", "--help"]), &[]).is_none());
        assert!(Invocation::lex(&raw(&["select", "--limit"]), &[]).is_none());
        assert!(Invocation::lex(&raw(&["select", "--limit", "--offset", "2"]), &[]).is_none());
    }

    #[test]
    fn projections_lex_and_merge_like_the_python_command() {
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
        assert!(Invocation::lex(&raw(&["select", "id,content"]), &[]).is_none());
        assert!(Invocation::lex(&raw(&["select", "[\"id\"]"]), &[]).is_none());

        // A count and an existence check render one value, so they take a destination
        // and nothing else. Fields, a format, or a header choice on one delegates.
        for verb in ["count", "any"] {
            assert_eq!(
                lex(&[verb, "--field", "id", "--no-color"]).dump_format(),
                None
            );
            assert_eq!(lex(&[verb, "id", "--no-color"]).dump_format(), None);
            assert!(
                lex(&[verb, "--output", "count.txt"])
                    .dump_format()
                    .is_some()
            );
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
