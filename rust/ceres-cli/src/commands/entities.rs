//! Native dumps for the non-record entities.
//!
//! Users, variables, settings, and workspaces take the same seven verbs the record
//! tables do, over the shared surface in [`dump`], so this module holds only what an
//! entity means. They are small tables an operator reads and edits, which makes the win
//! here the interpreter that never starts rather than the throughput of a large scan.
//!
//! Users are the one table whose writes carry rules of their own. A password hashes with
//! the database's configured Argon2 parameters and an email address normalizes, both
//! before the transaction opens, so a row written here is one the Python model would have
//! written identically. A database configured for bcrypt, or an address outside the subset
//! the normalizer understands, delegates rather than storing something else.

use std::ffi::OsString;
use std::path::Path;

use ceres_config::{DatabaseConfig, HashingConfig};
use ceres_database::{Argon2Params, Credentials, EntityFilter, EntityTable, Hashing};
use ceres_entities::Entities;

use crate::commands::dump::{
    DumpFormat, Invocation, Rendered, Sink, Verb, deliver, finish, open_store, written,
};
use crate::error::Result;
use crate::project::Project;

/// Attempt one entity command natively, `false` meaning the caller delegates.
pub fn try_run(table: EntityTable, config: Option<&Path>, raw: &[OsString]) -> Result<bool> {
    let Some(invocation) = Invocation::lex(raw, &EntityFilter::keys(table)) else {
        return Ok(false);
    };
    let Some(format) = invocation.dump_format() else {
        return Ok(false);
    };
    // Only the record tables declare a `follow`, so on an entity it is an argument
    // error the Python command owns.
    if invocation.verb.streams() {
        return Ok(false);
    }

    // The configuration is read before anything is built, because a user's own columns
    // are written under rules the database's own hashing configuration decides.
    let config = invocation.config.as_deref().or(config);
    let Ok(project) = Project::discover(config) else {
        return Ok(false);
    };
    let Ok(meta) = project.load_meta() else {
        return Ok(false);
    };

    let credentials = credentials(&meta.database);
    if !serves(table, &invocation, credentials) {
        return Ok(false);
    }

    // A filtered verb parses its wire pairs, while `create` reads them as the new
    // entity's field values and `load` opens a file it will walk as it writes.
    let mut filter = None;
    let mut incoming = Vec::new();
    let mut source = None;
    if invocation.verb.filters() {
        let Ok(parsed) = EntityFilter::parse(table, &invocation.pairs) else {
            return Ok(false);
        };

        filter = Some(parsed);
    } else if invocation.verb == Verb::Create {
        let Some(entities) = ceres_database::build_entity(table, &invocation.pairs, credentials)
        else {
            return Ok(false);
        };

        incoming.push(entities);
    } else {
        let Some((file, load_format)) = invocation.load_source() else {
            return Ok(false);
        };
        let Some(batches) = ceres_database::entity_batches(table, file, load_format, credentials)
        else {
            return Ok(false);
        };

        source = Some(batches);
    }

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
                .count_entity_filter(filter())
                .await
                .map(|count| Rendered::Text(format!("{count}\n"))),
            Verb::Any => store
                .any_entity_filter(filter())
                .await
                .map(Rendered::Exists),
            Verb::Delete => store
                .delete_entity_filter(filter())
                .await
                .map(|affected| Rendered::Text(format!("{affected}\n"))),
            Verb::Update => {
                let assign = invocation
                    .assign
                    .as_deref()
                    .expect("an update carries its assignments");
                store
                    .update_entity_filter(filter(), assign, credentials)
                    .await
                    .map(|affected| {
                        // Assignments the encoder refuses leave the table untouched, so
                        // the command delegates and Python owns the outcome.
                        affected.map_or(Rendered::Delegate, |affected| {
                            Rendered::Text(format!("{affected}\n"))
                        })
                    })
            }
            // A load reports how many rows it wrote, which the reader counts as it
            // walks the file, whatever the conflict mode then did with them.
            Verb::Load => {
                let conflict = invocation
                    .conflict()
                    .expect("a load resolved its conflict mode above");
                let batches = source.take().expect("a load opened its file above");
                store.load_entities(batches, conflict).await.map(|written| {
                    // A row the reader refused rolled the load back, so Python owns it.
                    written.map_or(Rendered::Delegate, |written| {
                        Rendered::Text(format!("{written}\n"))
                    })
                })
            }
            Verb::Follow => unreachable!("an entity group has no follow subcommand"),
            Verb::Create => {
                store
                    .load_entities(
                        incoming.iter().cloned().map(Some),
                        ceres_database::Conflict::Error,
                    )
                    .await?;
                render(&incoming[0], format, &projection, header).map(Rendered::Bytes)
            }
            // A select streams, rendering and writing each chunk as the driver yields
            // it, so the dump never holds more than one chunk however large the table.
            Verb::Select => {
                let mut sink = Sink::new(invocation.output.as_deref(), header);
                let outcome = store
                    .stream_entity_filter(filter(), &mut |entities| {
                        let heading = sink.heading();
                        let rendered = render(&entities, format, &projection, heading)?;
                        sink.push(rendered).map_err(written)
                    })
                    .await;

                finish(sink, outcome)
            }
        }
    });
    let Ok(rendered) = rendered else {
        return Ok(false);
    };

    deliver(&invocation, rendered)
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
) -> std::result::Result<Vec<u8>, ceres_database::Error> {
    let rendered = match (format, projection.is_empty()) {
        (DumpFormat::Json, true) => entities.to_json_lines(),
        (DumpFormat::Json, false) => entities.to_json_lines_projected(projection),
        (DumpFormat::Csv, true) => Ok(entities.to_csv_lines(header).into_bytes()),
        (DumpFormat::Csv, false) => entities
            .to_csv_lines_projected(projection, header)
            .map(String::into_bytes),
    };
    rendered.map_err(|error| ceres_database::Error::Decode(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raw(arguments: &[&str]) -> Vec<OsString> {
        arguments.iter().map(OsString::from).collect()
    }

    /// Lex against the table's boolean keys, the way the command dispatch does.
    fn lex(table: EntityTable, arguments: &[&str]) -> Invocation {
        Invocation::lex(&raw(arguments), &EntityFilter::keys(table)).unwrap()
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
            &["create", "--username", "ada", "--no-color"][..],
            &["load", "users.jsonl", "--no-color"][..],
            &["update", "--no-confirm", "--assign", "{}", "--no-color"][..],
            &["select", "--no-color"][..],
            &["count", "--no-color"][..],
        ] {
            assert!(
                serves(
                    EntityTable::Users,
                    &lex(EntityTable::Users, arguments),
                    rules()
                ),
                "{arguments:?}"
            );
        }

        // Without them, a user's writes stay in Python rather than storing a password
        // hashed some other way, while its reads carry on natively.
        for arguments in [
            &["create", "--username", "ada", "--no-color"][..],
            &["load", "users.jsonl", "--no-color"][..],
            &["update", "--no-confirm", "--assign", "{}", "--no-color"][..],
        ] {
            assert!(
                !serves(
                    EntityTable::Users,
                    &lex(EntityTable::Users, arguments),
                    None
                ),
                "{arguments:?}"
            );
        }
        assert!(serves(
            EntityTable::Users,
            &lex(EntityTable::Users, &["select", "--no-color"]),
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
                &lex(table, &["create", "--name", "x", "--no-color"]),
                None
            ));
            assert!(serves(
                table,
                &lex(table, &["load", "rows.jsonl", "--no-color"]),
                None
            ));
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
        // The Python CLI declares every boolean as a `--key` and `--no-key` pair, so a
        // token following one is a positional field rather than the boolean's value.
        // The arity comes from the field's family, so the parser and the compiler
        // cannot disagree about what `--owned` is.
        assert_eq!(
            EntityFilter::keys(EntityTable::Workspaces)
                .iter()
                .find(|key| key.key == "owned")
                .map(|key| key.arity),
            Some(ceres_database::Arity::Flag)
        );

        let invocation = lex(
            EntityTable::Workspaces,
            &["select", "--owned", "name", "--no-color"],
        );
        assert_eq!(
            invocation.pairs,
            vec![("owned".to_string(), "true".to_string())]
        );
        assert_eq!(
            invocation.projection(),
            vec![("name".to_string(), "name".to_string())]
        );

        let invocation = lex(
            EntityTable::Workspaces,
            &["select", "--no-show-when-logged-out", "--no-color"],
        );
        assert_eq!(
            invocation.pairs,
            vec![("show_when_logged_out".to_string(), "false".to_string())]
        );

        // A computed predicate is a boolean too, and a non-boolean key still takes the
        // argument that follows it.
        let invocation = lex(
            EntityTable::Variables,
            &["select", "--no-internal", "--name", "x", "--no-color"],
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
    fn an_entity_group_has_no_follow_to_serve() {
        // Only the record tables pass `follow=True` to the command factory, so `follow`
        // on an entity is an argument error the Python command owns.
        for table in [
            EntityTable::Users,
            EntityTable::Variables,
            EntityTable::Settings,
            EntityTable::Workspaces,
        ] {
            assert!(lex(table, &["follow", "--no-color"]).verb.streams());
        }
    }

    #[test]
    fn the_filter_is_what_refuses_an_unknown_key() {
        let invocation = lex(
            EntityTable::Variables,
            &[
                "select",
                "--name",
                "x",
                "--name-prefix",
                "y",
                "--limit",
                "3",
            ],
        );
        assert!(EntityFilter::parse(EntityTable::Variables, &invocation.pairs).is_ok());

        // A record-only construct is not part of the entity grammar.
        let windowed = lex(EntityTable::Variables, &["select", "--max-age", "2h"]);
        assert!(EntityFilter::parse(EntityTable::Variables, &windowed.pairs).is_err());
    }
}
