//! Native dumps for the non-record entities.
//!
//! The entity tables take the same seven verbs the record tables do, over the shared
//! surface in [`dump`](super::dump) so this module holds only what an entity means.
//! They are small tables an operator reads and edits so the win is the interpreter
//! that never starts rather than the throughput of a large scan.
//!
//! Users are the one table whose writes carry rules of their own. A password hashes
//! with the database's configured parameters and an email address normalizes, both
//! before the transaction opens so a row written here matches what the engine would
//! have written. A configuration these rules cannot reproduce, or an address the
//! normalizer cannot handle, refuses rather than storing something else.

use std::fs::File;
use std::path::Path;

use ceres_database::{Conflict, Credentials, EntityTable, Filter, LoadFormat, RecordStore};
use ceres_entities::Entities;

use crate::commands::dump::{Batches, DumpFormat, Dumpable, Invocation, StoreResult};
use crate::commands::surface::Table;
use crate::error::Result;

impl Dumpable for EntityTable {
    fn surface(self) -> Table {
        Table::Entity(self)
    }

    /// Every table but users serves whatever it is given. A user's writes hash a
    /// password and normalize an email address with the database's own parameters, so
    /// without rules to do that the command refuses. A user's reads never need them.
    fn serves(self, invocation: &Invocation, credentials: Option<Credentials>) -> bool {
        if self != EntityTable::Users {
            return true;
        }

        !invocation.verb.writes() || credentials.is_some()
    }

    fn follow(
        self,
        _invocation: &Invocation,
        _format: DumpFormat,
        _colored: bool,
        _config: Option<&Path>,
    ) -> Result<()> {
        // An entity group declares no `follow` so the surface refuses the verb before
        // anything reaches here.
        unreachable!("an entity group declares no follow")
    }

    fn build(
        self,
        pairs: &[(String, String)],
        credentials: Option<Credentials>,
    ) -> Option<Entities> {
        ceres_database::build_entity(self, pairs, credentials)
    }

    fn batches(
        self,
        file: std::io::BufReader<File>,
        format: LoadFormat,
        credentials: Option<Credentials>,
    ) -> Option<Batches<Entities>> {
        ceres_database::entity_batches(self, file, format, credentials)
            .map(|batches| Box::new(batches) as Batches<Entities>)
    }

