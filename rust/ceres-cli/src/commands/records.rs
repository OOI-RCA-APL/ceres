//! Native record dumps.
//!
//! A record command runs entirely natively when the shared rules in [`dump`] admit it,
//! the filter parses into the native subset, the database opens through the native store,
//! and the output renders in one pass, projected or not, so the interpreter never starts.
//! This module holds only what a record means, its filter, its rows, and its renderers.

use std::ffi::OsString;
use std::path::Path;

use ceres_database::{RecordFilter, RecordTable};
use ceres_entities::Records;

use crate::commands::dump::{DumpFormat, Invocation, Rendered, Verb, deliver, open_store};
use crate::error::Result;
use crate::project::Project;

/// Attempt one record command natively, `false` meaning the caller delegates.
pub fn try_run(table: RecordTable, config: Option<&Path>, raw: &[OsString]) -> Result<bool> {
    let Some(invocation) = Invocation::lex(raw, &RecordFilter::boolean_keys(table)) else {
        return Ok(false);
    };
    let Some(format) = invocation.dump_format() else {
        return Ok(false);
    };

    // A filtered verb parses its wire pairs, while `create` reads them as the new
    // record's field values and `load` reads a file instead. Both write forms build
    // their rows here, before anything opens, so a refusal costs nothing.
    let mut filter = None;
    let mut incoming = Vec::new();
    if invocation.verb.filters() {
        let Ok(parsed) = RecordFilter::parse(table, &invocation.pairs) else {
            return Ok(false);
        };

        filter = Some(parsed);
    } else if invocation.verb == Verb::Create {
        let Some(records) = ceres_database::build(table, &invocation.pairs) else {
            return Ok(false);
        };

        incoming.push(records);
    } else {
        let Some((text, load_format)) = invocation.load_source() else {
            return Ok(false);
        };
        let Some(batches) = ceres_database::read(table, &text, load_format) else {
            return Ok(false);
        };

        incoming = batches;
    }

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
        let filter = || {
            filter
                .as_ref()
                .expect("a filtered verb parsed its filter above")
        };
        match invocation.verb {
            Verb::Count => store
                .count_filter(filter())
                .await
                .map(|count| Rendered::Text(format!("{count}\n"))),
            Verb::Any => store.any_filter(filter()).await.map(Rendered::Exists),
            Verb::Delete => store
                .delete_filter(filter())
                .await
                .map(|affected| Rendered::Text(format!("{affected}\n"))),
            Verb::Update => {
                let assign = invocation
                    .assign
                    .as_deref()
                    .expect("an update carries its assignments");
                store.update_filter(filter(), assign).await.map(|affected| {
                    // Assignments the encoder refuses leave the table untouched, so the
                    // command delegates and Python owns the outcome.
                    affected.map_or(Rendered::Delegate, |affected| {
                        Rendered::Text(format!("{affected}\n"))
                    })
                })
            }
            // A load reports how many rows it read, which is the file's row count
            // whatever the conflict mode then did with them.
            Verb::Load => {
                let conflict = invocation
                    .conflict()
                    .expect("a load resolved its conflict mode above");
                let read = rows(&incoming);
                store
                    .load_records(&incoming, conflict)
                    .await
                    .map(|()| Rendered::Text(format!("{read}\n")))
            }
            Verb::Create => {
                store
                    .load_records(&incoming, ceres_database::Conflict::Error)
                    .await?;
                render(&incoming[0], format, &projection, header)
            }
            Verb::Select => {
                let records = store.fetch_filter(filter()).await?;
                render(&records, format, &projection, header)
            }
        }
    });
    let Ok(rendered) = rendered else {
        return Ok(false);
    };

    deliver(&invocation, rendered)
}

/// Render a set of records in the shape the invocation asked for.
fn render(
    records: &Records,
    format: DumpFormat,
    projection: &[(String, String)],
    header: bool,
) -> std::result::Result<Rendered, ceres_database::Error> {
    let rendered = match (format, projection.is_empty()) {
        (DumpFormat::Json, true) => records.to_json_lines(),
        (DumpFormat::Json, false) => records.to_json_lines_projected(projection),
        (DumpFormat::Csv, true) => Ok(records.to_csv_lines(header).into_bytes()),
        (DumpFormat::Csv, false) => records
            .to_csv_lines_projected(projection, header)
            .map(String::into_bytes),
    };
    rendered
        .map(Rendered::Bytes)
        .map_err(|error| ceres_database::Error::Decode(error.to_string()))
}

/// How many records a load's batches hold.
fn rows(batches: &[Records]) -> usize {
    batches
        .iter()
        .map(|batch| match batch {
            Records::Messages(records) => records.len(),
            Records::Particles(records) => records.len(),
            Records::Alerts(records) => records.len(),
            Records::LogEntries(records) => records.len(),
        })
        .sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raw(arguments: &[&str]) -> Vec<OsString> {
        arguments.iter().map(OsString::from).collect()
    }

    #[test]
    fn no_record_field_is_a_bare_boolean_flag() {
        // The shared lexer consumes the token after a flag unless the flag is a boolean,
        // which the Python CLI declares as a `--key` and `--no-key` pair. No record field
        // is one, so record lexing is exactly what it was before the entity tables
        // brought the first booleans, and a new boolean record field would land here.
        for table in [
            RecordTable::Messages,
            RecordTable::Particles,
            RecordTable::Alerts,
            RecordTable::Logs,
        ] {
            assert!(RecordFilter::boolean_keys(table).is_empty());
        }
    }

    #[test]
    fn the_filter_is_what_refuses_an_unknown_key() {
        let invocation = Invocation::lex(
            &raw(&[
                "select",
                "--address",
                "@sensor.temp",
                "--max-age=2h",
                "--order",
                "timestamp:desc",
            ]),
            &[],
        )
        .unwrap();
        assert!(RecordFilter::parse(RecordTable::Messages, &invocation.pairs).is_ok());

        // Unknown keys lex into pairs too, and the filter is what refuses them.
        let unknown = Invocation::lex(&raw(&["select", "--nope", "x"]), &[]).unwrap();
        assert!(RecordFilter::parse(RecordTable::Messages, &unknown.pairs).is_err());
    }
}
