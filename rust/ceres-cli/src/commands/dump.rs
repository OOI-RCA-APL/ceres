//! What a table command means, once its arguments are parsed.
//!
//! Record and entity commands take the same verbs over the same controls, because
//! [`surface`] generates both command groups from one template. Reading an invocation,
//! opening the store, and writing the output are therefore shared, and each table family
//! adds only what its own rows mean.
//!
//! The surface has already rejected an unknown key, a missing value, and a flag on a
//! verb that does not take it, so nothing here re-checks any of that. What is left is
//! the invocation's meaning, and the native filter subset the entities' `Filterable`
//! derives generate is the single authority on which of those meanings compile.

use std::io::Write;
use std::path::{Path, PathBuf};

use ceres_config::DatabaseConfig;
use ceres_database::{Conflict, LoadFormat, RecordStore};
use clap::ArgMatches;

use crate::commands::surface::{self, Table};
use crate::error::Result;

/// The output projection a verb asked for, as ordered `(field, alias)` pairs.
///
/// Positional specs come first in argument order, then the `--field` options. Each
/// splits on its first colon, a repeated field name replaces the alias in place, and a
/// spec carrying commas names several fields at once, which is how a projection is
/// written when it is being typed rather than generated.
fn projection(matches: &ArgMatches) -> Vec<(String, String)> {
    let read = |id| {
        matches
            .try_get_many::<String>(id)
            .ok()
            .flatten()
            .into_iter()
            .flatten()
    };

    let mut projection: Vec<(String, String)> = Vec::new();
    for spec in read("fields").chain(read("field")) {
        for spec in spec
            .split(',')
            .map(str::trim)
            .filter(|spec| !spec.is_empty())
        {
            let (field, alias) = match spec.split_once(':') {
                Some((field, alias)) => (field, alias),
                None => (spec, spec),
            };

            match projection.iter_mut().find(|(name, _)| name == field) {
                Some((_, existing)) => *existing = alias.to_string(),
                None => projection.push((field.to_string(), alias.to_string())),
            }
        }
    }

    projection
}

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
    /// The verb one declared subcommand name means.
    pub(crate) fn parse(name: &str) -> Option<Self> {
        Some(match name {
            "select" => Self::Select,
            "count" => Self::Count,
            "any" => Self::Any,
            "create" => Self::Create,
            "update" => Self::Update,
            "delete" => Self::Delete,
            "load" => Self::Load,
            "follow" => Self::Follow,
            _ => return None,
        })
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

/// What an invocation asked for, read off the parsed arguments.
///
/// The surface the arguments were parsed against already rejected an unknown key, a
/// missing value, and a flag on a verb that does not take it, so nothing here has to
/// re-check any of that. What is left is the invocation's meaning.
#[derive(Debug, Default, PartialEq)]
pub(crate) struct Invocation {
    pub(crate) verb: Verb,
    /// The filter's wire pairs, or a create's field values.
    pub(crate) pairs: Vec<(String, String)>,
    pub(crate) output: Option<PathBuf>,
    pub(crate) data_format: Option<String>,
    /// Whether a CSV dump carries its header row.
    pub(crate) header: bool,
    /// Whether to ask before a write goes through.
    pub(crate) confirm: bool,
    /// Whether `--collect` asked for the affected rows instead of a count.
    pub(crate) collect: bool,
    /// The `--assign` object an update carries, as its raw YAML or JSON text.
    pub(crate) assign: Option<String>,
    /// The `--on-conflict` mode a load resolves collisions with.
    pub(crate) on_conflict: Option<String>,
    /// The file a load reads.
    pub(crate) path: Option<PathBuf>,
    /// The output projection as ordered `(field, alias)` pairs, empty for every field.
    pub(crate) projection: Vec<(String, String)>,
}

impl Invocation {
    /// Read one parsed invocation of a table verb.
    pub(crate) fn read(table: Table, verb: Verb, matches: &ArgMatches) -> Self {
        let text = |id: &str| matches.try_get_one::<String>(id).ok().flatten().cloned();
        let flag = |id: &str| matches.try_get_one::<bool>(id).ok().flatten().copied();

        // A filtered verb reads the table's filter keys and a create reads its columns,
        // which are different surfaces over the same table. A load names a file rather
        // than either.
        let keys = match verb {
            Verb::Create => table.columns(),
            Verb::Load => Vec::new(),
            _ => table.keys(),
        };

        Self {
            verb,
            pairs: surface::pairs(&keys, matches),
            output: text("output").map(PathBuf::from),
            data_format: text("data_format"),
            // A header is written unless it was turned off, which is what makes a CSV
            // dump readable by default and pipeable on request.
            header: !flag("no-header").unwrap_or(false),
            // A filtered write asks first unless it was told not to. Nothing about the
            // environment turns the question off, because a script that would have been
            // stopped by the prompt has to keep being stopped by it.
            confirm: !flag("no-confirm").unwrap_or(false),
            collect: flag("collect").unwrap_or(false),
            assign: text("assign"),
            on_conflict: text("on_conflict"),
            path: text("path").map(PathBuf::from),
            projection: projection(matches),
        }
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
    /// it writes rather than holding the whole thing.
    pub(crate) fn load_source(
        &self,
    ) -> std::result::Result<(std::io::BufReader<std::fs::File>, LoadFormat), String> {
        let path = self.path.as_deref().expect("a load names its file");
        let format = match &self.data_format {
            Some(named) => LoadFormat::parse(named),
            // An unnamed format comes from the extension.
            None => path
                .extension()
                .and_then(|suffix| suffix.to_str())
                .and_then(LoadFormat::infer),
        };
        let Some(format) = format else {
            return Err(format!(
                "Cannot tell what shape {} is in. Pass --data-format json or --data-format csv.",
                path.display()
            ));
        };

        let file = std::fs::File::open(path)
            .map_err(|error| format!("Cannot read {}. {error}", path.display()))?;
        Ok((std::io::BufReader::new(file), format))
    }

    /// The shape a dump renders in.
    ///
    /// A named format is taken as given, and a destination's suffix decides when none was
    /// named. What is left is a dump nobody said anything about, which becomes a table
    /// when there is someone there to read it and JSON lines otherwise. A person at a
    /// terminal wants columns and a pipe wants one object per line, so neither has to ask
    /// for what they were going to want anyway.
    pub(crate) fn dump_format(&self, color: Option<bool>) -> DumpFormat {
        match self.data_format.as_deref() {
            Some("csv") => return DumpFormat::Csv,
            Some(_) => return DumpFormat::Json,
            None => {}
        }

        if let Some(output) = &self.output {
            return match output.extension() {
                Some(suffix) if suffix == "csv" => DumpFormat::Csv,
                _ => DumpFormat::Json,
            };
        }

        if watched(color) {
            DumpFormat::Table
        } else {
            DumpFormat::Json
        }
    }
}

/// Whether output is going somewhere a person is reading it right now.
pub(crate) fn watched(color: Option<bool>) -> bool {
    match color {
        Some(color) => color,
        None if std::env::var_os("NO_COLOR").is_some() => false,
        None if std::env::var_os("FORCE_COLOR").is_some() => true,
        None => std::io::IsTerminal::is_terminal(&std::io::stdout()),
    }
}

/// The dump formats a native pass renders.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum DumpFormat {
    Json,
    Csv,
    /// Columns drawn in a box, for a dump someone is reading rather than piping.
    ///
    /// Every row has to be in hand before the first line can be drawn, because a column
    /// is only as wide as its widest cell, so this is the one shape that does not stream.
    Table,
}

/// What a native pass produced, ahead of writing it.
pub(crate) enum Rendered {
    Bytes(Vec<u8>),
    Text(String),
    /// An existence answer, which prints like Python's `bool` and sets the exit status.
    Exists(bool),
    /// A stream that already reached the output, leaving nothing more to write.
    Written,
    /// A write the reader declined at the prompt, which changed nothing.
    Declined,
    /// A stream that failed after it had already written.
    ///
    /// This is the one place a native pass reports for itself, because delegating would
    /// mean Python writing a second copy of a dump the caller has already seen part of.
    Failed(String),
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
            Self::Written | Self::Failed(_) | Self::Declined => Vec::new(),
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
    /// Whether every chunk is held rather than only the most recent one.
    accumulate: bool,
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
            accumulate: false,
        }
    }

    /// A sink that writes each chunk as it arrives, for a live stream.
    pub(crate) fn live(output: Option<&'a Path>, header: bool) -> Self {
        Self {
            hold: false,
            ..Self::new(output, header)
        }
    }

    /// A sink that holds every chunk and writes none of them.
    ///
    /// A table cannot be drawn until its widest cell is known, so the shape that draws
    /// one has to have the whole result before it writes a byte. Holding it here keeps
    /// the driver and the renderers the same as for the shapes that do stream.
    pub(crate) fn collecting() -> Self {
        Self {
            accumulate: true,
            ..Self::new(None, false)
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
        if self.accumulate {
            self.held
                .get_or_insert_default()
                .extend_from_slice(&rendered);
            return Ok(());
        }

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

/// Draw rendered JSON lines as a table.
///
/// The rows arrive already rendered and already projected, so the columns are whatever
/// the rows carry, in the order the first one lists them. A row missing a column leaves
/// its cell empty rather than shifting the rest along.
pub(crate) fn tabulate(rendered: &[u8], color: bool) -> String {
    use serde_json::{Map, Value};

    let rows: Vec<Map<String, Value>> = rendered
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .filter_map(|line| serde_json::from_slice(line).ok())
        .collect();

    let mut columns: Vec<String> = Vec::new();
    for row in &rows {
        for name in row.keys() {
            if !columns.iter().any(|column| column == name) {
                columns.push(name.clone());
            }
        }
    }

    // An empty result still says so, which is the difference between "nothing matched"
    // and "something went wrong".
    if columns.is_empty() {
        return "No rows.\n".to_string();
    }

    let mut table = crate::output::Table::new(None);
    for column in &columns {
        table.column(column.clone());
    }

    for row in &rows {
        table.row(columns.iter().map(|column| match row.get(column) {
            Some(Value::String(text)) => text.clone(),
            Some(Value::Null) | None => String::new(),
            Some(value) => value.to_string(),
        }));
    }

    // The renderer draws the box without a trailing newline, which a table written to a
    // terminal needs so the next prompt starts on its own line.
    format!("{}\n", table.render(color))
}

/// Draw a rendered result as a table, when a table is the shape asked for.
///
/// Every shape but a table is already the bytes it will be written as, so this is where
/// the one that is not becomes them.
pub(crate) fn drawn(rendered: Rendered, format: DumpFormat, color: Option<bool>) -> Rendered {
    if format != DumpFormat::Table {
        return rendered;
    }

    match rendered {
        Rendered::Bytes(bytes) => Rendered::Text(tabulate(&bytes, watched(color))),
        // A result that reached the output already, or never produced one, has nothing
        // left to draw.
        other => other,
    }
}

/// Ask before a filtered write goes through, `false` meaning the reader declined.
///
/// The count is taken first, because "Delete 400 variables?" is a question that can be
/// answered and "Delete the matching variables?" is not. Anything but a yes is a no, so
/// a stray keypress cancels rather than proceeds.
///
/// With no terminal to ask at, the write is refused rather than assumed. A prompt is the
/// thing standing between a filter that matched more than its author expected and the
/// rows going away, and inferring consent from the absence of anyone to ask removes it
/// exactly where nobody is watching.
pub(crate) fn confirmed(
    verb: Verb,
    affected: u64,
    plural: &str,
) -> std::result::Result<bool, String> {
    use std::io::BufRead;

    let doing = match verb {
        Verb::Update => "Update",
        Verb::Delete => "Delete",
        _ => return Ok(true),
    };

    if !std::io::IsTerminal::is_terminal(&std::io::stdin()) {
        return Err(format!(
            "This would {} {affected} {plural}, and there is no terminal to confirm at. \
             Pass --no-confirm to go ahead without asking.",
            doing.to_lowercase()
        ));
    }

    let mut error = std::io::stderr();
    let asked = write!(error, "{doing} {affected} {plural}? [y/N] ").and_then(|()| error.flush());
    asked.map_err(|error| format!("Cannot ask for confirmation. {error}"))?;

    let mut answer = String::new();
    std::io::stdin()
        .lock()
        .read_line(&mut answer)
        .map_err(|error| format!("Cannot read an answer. {error}"))?;
    Ok(matches!(
        answer.trim().to_ascii_lowercase().as_str(),
        "y" | "yes"
    ))
}

/// Write what a pass produced, and answer whether the command was served.
///
/// An existence check reports through its exit status as well as its output, so it
/// writes first and then carries the status out.
pub(crate) fn deliver(invocation: &Invocation, rendered: Rendered) -> Result<bool> {
    match rendered {
        // A stream placed its own output, so there is nothing left to write.
        Rendered::Written => return Ok(true),
        // Declining changed nothing, and a command chained behind this one with `&&`
        // must not run as though the write had gone through.
        Rendered::Declined => return Err(crate::error::Exit::failed("Cancelled.")),
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
pub(crate) fn open_store(
    config: &DatabaseConfig,
    writing: bool,
) -> std::result::Result<RecordStore, String> {
    match config {
        DatabaseConfig::Sqlite(sqlite) => {
            // An in-memory database belongs to the process that made it, and this is a
            // different process, so there is nothing here to read or write. Saying so
            // beats reporting an empty table as though it were the answer.
            if sqlite.is_memory() {
                return Err(
                    "This project's database is in memory, which lives only inside the                      engine's own process. Point `database.path` at a file to read it from                      here."
                        .to_string(),
                );
            }

            let path = existing(sqlite.path.as_deref())?;
            if writing {
                RecordStore::sqlite_writable(&path)
            } else {
                RecordStore::sqlite(&path)
            }
            .map_err(|error| format!("Cannot open {path}. {error}"))
        }
        DatabaseConfig::Turso(turso) => {
            let path = existing(turso.path.as_deref())?;
            Ok(RecordStore::turso(&path, turso.mvcc))
        }
        DatabaseConfig::Postgres(postgres) => {
            // Server settings shape what a query sees, `search_path` above all, so they
            // are forwarded. Any other driver argument is a Python library's own, and
            // guessing at one would silently change how the connection behaves.
            let mut settings = Vec::new();
            for (key, value) in &postgres.shared.engine {
                if key != "connect_args" {
                    return Err(unsupported(key));
                }

                let Some(arguments) = value.as_object() else {
                    return Err(unsupported(key));
                };
                for (name, value) in arguments {
                    if name != "server_settings" {
                        return Err(unsupported(name));
                    }

                    let Some(held) = value.as_object() else {
                        return Err(unsupported(name));
                    };
                    for (setting, text) in held {
                        let Some(text) = text.as_str() else {
                            return Err(unsupported(setting));
                        };
                        settings.push((setting.clone(), text.to_string()));
                    }
                }
            }

            // Connection string parameters carry through by name, so a configuration
            // naming `sslmode` connects the way it says it does.
            let mut parameters = Vec::new();
            for (key, value) in postgres.shared.query.iter().flatten() {
                for held in value.as_slice() {
                    parameters.push((key.clone(), held.clone()));
                }
            }

            RecordStore::postgres(
                &postgres.host,
                postgres.port,
                &postgres.database,
                &postgres.user,
                postgres.password.as_ref().map(|secret| secret.expose()),
                settings,
                parameters,
            )
            .map_err(|error| error.to_string())
        }
    }
}

/// What to say about a driver argument this cannot reproduce.
fn unsupported(key: &str) -> String {
    format!(
        "The database configuration sets `{key}`, which is an argument for a Python          database library rather than something this connects with. Remove it, or move          what it does into `connect_args.server_settings`."
    )
}

/// Resolve a configured database path, which has to name a file that is there.
fn existing(path: Option<&Path>) -> std::result::Result<String, String> {
    let Some(path) = path else {
        return Err(
            "This project's database configuration names no path, so there is no file to              open."
                .to_string(),
        );
    };

    let absolute = std::path::absolute(path)
        .map_err(|error| format!("Cannot resolve {}. {error}", path.display()))?;
    if !absolute.is_file() {
        return Err(format!(
            "There is no database at {}. Run `ceres database migrate` to create it.",
            absolute.display()
        ));
    }

    Ok(absolute.to_string_lossy().into_owned())
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
    fn an_existence_answer_carries_its_status_as_well_as_its_output() {
        // An existence check is written to be used in a shell condition, so the exit
        // status is the answer and the printed word is a convenience.
        assert_eq!(Rendered::Exists(true).exists(), Some(true));
        assert_eq!(Rendered::Exists(false).exists(), Some(false));
        assert_eq!(Rendered::Text("3\n".to_string()).exists(), None);
        assert_eq!(Rendered::Exists(true).into_bytes(), b"true\n");
        assert_eq!(Rendered::Exists(false).into_bytes(), b"false\n");
    }

    #[test]
    fn a_load_infers_its_shape_and_says_so_when_it_cannot() {
        let directory = tempfile::tempdir().unwrap();
        let rows = directory.path().join("rows.jsonl");
        std::fs::write(&rows, "{}\n").unwrap();

        let invocation = Invocation {
            path: Some(rows.clone()),
            ..Invocation::default()
        };
        let (_, format) = invocation.load_source().unwrap();
        assert_eq!(format, LoadFormat::Json);

        // A named format wins over the suffix, which is how a file with no useful
        // extension is loaded at all.
        let named = Invocation {
            path: Some(rows.clone()),
            data_format: Some("csv".to_string()),
            ..Invocation::default()
        };
        let (_, format) = named.load_source().unwrap();
        assert_eq!(format, LoadFormat::Csv);

        // A suffix that names nothing is reported here, with the fix in the message,
        // rather than handed to another process to explain.
        let opaque = directory.path().join("rows.dat");
        std::fs::write(&opaque, "{}\n").unwrap();
        let refused = Invocation {
            path: Some(opaque),
            ..Invocation::default()
        }
        .load_source()
        .unwrap_err();
        assert!(refused.contains("--data-format"), "{refused}");

        // So is a file that is not there.
        let missing = Invocation {
            path: Some(directory.path().join("absent.jsonl")),
            ..Invocation::default()
        }
        .load_source()
        .unwrap_err();
        assert!(missing.contains("absent.jsonl"), "{missing}");
    }

    #[test]
    fn the_shape_comes_from_the_named_format_or_the_destination() {
        let shape = |data_format: Option<&str>, output: Option<&str>| {
            Invocation {
                data_format: data_format.map(str::to_string),
                output: output.map(PathBuf::from),
                ..Invocation::default()
            }
            // Nobody is reading, which is what a pipe or a redirect looks like.
            .dump_format(Some(false))
        };

        assert_eq!(shape(None, None), DumpFormat::Json);
        assert_eq!(shape(None, Some("rows.csv")), DumpFormat::Csv);
        assert_eq!(shape(None, Some("rows.json")), DumpFormat::Json);
        assert_eq!(shape(Some("csv"), None), DumpFormat::Csv);
        // Naming a format is how a reader overrides what the suffix would have said.
        assert_eq!(shape(Some("json"), Some("rows.csv")), DumpFormat::Json);
    }

    #[test]
    fn a_dump_nobody_named_a_shape_for_follows_who_is_reading_it() {
        let dump = |output: Option<&str>, color| {
            Invocation {
                output: output.map(PathBuf::from),
                ..Invocation::default()
            }
            .dump_format(color)
        };

        // Someone at a terminal gets columns, and a pipe gets one object per line, so
        // neither has to ask for what they were going to want anyway.
        assert_eq!(dump(None, Some(true)), DumpFormat::Table);
        assert_eq!(dump(None, Some(false)), DumpFormat::Json);

        // A file is never a table, whatever the terminal is doing, because the point of
        // naming a destination is feeding it to something else later.
        assert_eq!(dump(Some("rows.json"), Some(true)), DumpFormat::Json);
        assert_eq!(dump(Some("rows.csv"), Some(true)), DumpFormat::Csv);
    }

    #[test]
    fn a_table_draws_the_columns_its_rows_carry() {
        let rendered = br#"{"name":"speed","value":5}
{"name":"label","value":"drive"}
"#;
        let drawn = tabulate(rendered, false);
        let expected = concat!(
            "\u{256d}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}",
            "\u{252c}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{256e}\n",
            "\u{2502} name  \u{2502} value \u{2502}\n",
            "\u{251c}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}",
            "\u{253c}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2524}\n",
            "\u{2502} speed \u{2502} 5     \u{2502}\n",
            "\u{2502} label \u{2502} drive \u{2502}\n",
            "\u{2570}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}",
            "\u{2534}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{256f}\n",
        );
        assert_eq!(drawn, expected);

        // A string cell prints as its text rather than as quoted JSON, which is what
        // makes a table readable where JSON lines are exact.
        assert!(!drawn.contains('"'), "{drawn}");
    }

    #[test]
    fn a_table_of_nothing_says_so() {
        // An empty box would read as a rendering failure and a silent exit as a lost
        // result. Neither is what happened.
        assert_eq!(tabulate(b"", false), "No rows.\n");
    }
}