    async fn count(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<u64> {
        store.count_entity_filter(filter).await
    }

    async fn any(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<bool> {
        store.any_entity_filter(filter).await
    }

    async fn delete(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<u64> {
        store.delete_entity_filter(filter).await
    }

    async fn delete_returning(store: &RecordStore, filter: &Filter<Self>) -> StoreResult<Entities> {
        store.delete_entity_filter_returning(filter).await
    }

    async fn update(
        store: &RecordStore,
        filter: &Filter<Self>,
        assign: &str,
        credentials: Option<Credentials>,
    ) -> StoreResult<u64> {
        store
            .update_entity_filter(filter, assign, credentials)
            .await
    }

    async fn update_returning(
        store: &RecordStore,
        filter: &Filter<Self>,
        assign: &str,
        credentials: Option<Credentials>,
    ) -> StoreResult<Entities> {
        store
            .update_entity_filter_returning(filter, assign, credentials)
            .await
    }

    async fn load(
        store: &RecordStore,
        batches: impl Iterator<Item = std::result::Result<Entities, String>> + Send,
        conflict: Conflict,
    ) -> StoreResult<usize> {
        store.load_entities(batches, conflict).await
    }

    async fn stream(
        store: &RecordStore,
        filter: &Filter<Self>,
        sink: &mut (dyn FnMut(Entities) -> StoreResult<()> + Send),
    ) -> StoreResult<()> {
        store
            .stream_entity_filter(filter, &mut |batch| sink(batch))
            .await
    }
}

#[cfg(test)]
mod tests {
    use ceres_config::{DatabaseConfig, HashingConfig};
    use ceres_database::EntityFilter;

    use super::*;
    use crate::commands::dump::{Verb, credentials};

    /// Parse one invocation the way the binary does.
    fn read(table: EntityTable, arguments: &[&str]) -> Invocation {
        let table = Table::Entity(table);
        let matches = table
            .command()
            .try_get_matches_from(std::iter::once(table.plural()).chain(arguments.iter().copied()))
            .expect("the arguments parse");
        let (verb, matches) = matches.subcommand().expect("a verb was named");
        Invocation::read(table, Verb::parse(verb).expect("a declared verb"), matches)
    }

    /// The rules a database configured the ordinary way hands out.
    fn rules() -> Option<Credentials> {
        credentials(&DatabaseConfig::default())
    }

    #[test]
    fn a_user_write_needs_rules_for_the_columns_it_cannot_store_as_given() {
        // Argon2id is what a database configures unless it says otherwise so the
        // ordinary case carries rules and every verb serves.
        assert!(rules().is_some());
        for arguments in [
            &["create", "--username", "ada"][..],
            &["load", "users.jsonl"][..],
            &["update", "--assign", "{}"][..],
            &["select"][..],
            &["count"][..],
        ] {
            let invocation = read(EntityTable::Users, arguments);
            assert!(
                EntityTable::Users.serves(&invocation, rules()),
                "{arguments:?}"
            );
        }

        // Without them a user's writes cannot go through here because storing a
        // password hashed some other way than the database asked for is worse than not
        // storing it. Reads carry on natively.
        for arguments in [
            &["create", "--username", "ada"][..],
            &["load", "users.jsonl"][..],
            &["update", "--assign", "{}"][..],
        ] {
            let invocation = read(EntityTable::Users, arguments);
            assert!(
                !EntityTable::Users.serves(&invocation, None),
                "{arguments:?}"
            );
        }
        assert!(EntityTable::Users.serves(&read(EntityTable::Users, &["select"]), None));

        // No other table has a column these rules touch so none of them ever needs one.
        for table in [
            EntityTable::Variables,
            EntityTable::Settings,
            EntityTable::Workspaces,
        ] {
            assert!(table.serves(&read(table, &["create", "--name", "x"]), None));
            assert!(table.serves(&read(table, &["load", "rows.jsonl"]), None));
        }
    }

    #[test]
    fn a_bcrypt_database_serves_its_user_writes_too() {
        // bcrypt is the other algorithm a configuration can name, and it is produced
        // here as well so a database on it writes its users natively like any other.
        let config = DatabaseConfig::Sqlite(ceres_config::SqliteDatabaseConfig {
            path: Some("records.sqlite".into()),
            shared: ceres_config::SharedDatabaseConfig {
                hashing: HashingConfig::Bcrypt(ceres_config::BcryptHashingConfig { rounds: 4 }),
                ..Default::default()
            },
        });
        let rules = credentials(&config).expect("bcrypt hashes natively");
        let hashed = rules.password("secret").expect("a password hashes");
        assert!(hashed.starts_with("$2b$04$"), "{hashed}");
        assert_eq!(ceres_database::verify_bcrypt("secret", &hashed), Some(true));
    }

    #[test]
    fn a_boolean_key_is_its_own_value_and_never_takes_the_next_argument() {
        // A boolean is a `--key` and `--no-key` pair so a token following one is a
        // positional field rather than the boolean's value. The form comes from the
        // field's family so the surface and the compiler cannot disagree about what
        // `--owned` is.
        assert_eq!(
            EntityFilter::keys(EntityTable::Workspaces)
                .iter()
                .find(|key| key.key == "owned")
                .map(|key| key.arity),
            Some(ceres_database::Arity::Flag)
        );

        let invocation = read(EntityTable::Workspaces, &["select", "--owned", "name"]);
        assert_eq!(
            invocation.pairs,
            vec![("owned".to_string(), "true".to_string())]
        );
        assert_eq!(
            invocation.projection,
            vec![("name".to_string(), "name".to_string())]
        );

        let invocation = read(
            EntityTable::Workspaces,
            &["select", "--no-show-when-logged-out"],
        );
        assert_eq!(
            invocation.pairs,
            vec![("show_when_logged_out".to_string(), "false".to_string())]
        );

        // A computed predicate is a boolean too, and a non-boolean key still takes the
        // argument that follows it.
        let invocation = read(
            EntityTable::Variables,
            &["select", "--no-internal", "--name", "x"],
        );
        assert_eq!(
            invocation.pairs,
            vec![
                ("internal".to_string(), "false".to_string()),
                ("name".to_string(), "x".to_string()),
            ]
        );
    }

    #[test]
    fn an_entity_group_declares_no_follow() {
        // Following reads a running engine's stream of new rows, which the tables an
        // operator edits by hand do not have. The surface leaves the verb out rather
        // than accepting it and failing later.
        for table in [
            EntityTable::Users,
            EntityTable::Variables,
            EntityTable::Settings,
            EntityTable::Workspaces,
        ] {
            let group = Table::Entity(table).command();
            assert!(group.find_subcommand("follow").is_none());
            assert!(group.find_subcommand("select").is_some());
        }
    }

    #[test]
    fn a_create_takes_the_password_column_the_filter_does_not_expose() {
        // A user's password is stored hashed and is not filterable, but a create has to
        // be able to set one so the two surfaces are built from different lists.
        let invocation = read(
            EntityTable::Users,
            &["create", "--username", "ada", "--password", "secret"],
        );

        assert_eq!(
            invocation.pairs,
            vec![
                ("username".to_string(), "ada".to_string()),
                ("password".to_string(), "secret".to_string()),
            ]
        );
    }
}
