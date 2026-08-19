//! What a table command means, once its arguments are parsed.
//!
//! Record and entity commands take the same verbs over the same controls, because
//! [`surface`] generates both command groups from one template. Reading an invocation,
//! opening the store, and writing the output are therefore shared, and each table family
//! adds only what its own rows mean.
//!
//! The surface has already rejected an unknown key, a missing value, and a flag on a
//! verb that does not take it so nothing here re-checks any of that. What is left is
//! the invocation's meaning, and the native filter subset the entities'
//! [`Filterable`](ceres_entities::Filterable) derives generate is the single authority
//! on which of those meanings compile.

use std::io::Write;
use std::path::{Path, PathBuf};

use ceres_config::{DatabaseConfig, HashingConfig};
use ceres_database::{
    Argon2Params, Conflict, Credentials, Filter, Hashing, LoadFormat, RecordStore, Refusal, Tabled,
};
use ceres_entities::RenderRows;
use clap::ArgMatches;

use crate::commands::surface::{self, Table};
use crate::error::Result;
use crate::project::Project;

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
#[derive(Debug, Default, PartialEq)]
pub(crate) struct Invocation {
    pub(crate) verb: Verb,
    /// The filter's wire pairs, or a create's field values.
    pub(crate) pairs: Vec<(String, String)>,
    pub(crate) output: Option<PathBuf>,
    pub(crate) format: Option<String>,
    /// Whether a CSV dump carries its header row.
    pub(crate) header: bool,
    /// Whether to ask before a write goes through.
    pub(crate) confirm: bool,
    /// Whether `--collect` asked for the affected rows instead of a count.
    pub(crate) collect: bool,
    /// The `--set` object an update carries, as its raw YAML or JSON text.
    pub(crate) set: Option<String>,
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
        let (keys, shape) = match verb {
            Verb::Create => (table.columns(), surface::BooleanShape::Valued),
            Verb::Load => (Vec::new(), surface::BooleanShape::Bare),
            _ => (table.keys(), surface::BooleanShape::Bare),
        };

        Self {
            verb,
            pairs: surface::pairs(&keys, matches, shape),
            output: text("output").map(PathBuf::from),
            format: text("format"),
            // A header is written unless it was turned off, which makes a CSV
            // dump readable by default and pipeable on request.
            header: !flag("no-header").unwrap_or(false),
            // A filtered write asks first unless it was told not to. Nothing about the
            // environment turns the question off because a script that would have been
            // stopped by the prompt has to keep being stopped by it.
            confirm: !flag("no-confirm").unwrap_or(false),
            collect: flag("collect").unwrap_or(false),
            set: text("set"),
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
    /// The file is handed over open rather than read because a load walks its source as
    /// it writes rather than holding the whole thing.
    pub(crate) fn load_source(
        &self,
    ) -> std::result::Result<(std::io::BufReader<std::fs::File>, LoadFormat), String> {
        let path = self.path.as_deref().expect("a load names its file");
        let format = match &self.format {
            Some(named) => LoadFormat::parse(named),
            // An unnamed format comes from the extension.
            None => path
                .extension()
                .and_then(|suffix| suffix.to_str())
                .and_then(LoadFormat::infer),
        };
        let Some(format) = format else {
            return Err(format!(
                "Cannot tell what shape {} is in. Pass --format json or --format csv.",
                path.display()
            ));
        };

        let file = std::fs::File::open(path)
            .map_err(|error| format!("Cannot read {}. {error}", path.display()))?;
        Ok((std::io::BufReader::new(file), format))
    }

    /// The shape a dump renders in.
    ///
    /// A named format is taken as given, and a destination's `.csv` suffix decides
    /// when none was named. Everything else is JSON lines regardless of the reader, so
    /// a script sees the same shape however the dump is run. Columns are only ever
    /// asked for, never inferred.
    pub(crate) fn dump_format(&self) -> DumpFormat {
        match self.format.as_deref() {
            Some("csv") => return DumpFormat::Csv,
            Some("table") => return DumpFormat::Table,
            Some(_) => return DumpFormat::Json,
            None => {}
        }

        match self.output.as_ref().and_then(|output| output.extension()) {
            Some(suffix) if suffix == "csv" => DumpFormat::Csv,
            _ => DumpFormat::Json,
        }
    }

    /// Whether this dump's output carries color.
    ///
    /// A dump named a file is never colored, whatever the terminal is doing, because the
    /// escape sequences would land in the file rather than on a screen.
    pub(crate) fn colored(&self, color: Option<bool>) -> bool {
        self.output.is_none() && colored(color)
    }
}

/// Whether color goes to standard output, the explicit flag winning over the environment.
///
/// Only color asks whether anyone is there to see it. The shape a dump takes does not
/// because a script reads the same JSON whether or not it happens to have a terminal.
pub(crate) fn colored(color: Option<bool>) -> bool {
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
    /// Every row has to be in hand before the first line can be drawn because a column
    /// is only as wide as its widest cell so this is the one shape that does not stream.
    Table,
}

impl DumpFormat {
    /// Color one rendered chunk, for the shapes that carry color as they are written.
    ///
    /// This runs per chunk rather than once at the end so a dump too large to hold
    /// arrives colored the whole way down. A table takes its color when drawn, because
    /// it cannot be drawn until the last row is in, and CSV takes none, being a shape
    /// meant for machines.
    pub(crate) fn paint(self, bytes: Vec<u8>, colored: bool) -> Vec<u8> {
        if colored && self == Self::Json {
            crate::highlight::painted(bytes)
        } else {
            bytes
        }
    }
}

/// What a native pass produced, ahead of writing it.
pub(crate) enum Rendered {
    Bytes(Vec<u8>),
    /// A one-value answer, a count or a write's affected-row tally.
    ///
    /// It has no rows to pass through a chunk renderer so it is the one shape colored
    /// where it is written. A drawn table is already [`Self::Bytes`], colored when it
    /// was drawn.
    Text(String),
    /// An existence answer, which prints like Python's `bool` and sets the exit status.
    Exists(bool),
    /// A stream that already reached the output, leaving nothing more to write.
    Written,
    /// A write the reader declined at the prompt, which changed nothing.
    Declined,
    /// A stream that failed after it had already written.
    ///
    /// This is the one place a native pass reports for itself because delegating would
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

