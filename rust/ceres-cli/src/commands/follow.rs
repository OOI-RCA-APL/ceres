//! The native record follow stream.
//!
//! `follow` is the one verb that reads from a running engine rather than from the
//! database. It opens a websocket against the engine's CLI server, which streams a
//! record's wire JSON per frame, and renders each frame the way a `select` renders a
//! chunk, so a followed record prints exactly as a selected one does.
//!
//! Only the record tables declare it. The four non-record entity groups have no `follow`
//! subcommand at all, so the verb never reaches them.
//!
//! The delegation rule holds the same way it does for a streamed dump, and lands in the
//! same place for a different reason. Everything that decides whether a native pass may
//! serve, the filter, the format, the color, and whether an engine is even running, is
//! settled before the socket opens. Past that the output goes out as it arrives rather
//! than being held, because the first record may be the only one for a long while and
//! seeing it arrive is the point, so a later failure reports rather than delegating.

use std::path::Path;

use ceres_database::{RecordFilter, RecordTable};

use crate::client::Client;
use crate::commands::dump::{DumpFormat, Invocation, Rendered, Sink, deliver, written};
use crate::error::Result;
use crate::project::Project;

/// Follow a record table's live stream.
pub fn run(
    table: RecordTable,
    invocation: &Invocation,
    format: DumpFormat,
    colored: bool,
    config: Option<&Path>,
) -> Result<()> {
    // The filter parses here only to prove the query compiler understands it. The engine
    // compiles the query itself, so what crosses the wire is the pairs as typed.
    RecordFilter::parse(table, &invocation.pairs).map_err(crate::commands::records::refused)?;

    let project = Project::discover(config)?;
    let client = Client::connect(&project).map_err(|_| {
        crate::error::Exit::failed(
            "Following reads new rows from a running engine, and none is running for this \
             project. Start it with `ceres run`.",
        )
    })?;

    let mut socket = client
        .stream(table.name(), &invocation.pairs)
        .map_err(|error| {
            crate::error::Exit::failed(format!("Cannot open the engine's stream. {error}"))
        })?;

    let projection = invocation.projection.clone();
    let mut sink = Sink::live(invocation.output.as_deref(), invocation.header);
    loop {
        let frame = match socket.read() {
            Ok(tungstenite::Message::Text(text)) => text,
            // The engine closing the stream ends the command, and so does anything the
            // socket cannot carry on from.
            Ok(tungstenite::Message::Close(_)) | Err(_) => break,
            // A ping or a pong is the connection keeping itself alive.
            Ok(_) => continue,
        };

        let rendered = match render(table, &frame, format, &projection, colored, &mut sink) {
            Ok(rendered) => rendered,
            Err(message) => return deliver(invocation, Rendered::Failed(message), colored),
        };

        if let Err(error) = sink.push(rendered) {
            // A reader that closed the pipe is where the follow was asked to stop.
            if sink.broke() {
                return Ok(());
            }

            return deliver(
                invocation,
                Rendered::Failed(written(error).to_string()),
                colored,
            );
        }
    }

    match sink.finish() {
        Ok(Some(held)) => deliver(invocation, Rendered::Bytes(held), colored),
        Ok(None) => Ok(()),
        // A stream that failed having already put frames out ends where it stopped.
        Err(_) => Ok(()),
    }
}

/// Render one frame's record the way a dump renders a chunk of one.
///
/// A frame is a record's wire JSON, which is exactly one line of the JSON input a load
/// reads, so it decodes through the same reader and renders through the same renderers.
fn render(
    table: RecordTable,
    frame: &str,
    format: DumpFormat,
    projection: &[(String, String)],
    colored: bool,
    sink: &mut Sink<'_>,
) -> std::result::Result<Vec<u8>, String> {
    let Some(batches) = ceres_database::read(table, frame, ceres_database::LoadFormat::Json) else {
        return Err(format!("unreadable record in the stream: {frame}"));
    };
    let Some(records) = batches.first() else {
        return Ok(Vec::new());
    };

    // A stream has no end to draw a table at, so a follow that would have been drawn as
    // one is JSON lines instead, and is colored as the JSON lines it actually is.
    let format = match format {
        DumpFormat::Table => DumpFormat::Json,
        other => other,
    };

    let heading = sink.heading();
    let rendered = match (format, projection.is_empty()) {
        (DumpFormat::Json | DumpFormat::Table, true) => records.to_json_lines(),
        (DumpFormat::Json | DumpFormat::Table, false) => {
            records.to_json_lines_projected(projection)
        }
        (DumpFormat::Csv, true) => records.to_csv_lines(heading).map(String::into_bytes),
        (DumpFormat::Csv, false) => records
            .to_csv_lines_projected(projection, heading)
            .map(String::into_bytes),
    };
    rendered
        .map(|bytes| format.paint(bytes, colored))
        .map_err(|error| error.to_string())
}
