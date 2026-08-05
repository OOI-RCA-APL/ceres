//! Native dumps for the non-record entities.
//!
//! The entity tables take the same seven verbs the record tables do, over the shared
//! surface in [`dump`], so this module holds only what an entity means. They are small
//! tables an operator reads and edits, which makes the win here the interpreter that
//! never starts rather than the throughput of a large scan.
//!
//! Users are the one table whose writes carry rules of their own. A password hashes with
//! the database's configured Argon2 parameters and an email address normalizes, both
//! before the transaction opens, so a row written here is one the Python model would have
//! written identically. A database configured for bcrypt, or an address outside the subset
//! the normalizer understands, delegates rather than storing something else.

use std::path::Path;

use ceres_config::{DatabaseConfig, HashingConfig};
use ceres_database::{Argon2Params, Credentials, EntityFilter, EntityTable, Hashing};
use ceres_entities::Entities;
use clap::ArgMatches;

use crate::commands::dump::{
    DumpFormat, Invocation, Rendered, Sink, Verb, deliver, drawn, finish, open_store, written,
};
use crate::commands::surface::Table;
use crate::error::Result;
use crate::project::Project;

/// Run one entity command.
pub fn run(
    table: EntityTable,
    config: Option<&Path>,
    color: Option<bool>,
    verb: Verb,
    matches: &ArgMatches,
) -> Result<()> {
    let invocation = Invocation::read(Table::Entity(table), verb, matches);

    // The shape is what was asked for and the color follows the flags, which are two
    // questions rather than one. Turning color off changes nothing about the shape.
    let format = invocation.dump_format();
    let colored = invocation.colored(color);

    // The configuration is read before anything is built, because a user's own columns
    // are written under rules the database's own hashing configuration decides.
    let project = Project::discover(config)?;
    let meta = project.load_meta()?;

    let credentials = credentials(&meta.database);
    if !serves(table, &invocation, credentials) {
        return Err(crate::error::Exit::failed(
            "This database hashes passwords with parameters this command cannot \
             reproduce, so it will not write a user.",
        ));
    }

    // A filtered verb parses its wire pairs, while `create` reads them as the new
    // entity's field values and `load` opens a file it will walk as it writes.
    let mut filter = None;
    let mut incoming = Vec::new();
    let mut source = None;
    if invocation.verb.filters() {
        let parsed = EntityFilter::parse(table, &invocation.pairs).map_err(refused)?;
        filter = Some(parsed);
    } else if invocation.verb == Verb::Create {
        let Some(built) = ceres_database::build_entity(table, &invocation.pairs, credentials)
        else {
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
        let Some(batches) = ceres_database::entity_batches(table, file, load_format, credentials)
        else {
            return Err(crate::error::Exit::failed(
                "The file's first row does not name the columns to load.",
            ));
        };

        source = Some(batches);
    }

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
            let affected = store.count_entity_filter(filter()).await?;
            match crate::commands::dump::confirmed(invocation.verb, affected, table.name()) {
                Ok(true) => {}
                Ok(false) => return Ok(Rendered::Declined),
                Err(message) => return Ok(Rendered::Failed(message)),
            }
        }

        match invocation.verb {
            Verb::Count => store
                .count_entity_filter(filter())
                .await
                .map(|count| Rendered::Text(format!("{count}\n"))),
            Verb::Any => store
                .any_entity_filter(filter())
                .await
                .map(Rendered::Exists),
            // A filtered write reports how many rows it touched, or the rows
            // themselves when `--collect` asked for them.
            Verb::Delete if invocation.collect => {
                let touched = store.delete_entity_filter_returning(filter()).await?;
                render(&touched, format, &projection, header, colored)
                    .map(|bytes| drawn(Rendered::Bytes(bytes), format, colored))
            }
            Verb::Delete => store
                .delete_entity_filter(filter())
                .await
                .map(|affected| Rendered::Text(format!("{affected}\n"))),
            Verb::Update => {
                let assign = invocation
                    .assign
                    .as_deref()
                    .expect("an update carries its assignments");
                if invocation.collect {
                    let touched = store
                        .update_entity_filter_returning(filter(), assign, credentials)
                        .await?;
                    render(&touched, format, &projection, header, colored)
                        .map(|bytes| drawn(Rendered::Bytes(bytes), format, colored))
                } else {
                    store
                        .update_entity_filter(filter(), assign, credentials)
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
                    .load_entities(batches, conflict)
                    .await
                    .map(|written| Rendered::Text(format!("{written}\n")))
            }
            // An entity group declares no `follow`, so the surface refuses the verb
            // before anything reaches here.
            Verb::Follow => unreachable!("an entity group declares no follow"),
            Verb::Create => {
                store
                    .load_entities(
                        incoming.iter().cloned().map(Ok),
                        ceres_database::Conflict::Error,
                    )
                    .await?;
                render(&incoming[0], format, &projection, header, colored)
                    .map(|bytes| drawn(Rendered::Bytes(bytes), format, colored))
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
                    .stream_entity_filter(filter(), &mut |entities| {
                        let heading = sink.heading();
                        let rendered = render(&entities, format, &projection, heading, colored)?;
                        sink.push(rendered).map_err(written)
                    })
                    .await;

                finish(sink, outcome).map(|rendered| drawn(rendered, format, colored))
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

/// The credential rules this database's writes follow, `None` when a configured
/// parameter is outside what the hashing takes.
///
/// Both algorithms a configuration can name are produced here, so the answer is `None`
/// only for a parameter that would not hash at all, which the configuration layer should
/// already have refused.
fn credentials(database: &DatabaseConfig) -> Option<Credentials> {
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

/// Whether the native path serves this verb on this table.
///
/// Every table but users serves whatever it is given. A user's writes hash a password
/// and normalize an email address with the database's own parameters, so without rules
/// to do that they stay in Python. A user's reads never need them.
fn serves(table: EntityTable, invocation: &Invocation, credentials: Option<Credentials>) -> bool {
    if table != EntityTable::Users {
        return true;
    }

    !invocation.verb.writes() || credentials.is_some()
}

/// Render a set of entities in the shape the invocation asked for.
fn render(
    entities: &Entities,
    format: DumpFormat,
    projection: &[(String, String)],
    header: bool,
    colored: bool,
) -> std::result::Result<Vec<u8>, ceres_database::Error> {
    let rendered = match (format, projection.is_empty()) {
        // A table is drawn once the whole result is in hand, so each chunk
        // renders as JSON lines here and the drawing happens at the end.
        (DumpFormat::Table, true) => entities.to_json_lines(),
        (DumpFormat::Table, false) => entities.to_json_lines_projected(projection),
        (DumpFormat::Json, true) => entities.to_json_lines(),
        (DumpFormat::Json, false) => entities.to_json_lines_projected(projection),
        (DumpFormat::Csv, true) => Ok(entities.to_csv_lines(header).into_bytes()),
        (DumpFormat::Csv, false) => entities
            .to_csv_lines_projected(projection, header)
            .map(String::into_bytes),
    };
    rendered
        .map(|bytes| crate::commands::dump::painted(bytes, format, colored))
        .map_err(|error| ceres_database::Error::Decode(error.to_string()))
}

/// What to say about a filter the compiler will not take.
///
/// An invalid value carries its own sentence, and a construct outside the grammar names
/// itself, because both are things the reader wrote and can change.
fn refused(refusal: ceres_database::Refusal) -> crate::error::Exit {
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
        // Argon2id is what a database configures unless it says otherwise, so the
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
                serves(EntityTable::Users, &invocation, rules()),
                "{arguments:?}"
            );
        }

        // Without them a user's writes cannot go through here, because storing a
        // password hashed some other way than the database asked for is worse than not
        // storing it. Reads carry on natively.
        for arguments in [
            &["create", "--username", "ada"][..],
            &["load", "users.jsonl"][..],
            &["update", "--assign", "{}"][..],
        ] {
            let invocation = read(EntityTable::Users, arguments);
            assert!(
                !serves(EntityTable::Users, &invocation, None),
                "{arguments:?}"
            );
        }
        assert!(serves(
            EntityTable::Users,
            &read(EntityTable::Users, &["select"]),
            None
        ));

        // No other table has a column these rules touch, so none of them ever needs one.
        for table in [
            EntityTable::Variables,
            EntityTable::Settings,
            EntityTable::Workspaces,
        ] {
            assert!(serves(
                table,
                &read(table, &["create", "--name", "x"]),
                None
            ));
            assert!(serves(table, &read(table, &["load", "rows.jsonl"]), None));
        }
    }

    #[test]
    fn a_bcrypt_database_serves_its_user_writes_too() {
        // bcrypt is the other algorithm a configuration can name, and it is produced
        // here as well, so a database on it writes its users natively like any other.
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
        // A boolean is a `--key` and `--no-key` pair, so a token following one is a
        // positional field rather than the boolean's value. The form comes from the
        // field's family, so the surface and the compiler cannot disagree about what
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
        // be able to set one, so the two surfaces are built from different lists.
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