    /// Draw a rendered result as a table, when a table is the shape asked for.
    ///
    /// Every other shape is already its output bytes and was colored per chunk, so
    /// only a table renders here, being the one shape that needs the last row first.
    pub(crate) fn drawn(self, format: DumpFormat, colored: bool) -> Self {
        if format != DumpFormat::Table {
            return self;
        }

        match self {
            Self::Bytes(bytes) => Self::Bytes(tabulate(&bytes, colored).into_bytes()),
            // A result that reached the output already, or never produced one, has
            // nothing left to draw.
            other => other,
        }
    }
}

/// A streaming output target that holds its first chunk back.
///
/// Chunks render and write as the driver yields them so a dump of any size holds one
/// chunk rather than the whole table. Holding the first chunk keeps failures clean. A
/// result that fits one chunk, which is nearly every interactive dump, reaches the end
/// having written nothing so a refusal reports whole with no partial output.
///
/// Past the first chunk there is no taking it back. A failure there is a genuine
/// decode or write error rather than a refusal, which the caller reports as its own.
pub(crate) struct Sink<'a> {
    output: Option<&'a Path>,
    /// Whether the first chunk waits for a second before going out.
    ///
    /// A dump of a finished result holds it so a refusal partway through still writes
    /// nothing. A live stream cannot because the first row may be the only one for a
    /// long while and the point of following is seeing it arrive.
    hold: bool,
    /// The first chunk's bytes, until a second chunk forces them out.
    held: Option<Vec<u8>>,
    /// The destination, opened when the first write actually happens.
    ///
    /// `Send` because the store hands its chunks over from the executor's threads rather
    /// than the caller's so a sink has to be able to travel there.
    destination: Option<Box<dyn Write + Send>>,
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
    /// A table cannot be drawn until its widest cell is known so the shape that draws
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

    /// Whether anything has reached the output, past which a failure reports rather
    /// than refusing cleanly.
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

    /// Resolve a finished stream into what the caller should deliver.
    ///
    /// A stream that failed having written nothing is a refusal like any other and
    /// reports whole, with no partial output ahead of it. One that failed after writing
    /// cannot so it reports what failed, unless what failed was the reader closing the
    /// pipe, which is where the dump was asked to end.
    pub(crate) fn resolve(
        self,
        outcome: std::result::Result<(), ceres_database::Error>,
    ) -> std::result::Result<Rendered, ceres_database::Error> {
        match outcome {
            Ok(()) => match self.finish() {
                // The whole result fit one chunk and is still unwritten so it goes out
                // the way an unstreamed dump does.
                Ok(Some(held)) => Ok(Rendered::Bytes(held)),
                Ok(None) => Ok(Rendered::Written),
                Err(error) if error.kind() == std::io::ErrorKind::BrokenPipe => {
                    Ok(Rendered::Written)
                }
                Err(error) => Err(written(error)),
            },
            Err(_) if self.broke() => Ok(Rendered::Written),
            Err(error) if self.wrote() => Ok(Rendered::Failed(error.to_string())),
            Err(error) => Err(error),
        }
    }

