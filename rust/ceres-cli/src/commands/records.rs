//! Native record dumps.
//!
//! A record command runs entirely natively when the shared rules in
//! [`dump`](super::dump) admit it,
//! the filter parses into the native subset, the database opens through the native store,
//! and the output renders in one pass, projected or not, so the interpreter never starts.
//! This module holds only what a record means, its filter, its rows, and its renderers.

use std::fs::File;
use std::path::Path;

use ceres_database::{Conflict, Credentials, Filter, LoadFormat, RecordStore, RecordTable};
use ceres_entities::Records;

use crate::commands::dump::{Batches, DumpFormat, Dumpable, Invocation, StoreResult};
use crate::commands::surface::Table;
use crate::error::Result;

impl Dumpable for RecordTable {
    fn surface(self) -> Table {
        Table::Record(self)
    }

    fn serves(self, _invocation: &Invocation, _credentials: Option<Credentials>) -> bool {
        true
    }

    fn follow(
        self,
        invocation: &Invocation,
        format: DumpFormat,
        colored: bool,
        config: Option<&Path>,
    ) -> Result<()> {
        crate::commands::follow::run(self, invocation, format, colored, config)
    }

    fn build(
        self,
        pairs: &[(String, String)],
        _credentials: Option<Credentials>,
    ) -> Option<Records> {
        ceres_database::build(self, pairs)
    }

    fn batches(
        self,
        file: std::io::BufReader<File>,
        format: LoadFormat,
        _credentials: Option<Credentials>,
    ) -> Option<Batches<Records>> {
        ceres_database::batches(self, file, format)
            .map(|batches| Box::new(batches) as Batches<Records>)
    }

    async fn count(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<u64> {
        store.count_filter(filter).await
    }

    async fn any(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<bool> {
        store.any_filter(filter).await
    }

    async fn delete(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<u64> {
        store.delete_filter(filter).await
    }

    async fn delete_returning(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<Records> {
        store.delete_filter_returning(filter).await
    }

    async fn update(
        store: &RecordStore,
        filter: &Filter<Self>,
        assign: &str,
        _credentials: Option<Credentials>,
    ) -> StoreResult<u64> {
        store.update_filter(filter, assign).await
    }

    async fn update_returning(
        store: &RecordStore,
        filter: &Filter<Self>,
        assign: &str,
        _credentials: Option<Credentials>,
    ) -> StoreResult<Records> {
        store.update_filter_returning(filter, assign).await
    }

    async fn load(
        store: &RecordStore,
        batches: impl Iterator<Item = std::result::Result<Records, String>> + Send,
        conflict: Conflict,
    ) -> StoreResult<usize> {
        store.load_records(batches, conflict).await
    }

    async fn stream(
        store: &RecordStore,
        filter: &Filter<Self>,
        sink: &mut (dyn FnMut(Records) -> StoreResult<()> + Send),
    ) -> StoreResult<()> {
        store.stream_filter(filter, &mut |batch| sink(batch)).await
    }
}

#[cfg(test)]
mod tests {
    use ceres_database::RecordFilter;

    use super::*;
    use crate::commands::dump::Verb;

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
