//! Native record dumps.
//!
//! A record command runs entirely natively when the shared rules in [`dump`] admit it,
//! the filter parses into the native subset, the database opens through the native store,
//! and the output renders in one pass, projected or not, so the interpreter never starts.
//! This module holds only what a record means, its filter, its rows, and its renderers.

use std::path::Path;

use ceres_database::{RecordFilter, RecordTable};
use ceres_entities::Records;
use clap::ArgMatches;

use crate::commands::dump::{
    DumpFormat, Invocation, Rendered, Sink, Verb, deliver, open_store, written,
};
use crate::commands::surface::Table;
use crate::error::Result;
use crate::project::Project;

/// Run one record command.
pub fn run(
    table: RecordTable,
    config: Option<&Path>,
    color: Option<bool>,
    verb: Verb,
    matches: &ArgMatches,
) -> Result<()> {
    let invocation = Invocation::read(Table::Record(table), verb, matches);

    // The shape is what was asked for and the color follows the flags, which are two
    // questions rather than one. Turning color off changes nothing about the shape.
    let format = invocation.dump_format();
    let colored = invocation.colored(color);

    // A follow reads a running engine rather than the database, so it opens no store and
    // takes its own path from here.
    if invocation.verb.streams() {
        return crate::commands::follow::run(table, &invocation, format, colored, config);
    }

    // A filtered verb parses its wire pairs, while `create` reads them as the new
    // record's field values and `load` opens a file it will walk as it writes.
    let mut filter = None;
    let mut incoming = Vec::new();
    let mut source = None;
    if invocation.verb.filters() {
        let parsed = RecordFilter::parse(table, &invocation.pairs).map_err(refused)?;
        filter = Some(parsed);
    } else if invocation.verb == Verb::Create {
        let Some(built) = ceres_database::build(table, &invocation.pairs) else {
            return Err(crate::error::Exit::failed(
                "This create names a value that cannot be stored as given. Check the \
                 types each field takes with --help.",
            ));
        };

        incoming.push(built);
    } else {
        // A file that will not open is this command's failure to report, not a reason
        // to hand the whole load to another process.
        let (file, load_format) = invocation
            .load_source()
            .map_err(crate::error::Exit::failed)?;
        let Some(batches) = ceres_database::batches(table, file, load_format) else {
            return Err(crate::error::Exit::failed(
                "The file's first row does not name the columns to load.",
            ));
        };

        source = Some(batches);
    }

    let project = Project::discover(config)?;
    let meta = project.load_meta()?;
    // Pool construction spawns maintenance tasks, so the runtime has to exist first.
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

    // The whole result renders before anything writes, so a failure here can still
    // delegate without having produced partial output.
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
            let affected = store.count_filter(filter()).await?;
            match crate::commands::dump::confirmed(invocation.verb, affected, table.name()) {
                Ok(true) => {}
                Ok(false) => return Ok(Rendered::Declined),
                Err(message) => return Ok(Rendered::Failed(message)),
            }
        }

        match invocation.verb {
            Verb::Count => store
                .count_filter(filter())
                .await
                .map(|count| Rendered::Text(format!("{count}\n"))),
            Verb::Any => store.any_filter(filter()).await.map(Rendered::Exists),
            // A filtered write reports how many rows it touched, or the rows
            // themselves when `--collect` asked for them.
            Verb::Delete if invocation.collect => {
                let touched = store.delete_filter_returning(filter()).await?;
                render(&touched, format, &projection, header, colored)
                    .map(|bytes| Rendered::Bytes(bytes).drawn(format, colored))
            }
            Verb::Delete => store
                .delete_filter(filter())
                .await
                .map(|affected| Rendered::Text(format!("{affected}\n"))),
            Verb::Update => {
                let assign = invocation
                    .assign
                    .as_deref()
                    .expect("an update carries its assignments");
                if invocation.collect {
                    let touched = store.update_filter_returning(filter(), assign).await?;
                    render(&touched, format, &projection, header, colored)
                        .map(|bytes| Rendered::Bytes(bytes).drawn(format, colored))
                } else {
                    store
                        .update_filter(filter(), assign)
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
                store
                    .load_records(batches, conflict)
                    .await
                    .map(|written| Rendered::Text(format!("{written}\n")))
            }
            // A follow took its own path before the store opened.
            Verb::Follow => unreachable!("a follow never reaches the store"),
            Verb::Create => {
                store
                    .load_records(
                        incoming.iter().cloned().map(Ok),
                        ceres_database::Conflict::Error,
                    )
                    .await?;
                render(&incoming[0], format, &projection, header, colored)
                    .map(|bytes| Rendered::Bytes(bytes).drawn(format, colored))
            }
            // A select streams, rendering and writing each chunk as the driver yields
            // it, so the dump never holds more than one chunk however large the table.
            Verb::Select => {
                // A table holds every chunk, because a column is only as wide as its
                // widest cell. Every other shape streams, so a dump of any size holds
                // one chunk however large the table.
                let mut sink = if format == DumpFormat::Table {
                    Sink::collecting()
                } else {
                    Sink::new(invocation.output.as_deref(), header)
                };
                let outcome = store
                    .stream_filter(filter(), &mut |records| {
                        let heading = sink.heading();
                        let rendered = render(&records, format, &projection, heading, colored)?;
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
        // nothing was written, so this is its own failure to report.
        Err(ceres_database::Error::Refused(message)) => {
            return Err(crate::error::Exit::failed(message));
        }
        Err(error) => return Err(crate::error::Exit::failed(error.to_string())),
    };

    deliver(&invocation, rendered, colored)
}

/// Render one chunk of records in the shape the invocation asked for.
fn render(
    records: &Records,
    format: DumpFormat,
    projection: &[(String, String)],
    header: bool,
    colored: bool,
) -> std::result::Result<Vec<u8>, ceres_database::Error> {
    let rendered = match (format, projection.is_empty()) {
        // A table is drawn once the whole result is in hand, so each chunk
        // renders as JSON lines here and the drawing happens at the end.
        (DumpFormat::Table, true) => records.to_json_lines(),
        (DumpFormat::Table, false) => records.to_json_lines_projected(projection),
        (DumpFormat::Json, true) => records.to_json_lines(),
        (DumpFormat::Json, false) => records.to_json_lines_projected(projection),
        (DumpFormat::Csv, true) => records.to_csv_lines(header).map(String::into_bytes),
        (DumpFormat::Csv, false) => records
            .to_csv_lines_projected(projection, header)
            .map(String::into_bytes),
    };
    rendered
        .map(|bytes| format.paint(bytes, colored))
        .map_err(|error| ceres_database::Error::Decode(error.to_string()))
}

/// What to say about a filter the compiler will not take.
///
/// An invalid value carries its own sentence, and a construct outside the grammar names
/// itself, because both are things the reader wrote and can change.
pub(crate) fn refused(refusal: ceres_database::Refusal) -> crate::error::Exit {
    crate::error::Exit::failed(match refusal {
        ceres_database::Refusal::Invalid(message) => message,
        ceres_database::Refusal::Delegated => {
            "This filter uses a construct the query compiler does not serve.".to_string()
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    /// Parse one invocation the way the binary does.
    fn read(table: RecordTable, arguments: &[&str]) -> Invocation {
        let table = Table::Record(table);
        let matches = table
            .command()
            .try_get_matches_from(std::iter::once(table.plural()).chain(arguments.iter().copied()))
            .expect("the arguments parse");
        let (verb, matches) = matches.subcommand().expect("a verb was named");
        Invocation::read(table, Verb::parse(verb).expect("a declared verb"), matches)
    }

    #[test]
    fn a_filter_reads_as_the_wire_pairs_the_compiler_takes() {
        let invocation = read(
            RecordTable::Messages,
            &[
                "select",
                "--address",
                "@sensor.temp",
                "--max-age=2h",
                "--order",
                "timestamp:desc",
            ],
        );

        assert_eq!(
            invocation.pairs,
            vec![
                ("address".to_string(), "@sensor.temp".to_string()),
                ("max_age".to_string(), "2h".to_string()),
                ("order".to_string(), "timestamp:desc".to_string()),
            ]
        );
        assert!(RecordFilter::parse(RecordTable::Messages, &invocation.pairs).is_ok());
    }

    #[test]
    fn an_unknown_key_is_an_argument_error_rather_than_a_filter_one() {
        // The surface is what refuses a key nobody declared, so it never reaches the
        // compiler and the reader is told which flag was wrong rather than being handed
        // a validation dump.
        let table = Table::Record(RecordTable::Messages);
        let refused = table
            .command()
            .try_get_matches_from(["messages", "select", "--nope", "x"])
            .unwrap_err();

        assert_eq!(refused.kind(), clap::error::ErrorKind::UnknownArgument);
    }

    #[test]
    fn a_repeated_key_folds_into_a_set() {
        let invocation = read(
            RecordTable::Messages,
            &["select", "--address", "@a", "--address", "@b"],
        );

        assert_eq!(
            invocation.pairs,
            vec![
                ("address".to_string(), "@a".to_string()),
                ("address".to_string(), "@b".to_string()),
            ]
        );
    }

    #[test]
    fn a_projection_merges_its_positional_and_flagged_halves() {
        // The last spelling of a field wins, and a comma-separated spec names several
        // fields at once so a projection can be typed rather than repeated.
        let invocation = read(
            RecordTable::Messages,
            &["select", "id:first,timestamp", "--field", "id:last"],
        );

        assert_eq!(
            invocation.projection,
            vec![
                ("id".to_string(), "last".to_string()),
                ("timestamp".to_string(), "timestamp".to_string()),
            ]
        );
    }

    #[test]
    fn a_csv_dump_carries_its_header_unless_it_is_turned_off() {
        assert!(read(RecordTable::Messages, &["select"]).header);
        assert!(!read(RecordTable::Messages, &["select", "--no-header"]).header);
        // The two spellings override each other, so the last one written wins.
        assert!(
            read(
                RecordTable::Messages,
                &["select", "--no-header", "--header"]
            )
            .header
        );
    }

    #[test]
    fn a_filtered_write_asks_unless_it_was_told_not_to() {
        // Nothing about the environment turns the question off. A script that would have
        // been stopped by the prompt has to keep being stopped by it, because the
        // alternative is a filter matching more than its author meant and the rows going
        // away with nobody watching.
        assert!(read(RecordTable::Messages, &["delete"]).confirm);
        assert!(read(RecordTable::Messages, &["update", "--assign", "{}"]).confirm);
        assert!(!read(RecordTable::Messages, &["delete", "--no-confirm"]).confirm);
        // The short spelling is the one that gets typed at a terminal.
        assert!(!read(RecordTable::Messages, &["delete", "-y"]).confirm);
        // The two spellings override each other, so the last one written wins.
        assert!(
            read(
                RecordTable::Messages,
                &["delete", "--no-confirm", "--confirm"]
            )
            .confirm
        );
    }

    #[test]
    fn an_unattended_write_is_refused_rather_than_assumed() {
        // Tests do not run at a terminal, which is the case this is about. Asking with
        // nobody there cannot be read as a yes.
        let refused = crate::commands::dump::confirmed(Verb::Delete, 400, "messages")
            .expect_err("there is no terminal to answer at");

        assert!(refused.contains("400 messages"), "{refused}");
        assert!(refused.contains("--no-confirm"), "{refused}");

        // A verb with no prompt is unaffected, whatever the terminal is doing.
        assert_eq!(
            crate::commands::dump::confirmed(Verb::Select, 400, "messages"),
            Ok(true)
        );
    }

    #[test]
    fn the_destination_decides_the_shape_when_no_format_is_named() {
        // Nobody is reading, which is what a pipe or a redirect looks like.
        let shape = |arguments: &[&str]| read(RecordTable::Messages, arguments).dump_format();

        assert_eq!(shape(&["select", "--output", "rows.csv"]), DumpFormat::Csv);
        assert_eq!(
            shape(&["select", "--output", "rows.json"]),
            DumpFormat::Json
        );
        // A named format wins over the suffix, which is the point of naming one.
        assert_eq!(
            shape(&["select", "--output", "rows.csv", "--format", "json"]),
            DumpFormat::Json
        );
    }
}