    /// Write the held chunk, if it was never forced out, and answer whether anything
    /// was written at all.
    ///
    /// A pass that only ever held one chunk has written nothing yet so its result can
    /// go out whole the way an unstreamed dump's does.
    pub(crate) fn finish(mut self) -> std::io::Result<Option<Vec<u8>>> {
        match self.destination {
            // Nothing went out so the whole result is still the caller's to place.
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
        // A stream is read as it arrives so each chunk leaves rather than waiting for
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

/// Draw rendered JSON lines as a table.
///
/// The rows arrive already rendered and already projected so the columns are whatever
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
        table.row(columns.iter().map(|column| {
            // A column no row carries a value for is an empty cell rather than the word
            // "null", which is also what a stored null looks like, so neither is colored.
            let Some(value) = row.get(column).filter(|value| !value.is_null()) else {
                return crate::output::Cell::default();
            };

            let text = match value {
                // A string prints as its text rather than as quoted JSON, which
                // makes a table readable where JSON lines are exact.
                Value::String(text) => printable(text),
                value => printable(&value.to_string()),
            };

            crate::output::Cell::styled(
                text,
                color.then(|| crate::highlight::style(value)).flatten(),
            )
        }));
    }

    // The renderer draws the box without a trailing newline, which a table written to a
    // terminal needs so the next prompt starts on its own line.
    format!("{}\n", table.render(color))
}

/// Escape control characters a terminal would act on rather than show, for one cell.
///
/// A message's payload is arbitrary instrument bytes carried as text. Unescaped, a
/// newline breaks the row and the table's borders, and an escape byte starts an ANSI
/// sequence that could move the cursor or clear an operator's terminal.
///
/// `\n`, `\r`, and `\t` render by name and every other control as `\u{..}`, the same
/// shape JSON shows so a value looks the same whichever way it was asked for.
fn printable(text: &str) -> String {
    if !text.chars().any(char::is_control) {
        return text.to_string();
    }

    let mut escaped = String::with_capacity(text.len());
    for character in text.chars() {
        match character {
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            _ if character.is_control() => {
                escaped.push_str(&format!("\\u{{{:04x}}}", character as u32));
            }
            _ => escaped.push(character),
        }
    }

    escaped
}

/// Ask before a filtered write goes through, `false` meaning the reader declined.
///
/// The count is taken first because "Delete 400 variables?" is a question that can be
/// answered and "Delete the matching variables?" is not. Anything but a yes is a no, so
/// a stray keypress cancels rather than proceeds.
///
/// With no terminal to ask at, the write is refused rather than assumed because the
/// prompt is what stands between an over-broad filter and the rows going away.
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
/// An existence check reports through its exit status as well as its output so it
/// writes first and then carries the status out.
pub(crate) fn deliver(invocation: &Invocation, rendered: Rendered, colored: bool) -> Result<()> {
    match rendered {
        // A stream placed its own output so there is nothing left to write.
        Rendered::Written => return Ok(()),
        // Declining changed nothing, and a command chained behind this one with `&&`
        // must not run as though the write had gone through.
        Rendered::Declined => return Err(crate::error::Exit::failed("Cancelled.")),
        Rendered::Failed(message) => return Err(crate::error::Exit::failed(message)),
        _ => {}
    }

    let exists = rendered.exists();
    // A one-value answer is colored here, having had no chunk renderer to be colored in.
    // Rows and a drawn table arrive already colored so neither is touched again.
    let answer = matches!(rendered, Rendered::Text(_) | Rendered::Exists(_));
    let mut bytes = rendered.into_bytes();
    if colored && answer {
        bytes = crate::highlight::painted(bytes);
    }

    write_output(invocation.output.as_deref(), &bytes)?;
    match exists {
        Some(false) => Err(crate::error::Exit::status(1)),
        _ => Ok(()),
    }
}

/// Open the native store for a configured database.
///
/// A configuration this cannot connect through is refused with a message naming the
/// problem because the reader is the one who can fix it.
pub(crate) fn open_store(
    config: &DatabaseConfig,
    directory: &Path,
    writing: bool,
) -> std::result::Result<RecordStore, String> {
    match config {
        DatabaseConfig::Sqlite(sqlite) => {
            let path = existing(sqlite.path.as_deref(), directory)?;
            let (on_init, on_connect, on_close) = shared_hooks(&sqlite.shared);
            if writing {
                RecordStore::sqlite_writable(&path, on_init, on_connect, on_close)
            } else {
                RecordStore::sqlite(&path, on_connect, on_close)
            }
            .map_err(|error| format!("Cannot open {path}. {error}"))
        }
        DatabaseConfig::Turso(turso) => {
            let path = existing(turso.path.as_deref(), directory)?;
            let (on_init, on_connect, on_close) = shared_hooks(&turso.shared);
            Ok(RecordStore::turso(
                &path, turso.mvcc, on_init, on_connect, on_close,
            ))
        }
        DatabaseConfig::Postgres(postgres) => open_postgres(postgres),
    }
}

/// A configuration's connection lifecycle statements, ready to hand to a store.
///
/// The hooks run here the way they do anywhere else the database is opened, a database
/// reached from a command being the same database.
pub(crate) fn shared_hooks(
    shared: &ceres_config::SharedDatabaseConfig,
) -> (Vec<String>, Vec<String>, Vec<String>) {
    (
        shared.hooks.init.clone().unwrap_or_default(),
        shared.hooks.connect.clone().unwrap_or_default(),
        shared.hooks.close.clone().unwrap_or_default(),
    )
}

/// Open the native store for a configured PostgreSQL database.
pub(crate) fn open_postgres(
    postgres: &ceres_config::PostgresDatabaseConfig,
) -> std::result::Result<RecordStore, String> {
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

    // Connection string parameters carry through by name so a configuration
    // naming `sslmode` connects the way it says it does.
    let mut parameters = Vec::new();
    for (key, value) in postgres.shared.query.iter().flatten() {
        for held in value.as_slice() {
            parameters.push((key.clone(), held.clone()));
        }
    }

    let (on_init, on_connect, on_close) = shared_hooks(&postgres.shared);
    RecordStore::postgres(
        &postgres.host,
        postgres.port,
        &postgres.database,
        &postgres.user,
        postgres.password.as_ref().map(|secret| secret.expose()),
        settings,
        parameters,
        on_init,
        on_connect,
        on_close,
    )
    .map_err(|error| error.to_string())
}

/// What to say about a driver argument this cannot reproduce.
fn unsupported(key: &str) -> String {
    format!(
        "The database configuration sets `{key}`, which is an argument for a Python \
         database library rather than something this connects with. Remove it, or move \
         what it does into `connect_args.server_settings`."
    )
}

/// Resolve a configured database path, which has to name a file that is there.
///
/// A relative path is taken as naming a file beside the configuration that named it, so
/// the same project opens the same database whatever directory the command ran from.
fn existing(path: Option<&Path>, directory: &Path) -> std::result::Result<String, String> {
    let Some(path) = path else {
        return Err(
            "This project's database configuration names no path, so there is no file to \
             open."
                .to_string(),
        );
    };

    let path = ceres_config::resolve_path(path, directory);
    let absolute = std::path::absolute(&path)
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
fn write_output(output: Option<&Path>, rendered: &[u8]) -> Result<()> {
    match output {
        Some(path) => {
            let written = std::fs::File::create(path).and_then(|mut file| file.write_all(rendered));
            if let Err(error) = written {
                return Err(crate::error::Exit::failed(format!(
                    "Cannot write {}. {error}",
                    path.display()
                )));
            }
        }
        None => {
            let stdout = std::io::stdout();
            let mut lock = stdout.lock();
            let _ = lock.write_all(rendered);
        }
    }

    Ok(())
}

/// A statement outcome in the store's own error type.
pub(crate) type StoreResult<T> = std::result::Result<T, ceres_database::Error>;

/// A load's batches, read from their file as they are written.
pub(crate) type Batches<B> = Box<dyn Iterator<Item = std::result::Result<B, String>> + Send>;

/// One half of the table split, as the shared [`run`] pass needs it.
///
/// The record and entity tables differ in which store methods serve them and in the
/// rules a write applies, credentials existing only on the entity side. Everything else
/// about a run is shared, which lets it be written once.
pub(crate) trait Dumpable: Tabled + Copy + Send + 'static
where
    Self::Batch: RenderRows + Clone + Send + Sync,
{
    /// The surface group this table belongs to, which reads the invocation.
    fn surface(self) -> Table;

    /// Whether the native pass serves this invocation.
    fn serves(self, invocation: &Invocation, credentials: Option<Credentials>) -> bool;

    /// Hand a follow to its streaming path, which only the record tables declare.
    fn follow(
        self,
        invocation: &Invocation,
        format: DumpFormat,
        colored: bool,
        config: Option<&Path>,
    ) -> Result<()>;

    /// Parse filter pairs against this table's schema.
    fn parse(self, pairs: &[(String, String)]) -> std::result::Result<Filter<Self>, Refusal> {
        Filter::parse(self, pairs)
    }

    /// Build the one row a create names, the failure naming the field and reason.
    fn build(
        self,
        pairs: &[(String, String)],
        credentials: Option<Credentials>,
    ) -> std::result::Result<Self::Batch, String>;

    /// Open a load's batches, `None` when the file's first row names no columns.
    fn batches(
        self,
        file: std::io::BufReader<std::fs::File>,
        format: LoadFormat,
        credentials: Option<Credentials>,
    ) -> Option<Batches<Self::Batch>>;

    /// Count what the filter matches.
    async fn count(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<u64>;

    /// Whether anything matches the filter.
    async fn any(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<bool>;

    /// Delete what the filter matches, returning the deleted count.
    async fn delete(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<u64>;

    /// Delete what the filter matches and return the deleted rows.
    async fn delete_returning(
        store: &RecordStore,
        filter: &Filter<Self>,
    ) -> StoreResult<Self::Batch>;

    /// Assign values to what the filter matches, returning how many rows changed.
    async fn update(
        store: &RecordStore,
        filter: &Filter<Self>,
        set: &str,
        credentials: Option<Credentials>,
    ) -> StoreResult<u64>;

    /// Assign values to what the filter matches and return the changed rows.
    async fn update_returning(
        store: &RecordStore,
        filter: &Filter<Self>,
        set: &str,
        credentials: Option<Credentials>,
    ) -> StoreResult<Self::Batch>;

    /// Write a load's batches in one transaction, returning how many rows landed.
    async fn load(
        store: &RecordStore,
        batches: impl Iterator<Item = std::result::Result<Self::Batch, String>> + Send,
        conflict: Conflict,
    ) -> StoreResult<usize>;

    /// Stream what the filter matches, a chunk at a time.
    async fn stream(
        store: &RecordStore,
        filter: &Filter<Self>,
        sink: &mut (dyn FnMut(Self::Batch) -> StoreResult<()> + Send),
    ) -> StoreResult<()>;
}

/// The credential rules this database's writes follow, `None` when a configured
/// parameter is outside what the hashing takes.
///
/// Both algorithms a configuration can name are produced here so the answer is `None`
/// only for a parameter that would not hash at all, which the configuration layer should
/// already have refused.
pub(crate) fn credentials(database: &DatabaseConfig) -> Option<Credentials> {
    let hashing = match &database.shared().hashing {
        HashingConfig::Argon2(hashing) => Hashing::Argon2(Argon2Params {
            time_cost: hashing.time_cost.try_into().ok()?,
            memory_cost: hashing.memory_cost.try_into().ok()?,
            parallelism: hashing.parallelism.try_into().ok()?,
            hash_length: hashing.hash_length.try_into().ok()?,
            salt_length: hashing.salt_length.try_into().ok()?,
        }),
        HashingConfig::Bcrypt(hashing) => Hashing::Bcrypt(hashing.rounds.try_into().ok()?),
    };

    Some(Credentials::new(hashing))
}

/// What to say about a filter the compiler will not take.
///
/// An invalid value carries its own sentence, and a construct outside the grammar names
/// itself because both are things the reader wrote and can change.
pub(crate) fn refused(refusal: Refusal) -> crate::error::Exit {
    crate::error::Exit::failed(match refusal {
        Refusal::Invalid(message) => message,
        Refusal::Delegated => {
            "This filter uses a construct the query compiler does not serve.".to_string()
        }
    })
}

/// Render one chunk of rows in the shape the invocation asked for.
pub(crate) fn render<B: RenderRows>(
    batch: &B,
    format: DumpFormat,
    projection: &[(String, String)],
    header: bool,
    colored: bool,
) -> StoreResult<Vec<u8>> {
    let rendered = match (format, projection.is_empty()) {
        // A table is drawn once the whole result is in hand so each chunk
        // renders as JSON lines here and the drawing happens at the end.
        (DumpFormat::Table, true) => batch.to_json_lines(),
        (DumpFormat::Table, false) => batch.to_json_lines_projected(projection),
        (DumpFormat::Json, true) => batch.to_json_lines(),
        (DumpFormat::Json, false) => batch.to_json_lines_projected(projection),
        (DumpFormat::Csv, true) => batch.to_csv_lines(header).map(String::into_bytes),
        (DumpFormat::Csv, false) => batch
            .to_csv_lines_projected(projection, header)
            .map(String::into_bytes),
    };
    rendered
        .map(|bytes| format.paint(bytes, colored))
        .map_err(|error| ceres_database::Error::Decode(error.to_string()))
}

/// Ask for a password with echo off, twice, so a typo cannot land in the database.
fn prompt_password() -> Result<String> {
    use std::io::IsTerminal;

    if !std::io::stdin().is_terminal() {
        return Err(crate::error::Exit::failed(
            "A password is required. Pass --password, or run interactively to be \
             prompted for one.",
        ));
    }

    let read = |prompt| {
        rpassword::prompt_password(prompt)
            .map_err(|error| crate::error::Exit::failed(format!("Failed to read it. {error}")))
    };
    let password = read("User Password: ")?;
    if password != read("User Password (Confirm): ")? {
        return Err(crate::error::Exit::failed("Passwords did not match."));
    }

    Ok(password)
}

/// Run one table command.
pub(crate) fn run<T: Dumpable>(
    table: T,
    config: Option<&Path>,
    color: Option<bool>,
    verb: Verb,
    matches: &ArgMatches,
) -> Result<()>
where
    T::Batch: RenderRows + Clone + Send + Sync,
{
    let invocation = Invocation::read(table.surface(), verb, matches);

    // The shape is what was asked for and the color follows the flags, which are two
    // questions rather than one. Turning color off changes nothing about the shape.
    let format = invocation.dump_format();
    let colored = invocation.colored(color);

    // A follow reads a running engine rather than the database so it opens no store and
    // takes its own path from here.
    if invocation.verb.streams() {
        return table.follow(&invocation, format, colored, config);
    }

    // The configuration is read before anything is built because a user's own columns
    // are written under rules the database's own hashing configuration decides.
    let project = Project::discover(config)?;
    let meta = project.load_meta()?;

    let credentials = credentials(&meta.database);
    if !table.serves(&invocation, credentials) {
        return Err(crate::error::Exit::failed(
            "This database hashes passwords with parameters this command cannot \
             reproduce, so it will not write a user.",
        ));
    }

    // A filtered verb parses its wire pairs, while `create` reads them as the new
    // row's field values and `load` opens a file it will walk as it writes.
    let mut filter = None;
    let mut incoming = Vec::new();
    let mut source = None;
    if invocation.verb.filters() {
        let parsed = table.parse(&invocation.pairs).map_err(refused)?;
        filter = Some(parsed);
    } else if invocation.verb == Verb::Create {
        // A password never has to travel on the command line, where it lands in shell
        // history. An absent one is prompted for with echo off.
        let mut pairs = invocation.pairs.clone();
        if table.surface().dynamic().create_requires("password")
            && !pairs.iter().any(|(key, _)| key == "password")
        {
            pairs.push(("password".into(), prompt_password()?));
        }

        let built = table
            .build(&pairs, credentials)
            .map_err(crate::error::Exit::failed)?;

        incoming.push(built);
    } else {
        // A file that will not open is this command's failure to report, not a reason
        // to hand the whole load to another process.
        let (file, load_format) = invocation
            .load_source()
            .map_err(crate::error::Exit::failed)?;
        let Some(batches) = table.batches(file, load_format, credentials) else {
            return Err(crate::error::Exit::failed(
                "The file's first row does not name the columns to load.",
            ));
        };

        source = Some(batches);
    }

    // Pool construction spawns maintenance tasks so the runtime has to exist first.
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("the runtime always builds");
    let guard = runtime.enter();
    // A database this cannot open is reported here, naming the configuration that made
    // it so, rather than being handed to another process to explain.
    let store = open_store(
        &meta.database,
        project.directory(),
        invocation.verb.writes(),
    )
    .map_err(crate::error::Exit::failed)?;

    drop(guard);

    // The whole result renders before anything writes so a failure here can still
    // refuse without having produced partial output.
    let projection = invocation.projection.clone();
    let header = invocation.header;
    let rendered = runtime.block_on(async {
        let filter = || {
            filter
                .as_ref()
                .expect("a filtered verb parsed its filter above")
        };

        // A filtered write says how much it is about to change and waits for an answer.
        // The count costs a round trip, which is why it is only taken when someone is
        // actually going to be asked.
        if invocation.verb.confirms() && invocation.confirm {
            let affected = T::count(&store, filter()).await?;
            match confirmed(invocation.verb, affected, table.schema().name) {
                Ok(true) => {}
                Ok(false) => return Ok(Rendered::Declined),
                Err(message) => return Ok(Rendered::Failed(message)),
            }
        }

        match invocation.verb {
            Verb::Count => T::count(&store, filter())
                .await
                .map(|count| Rendered::Text(format!("{count}\n"))),
            Verb::Any => T::any(&store, filter()).await.map(Rendered::Exists),
            // A filtered write reports how many rows it touched, or the rows
            // themselves when `--collect` asked for them.
            Verb::Delete if invocation.collect => {
                let touched = T::delete_returning(&store, filter()).await?;
                render(&touched, format, &projection, header, colored)
                    .map(|bytes| Rendered::Bytes(bytes).drawn(format, colored))
            }
            Verb::Delete => T::delete(&store, filter())
                .await
                .map(|affected| Rendered::Text(format!("{affected}\n"))),
            Verb::Update => {
                let set = invocation
                    .set
                    .as_deref()
                    .expect("an update carries its set object");
                if invocation.collect {
                    let touched = T::update_returning(&store, filter(), set, credentials).await?;
                    render(&touched, format, &projection, header, colored)
                        .map(|bytes| Rendered::Bytes(bytes).drawn(format, colored))
                } else {
                    T::update(&store, filter(), set, credentials)
                        .await
                        .map(|affected| Rendered::Text(format!("{affected}\n")))
                }
            }
            // A load reports how many rows it wrote, which the reader counts as it
            // walks the file, whatever the conflict mode then did with them.
            Verb::Load => {
                let conflict = invocation
                    .conflict()
                    .expect("a load resolved its conflict mode above");
                let batches = source.take().expect("a load opened its file above");
                T::load(&store, batches, conflict)
                    .await
                    .map(|written| Rendered::Text(format!("{written}\n")))
            }
            // A follow took its own path before the store opened.
            Verb::Follow => unreachable!("a follow never reaches the store"),
            Verb::Create => {
                T::load(&store, incoming.iter().cloned().map(Ok), Conflict::Error).await?;
                render(&incoming[0], format, &projection, header, colored)
                    .map(|bytes| Rendered::Bytes(bytes).drawn(format, colored))
            }
            // A select streams, rendering and writing each chunk as the driver yields
            // it so the dump never holds more than one chunk however large the table.
            Verb::Select => {
                // A table holds every chunk because a column is only as wide as its
                // widest cell. Every other shape streams so a dump of any size holds
                // one chunk however large the table.
                let mut sink = if format == DumpFormat::Table {
                    Sink::collecting()
                } else {
                    Sink::new(invocation.output.as_deref(), header)
                };
                let outcome = T::stream(&store, filter(), &mut |batch| {
                    let heading = sink.heading();
                    let rendered = render(&batch, format, &projection, heading, colored)?;
                    sink.push(rendered).map_err(written)
                })
                .await;

                sink.resolve(outcome)
                    .map(|rendered| rendered.drawn(format, colored))
            }
        }
    });
    let rendered = match rendered {
        Ok(rendered) => rendered,
        // A refusal names what the command asked for that the writer will not do, and
        // nothing was written so this is its own failure to report.
        Err(ceres_database::Error::Refused(message)) => {
            return Err(crate::error::Exit::failed(message));
        }
        Err(error) => return Err(crate::error::Exit::failed(error.to_string())),
    };

    deliver(&invocation, rendered, colored)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_sink_holds_one_chunk_so_a_small_dump_can_still_refuse_cleanly() {
        // A result that fits one chunk never opens its destination so the whole dump
        // comes back to the caller and a late refusal reports whole with no partial
        // output ahead of it.
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
        // The first chunk went out to make room so the pass is committed from here.
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

        // A stream cannot hold its first row back because it may be the only one for a
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
    fn a_stream_refuses_before_its_first_write_and_reports_after() {
        let failure = || ceres_database::Error::Decode("unreadable row".to_string());

        // Nothing has been written so the failure is a clean refusal.
        let sink = Sink::new(None, true);
        assert!(sink.resolve(Err(failure())).is_err());

        // Past the first write there is no taking it back so the pass reports what
        // failed rather than pretending nothing was printed.
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("rows.jsonl");
        let mut sink = Sink::new(Some(&path), true);
        sink.push(b"one\n".to_vec()).unwrap();
        sink.push(b"two\n".to_vec()).unwrap();
        assert!(matches!(
            sink.resolve(Err(failure())),
            Ok(Rendered::Failed(_))
        ));
    }

    #[test]
    fn an_existence_answer_carries_its_status_as_well_as_its_output() {
        // An existence check is written to be used in a shell condition so the exit
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
            format: Some("csv".to_string()),
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
        assert!(refused.contains("--format"), "{refused}");

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
        let shape = |named: Option<&str>, output: Option<&str>| {
            Invocation {
                format: named.map(str::to_string),
                output: output.map(PathBuf::from),
                ..Invocation::default()
            }
            .dump_format()
        };

        assert_eq!(shape(None, None), DumpFormat::Json);
        assert_eq!(shape(None, Some("rows.csv")), DumpFormat::Csv);
        assert_eq!(shape(None, Some("rows.json")), DumpFormat::Json);
        assert_eq!(shape(Some("csv"), None), DumpFormat::Csv);
        // Naming a format is how a reader overrides what the suffix would have said,
        // columns included, columns being the shape nothing ever infers.
        assert_eq!(shape(Some("json"), Some("rows.csv")), DumpFormat::Json);
        assert_eq!(shape(Some("table"), None), DumpFormat::Table);
        assert_eq!(shape(Some("table"), Some("rows.txt")), DumpFormat::Table);
    }

    #[test]
    fn a_dump_nobody_named_a_shape_for_is_json_lines() {
        // A dump is a thing to pipe into something else. One that changed shape depending
        // on where it was pointed could not be scripted against without first knowing how
        // it was going to be run so the shape does not depend on who is reading.
        let dump = Invocation::default();
        assert_eq!(dump.dump_format(), DumpFormat::Json);

        // Color is the one thing that does ask because nobody watching means nobody to
        // see it, and it changes no byte a script would have read.
        assert!(dump.colored(Some(true)));
        assert!(!dump.colored(Some(false)));
        assert_eq!(dump.dump_format(), DumpFormat::Json);
    }

    #[test]
    fn a_dump_named_a_file_carries_no_color_however_the_terminal_is_set() {
        let dump = |output: Option<&str>| Invocation {
            output: output.map(PathBuf::from),
            ..Invocation::default()
        };

        // Escape sequences written to a file are read back as the characters they are
        // so a redirected dump is uncolored even where a reader asked for color.
        assert!(dump(None).colored(Some(true)));
        assert!(!dump(Some("rows.json")).colored(Some(true)));
        assert!(!dump(None).colored(Some(false)));
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

        // A string cell prints as its text rather than as quoted JSON, which
        // makes a table readable where JSON lines are exact.
        assert!(!drawn.contains('"'), "{drawn}");
    }

    #[test]
    fn a_table_of_nothing_says_so() {
        // An empty box would read as a rendering failure and a silent exit as a lost
        // result. Neither is what happened.
        assert_eq!(tabulate(b"", false), "No rows.\n");
    }

    #[test]
    fn a_cell_holding_binary_stays_inside_its_row() {
        // A message's payload is arbitrary instrument bytes. Unescaped, a newline
        // would break the row across lines and an escape byte would reach the
        // terminal as an ANSI sequence.
        let rendered = "{\"data\":\"a\\r\\nb\\u0000c\\u001bd\"}\n".as_bytes();
        let drawn = tabulate(rendered, false);

        // Four lines of box and one of content, the shape of a one-row table.
        assert_eq!(drawn.lines().count(), 5, "{drawn}");
        assert!(drawn.contains("a\\r\\nb\\u{0000}c\\u{001b}d"), "{drawn}");

        // Nothing a terminal would act on survived into the output.
        assert!(!drawn.contains('\r'), "{drawn}");
        assert!(!drawn.contains('\u{0000}'), "{drawn}");
        assert!(!drawn.contains('\u{001b}'), "{drawn}");
    }

    #[test]
    fn ordinary_text_passes_through_a_cell_untouched() {
        // Escaping only applies where something needs it so a readable value stays
        // readable rather than arriving full of backslashes.
        assert_eq!(printable("@sensor.temp"), "@sensor.temp");
        assert_eq!(printable("a value with spaces"), "a value with spaces");
        assert_eq!(printable("ünïcode ✓"), "ünïcode ✓");
    }
}
