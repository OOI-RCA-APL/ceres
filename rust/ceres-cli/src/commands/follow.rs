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

/// Follow a record table's live stream, `false` meaning the caller delegates.
pub fn run(
    table: RecordTable,
    invocation: &Invocation,
    format: DumpFormat,
    config: Option<&Path>,
) -> Result<bool> {
    // The filter parses here only to prove the native path understands it. The engine
    // compiles the query itself, so what crosses the wire is the pairs as typed.
    if RecordFilter::parse(table, &invocation.pairs).is_err() {
        return Ok(false);
    }

    let Ok(project) = Project::discover(config) else {
        return Ok(false);
    };
    // A stream needs a running engine, and reporting that none is running is the Python
    // command's message to produce.
    let Ok(client) = Client::connect(&project) else {
        return Ok(false);
    };

    let Ok(mut socket) = client.stream(table.name(), &invocation.pairs) else {
        return Ok(false);
    };

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

        let rendered = match render(table, &frame, format, &projection, &mut sink) {
            Ok(rendered) => rendered,
            Err(message) => {
                // Nothing has gone out yet, so the whole command is still Python's.
                if !sink.wrote() {
                    return Ok(false);
                }

                return deliver(invocation, Rendered::Failed(message));
            }
        };

        if let Err(error) = sink.push(rendered) {
            // A reader that closed the pipe is where the follow was asked to stop.
            if sink.broke() {
                return Ok(true);
            }

            if !sink.wrote() {
                return Ok(false);
            }

            return deliver(invocation, Rendered::Failed(written(error).to_string()));
        }
    }

    let wrote = sink.wrote();
    match sink.finish() {
        Ok(Some(held)) => deliver(invocation, Rendered::Bytes(held)),
        Ok(None) => Ok(true),
        // A final write that failed having already put frames out cannot be handed back,
        // so the command ends here rather than replaying in Python.
        Err(_) => Ok(wrote),
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
    sink: &mut Sink<'_>,
) -> std::result::Result<Vec<u8>, String> {
    let Some(batches) = ceres_database::read(table, frame, ceres_database::LoadFormat::Json) else {
        return Err(format!("unreadable record in the stream: {frame}"));
    };
    let Some(records) = batches.first() else {
        return Ok(Vec::new());
    };

    let heading = sink.heading();
    let rendered = match (format, projection.is_empty()) {
        (DumpFormat::Json, true) => records.to_json_lines(),
        (DumpFormat::Json, false) => records.to_json_lines_projected(projection),
        (DumpFormat::Csv, true) => Ok(records.to_csv_lines(heading).into_bytes()),
        (DumpFormat::Csv, false) => records
            .to_csv_lines_projected(projection, heading)
            .map(String::into_bytes),
    };
    rendered.map_err(|error| error.to_string())
}
