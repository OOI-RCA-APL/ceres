//! Ordered schema migrations and the runner that applies them.
//!
//! Every migration is a plain SQL script embedded from this crate's `migrations/`
//! directory, named `<id>-<name>.sql` for a script shared across dialects, or
//! `<id>-<name>.sqlite.sql` / `<id>-<name>.postgres.sql` when the SQL differs by backend.
//! The runner records each applied migration in a `migrations` bookkeeping table it
//! creates for itself. See [`migrate`] for how a script and its record travel together.

use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use include_dir::{Dir, include_dir};

use crate::dynamic::Cell;
use crate::entities::EntityTable;
use crate::filter::SqlDialect;
use crate::records::RecordTable;
use crate::store::{Error, RecordStore};

/// The migration script files, embedded at build time.
static FILES: Dir = include_dir!("$CARGO_MANIFEST_DIR/migrations");

/// Every known migration, in application order.
static MIGRATIONS: LazyLock<Vec<Migration>> = LazyLock::new(|| {
    let files = FILES.files().map(|file| {
        let name = file.path().to_string_lossy().into_owned();
        let content = std::str::from_utf8(file.contents())
            .expect("migration scripts are UTF-8")
            .to_owned();
        (name, content)
    });

    assemble(files).expect("the embedded migration files follow the naming convention")
});

const TABLE_DDL_SQLITE: &str = "CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
)";

const TABLE_DDL_POSTGRES: &str = "CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
)";

/// Return every known migration, in application order.
pub fn all() -> &'static [Migration] {
    &MIGRATIONS
}

/// The bookkeeping table's own DDL, in the given dialect's spelling.
///
/// The table is not an entity row, it is bookkeeping owned by the database layer.
pub fn table_ddl(dialect: SqlDialect) -> &'static str {
    match dialect {
        SqlDialect::SqliteText => TABLE_DDL_SQLITE,
        SqlDialect::Postgres => TABLE_DDL_POSTGRES,
    }
}

/// Return the warning to log before a migration that discards data runs.
///
/// A migration belongs here only while operators still have it ahead of them. Once every
/// deployment has run it the warning is noise on each load.
pub fn destructive_warning(name: &str) -> Option<&'static str> {
    let _ = name;
    None
}

/// Resolve a dialect name to the dialect it renders as.
///
/// Turso maps to SQLite because it reads and writes the same file format and takes the
/// same schema, so it has no scripts of its own. A name no backend answers to resolves to
/// nothing, and a migration renders only its shared script for it.
pub fn parse_dialect(value: &str) -> Option<SqlDialect> {
    match value {
        "sqlite" | "turso" => Some(SqlDialect::SqliteText),
        "postgres" | "postgresql" => Some(SqlDialect::Postgres),
        _ => None,
    }
}

/// Every script that creates the schema, in the order they run.
///
/// The migrations are the schema, so a fresh database runs the whole chain. The
/// bookkeeping table comes first since it records the rest as they are applied, and a
/// migration with no script for this dialect contributes nothing.
pub fn ddl(migrations: &[Migration], dialect: SqlDialect) -> Vec<String> {
    let scripts = migrations
        .iter()
        .filter_map(|migration| migration.render(Some(dialect)))
        .map(str::to_owned);

    std::iter::once(table_ddl(dialect).to_owned())
        .chain(scripts)
        .collect()
}

/// A single ordered schema migration backed by one or more SQL scripts.
#[derive(Clone, Debug, PartialEq)]
pub struct Migration {
    id: i64,
    name: String,
    scripts: Scripts,
}

/// A migration's SQL, one shared script or one per dialect.
#[derive(Clone, Debug, Default, PartialEq)]
struct Scripts {
    shared: Option<String>,
    sqlite: Option<String>,
    postgres: Option<String>,
}

impl Migration {
    /// Build a migration from its scripts, keyed by dialect with `None` for shared.
    ///
    /// Errors when a shared script is mixed with dialect-specific ones, or when two
    /// entries resolve to the same dialect.
    pub fn new(
        id: i64,
        name: impl Into<String>,
        scripts: impl IntoIterator<Item = (Option<SqlDialect>, String)>,
    ) -> Result<Self, String> {
        let mut held = Scripts::default();
        for (dialect, script) in scripts {
            let slot = match dialect {
                None => &mut held.shared,
                Some(SqlDialect::SqliteText) => &mut held.sqlite,
                Some(SqlDialect::Postgres) => &mut held.postgres,
            };
            if slot.is_some() {
                return Err(format!("Migration {id} has two scripts for one dialect."));
            }

            *slot = Some(script);
        }

        if held.shared.is_some() && (held.sqlite.is_some() || held.postgres.is_some()) {
            return Err(format!(
                "Migration {id} mixes a shared script with dialect-specific scripts."
            ));
        }

        Ok(Self {
            id,
            name: name.into(),
            scripts: held,
        })
    }

    /// Unique sequential identifier parsed from the filename prefix.
    pub fn id(&self) -> i64 {
        self.id
    }

    /// Kebab-case name parsed from the filename (e.g. `init`).
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Return the SQL text for a dialect, or `None` when this migration has no script for
    /// it (a recorded no-op). A shared script serves every dialect, `None` included.
    pub fn render(&self, dialect: Option<SqlDialect>) -> Option<&str> {
        if let Some(shared) = &self.scripts.shared {
            return Some(shared);
        }

        match dialect? {
            SqlDialect::SqliteText => self.scripts.sqlite.as_deref(),
            SqlDialect::Postgres => self.scripts.postgres.as_deref(),
        }
    }
}

/// Parse a migration filename into its ID, name, and optional dialect.
fn parse_filename(filename: &str) -> Option<(i64, &str, Option<SqlDialect>)> {
    let stem = filename.strip_suffix(".sql")?;
    let (stem, dialect) = if let Some(stem) = stem.strip_suffix(".sqlite") {
        (stem, Some(SqlDialect::SqliteText))
    } else if let Some(stem) = stem.strip_suffix(".postgres") {
        (stem, Some(SqlDialect::Postgres))
    } else {
        (stem, None)
    };

    let (id, name) = stem.split_once('-')?;
    if id.is_empty() || !id.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }

    let named = !name.is_empty()
        && name
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-');
    if !named {
        return None;
    }

    Some((id.parse().ok()?, name, dialect))
}

/// Build the ordered registry from migration files, validating the naming convention.
///
/// Errors when a filename does not match the convention, an ID is duplicated with
/// conflicting names, or an ID mixes shared and dialect-specific files.
pub fn assemble(
    files: impl IntoIterator<Item = (String, String)>,
) -> Result<Vec<Migration>, String> {
    let mut files: Vec<_> = files.into_iter().collect();
    files.sort_by(|(left, _), (right, _)| left.cmp(right));

    let mut names: HashMap<i64, String> = HashMap::new();
    let mut scripts: HashMap<i64, Vec<(Option<SqlDialect>, String)>> = HashMap::new();
    for (filename, content) in files {
        let Some((id, name, dialect)) = parse_filename(&filename) else {
            return Err(format!(
                "Migration filename {filename:?} does not match the naming convention \
                 '<id>-<name>.sql' or '<id>-<name>.<sqlite|postgres>.sql'."
            ));
        };

        if let Some(existing) = names.get(&id)
            && existing != name
        {
            return Err(format!(
                "Migration {id} has conflicting names: {existing:?} and {name:?}."
            ));
        }

        names.insert(id, name.to_owned());
        scripts.entry(id).or_default().push((dialect, content));
    }

    let mut ids: Vec<i64> = scripts.keys().copied().collect();
    ids.sort_unstable();
    ids.into_iter()
        .map(|id| {
            Migration::new(
                id,
                names.remove(&id).expect("every id was named"),
                scripts.remove(&id).expect("every id has scripts"),
            )
        })
        .collect()
}

/// Told which migration is running, for a caller showing progress as they apply.
///
/// A migration is one script the driver runs whole so there is nothing to report from
/// inside one. What a caller can show is which of them is running and how many are left.
/// An error aborts the run before the named migration is applied.
pub trait MigrationReporter {
    /// A migration is about to run. `index` is 0-based, `total` counts the pending.
    fn starting(
        &mut self,
        migration: &Migration,
        index: usize,
        total: usize,
    ) -> Result<(), ReporterError>;

    /// The migration that was running has landed and been recorded.
    fn finished(&mut self, migration: &Migration) -> Result<(), ReporterError>;
}

/// What stopped a reporter, carried back to the caller that supplied it.
pub type ReporterError = Box<dyn std::error::Error + Send + Sync>;

/// A reporter for callers with no progress to show.
pub struct SilentReporter;

impl MigrationReporter for SilentReporter {
    fn starting(&mut self, _: &Migration, _: usize, _: usize) -> Result<(), ReporterError> {
        Ok(())
    }

    fn finished(&mut self, _: &Migration) -> Result<(), ReporterError> {
        Ok(())
    }
}

/// What stopped a migration run.
#[derive(Debug, thiserror::Error)]
pub enum MigrateError {
    /// A migration's script failed, leaving it unapplied and the run stopped at it.
    #[error("Migration {id} ({name}) failed. {source}")]
    Migration {
        id: i64,
        name: String,
        source: Error,
    },
    /// Reading or creating the bookkeeping table failed.
    #[error(transparent)]
    Database(#[from] Error),
    /// The caller's reporter refused to continue.
    #[error(transparent)]
    Reporter(ReporterError),
}

/// Every table name this schema is the author of.
///
/// The entity and record tables come from the table enums, the single authority on what
/// the schema holds, and `migrations` is added because it is bookkeeping owned by this
/// layer rather than an entity row.
pub fn owned_table_names() -> impl Iterator<Item = &'static str> {
    RecordTable::ALL
        .iter()
        .map(RecordTable::name)
        .chain(EntityTable::ALL.iter().map(EntityTable::name))
        .chain(["migrations"])
}

/// Check whether this schema has been created in the database.
///
/// The question is whether any table this schema owns is there, not whether the database
/// holds a table at all. A configuration's `init` hook runs on connections opened before
/// any migration has, and one that creates a table of its own would otherwise make an
/// empty database look bootstrapped, leaving a project whose migrations never run and
/// whose schema is never created.
pub async fn initialized(store: &RecordStore) -> Result<bool, Error> {
    // The wording follows what each backend counts as a table of the caller's. Neither
    // backend's internal tables are the caller's, and on PostgreSQL neither is a table in
    // a schema this connection does not resolve names against.
    let sql = match store.dialect() {
        SqlDialect::Postgres => {
            "SELECT tablename AS name FROM pg_catalog.pg_tables \
             WHERE schemaname = ANY(current_schemas(false))"
        }
        SqlDialect::SqliteText => {
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        }
    };

    let rows = store.fetch_dynamic(None, sql, Vec::new()).await?;
    let present: HashSet<&str> = rows
        .iter()
        .flat_map(|row| row.iter())
        .filter_map(|(column, cell)| match cell {
            Cell::Text(name) if column == "name" => Some(name.as_str()),
            _ => None,
        })
        .collect();

    Ok(owned_table_names().any(|name| present.contains(name)))
}

/// Return the IDs of every migration recorded as applied, in ascending order.
///
/// Creates the bookkeeping table first so an empty database answers with an empty list
/// rather than an error.
pub async fn applied_ids(store: &RecordStore) -> Result<Vec<i64>, Error> {
    store.execute_script(table_ddl(store.dialect())).await?;
    let rows = store
        .fetch_dynamic(None, "SELECT id FROM migrations ORDER BY id", Vec::new())
        .await?;

    rows.iter()
        .flat_map(|row| row.iter())
        .filter(|(column, _)| column == "id")
        .map(|(_, cell)| match cell {
            Cell::Integer(id) => Ok(*id),
            other => Err(Error::Decode(format!(
                "a migration id decoded as {other:?} rather than an integer"
            ))),
        })
        .collect()
}

/// Apply every pending migration in order, recording each as it completes.
///
/// Each migration's script and the record that it ran go over as one batch so a migration
/// cannot land without being recorded and then run twice. The driver separates the
/// statements, which lets a script turn foreign keys off before rebuilding a table, a
/// pragma that does nothing inside a transaction someone else opened.
///
/// Returns the IDs of the migrations that were applied.
pub async fn migrate(
    store: &RecordStore,
    migrations: &[Migration],
    reporter: &mut (dyn MigrationReporter + Send),
) -> Result<Vec<i64>, MigrateError> {
    let recorded: HashSet<i64> = applied_ids(store).await?.into_iter().collect();
    let pending: Vec<&Migration> = migrations
        .iter()
        .filter(|migration| !recorded.contains(&migration.id))
        .collect();

    let mut applied = Vec::new();
    for (index, &migration) in pending.iter().enumerate() {
        reporter
            .starting(migration, index, pending.len())
            .map_err(MigrateError::Reporter)?;

        let record = format!("INSERT INTO migrations (id) VALUES ({});", migration.id);
        let script = match migration.render(Some(store.dialect())) {
            Some(sql) => format!("{};\n{record}", sql.trim_end().trim_end_matches(';')),
            None => record,
        };
        store
            .execute_script(&script)
            .await
            .map_err(|source| MigrateError::Migration {
                id: migration.id,
                name: migration.name.clone(),
                source,
            })?;

        applied.push(migration.id);
        reporter
            .finished(migration)
            .map_err(MigrateError::Reporter)?;
    }

    Ok(applied)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn file(name: &str) -> (String, String) {
        (name.to_owned(), "SELECT 1;".to_owned())
    }

    #[test]
    fn the_embedded_registry_parses() {
        let migrations = all();
        assert_eq!(migrations.len(), 8);
        assert_eq!(migrations[0].id(), 1);
        assert_eq!(migrations[0].name(), "init");

        let third = migrations.iter().find(|held| held.id() == 3).unwrap();
        assert!(third.render(Some(SqlDialect::SqliteText)).is_some());
        assert!(third.render(Some(SqlDialect::Postgres)).is_some());
    }

    #[test]
    fn assemble_parses_ids_names_and_dialects() {
        let migrations = assemble([
            file("0001-init.sqlite.sql"),
            file("0001-init.postgres.sql"),
            file("0002-remove-user-roles.sql"),
        ])
        .unwrap();

        assert_eq!(
            migrations.iter().map(Migration::id).collect::<Vec<_>>(),
            [1, 2]
        );
        assert_eq!(migrations[0].name(), "init");
        assert!(migrations[0].render(Some(SqlDialect::SqliteText)).is_some());
        assert!(migrations[0].render(Some(SqlDialect::Postgres)).is_some());
        assert!(migrations[0].render(None).is_none());
        assert!(migrations[1].render(None).is_some());
    }

    #[test]
    fn assemble_rejects_conflicting_names_for_one_id() {
        let error =
            assemble([file("0001-one.sqlite.sql"), file("0001-other.postgres.sql")]).unwrap_err();
        assert!(error.contains("conflicting names"));
    }

    #[test]
    fn assemble_rejects_duplicate_shared_ids() {
        let error = assemble([file("0001-one.sql"), file("0001-one.sqlite.sql")]).unwrap_err();
        assert!(error.contains("mixes a shared script"));
    }

    #[test]
    fn assemble_rejects_unrecognized_filenames() {
        for name in [
            "not-a-migration.sql",
            "0001-UPPER.sql",
            "0001-name.mysql.sql",
            "0001-.sql",
            "0001-name.txt",
        ] {
            assert!(assemble([file(name)]).is_err(), "{name} was accepted");
        }
    }

    #[test]
    fn assemble_accepts_an_empty_directory() {
        assert_eq!(assemble([]).unwrap(), []);
    }

    #[test]
    fn a_migration_without_a_dialect_script_is_a_noop() {
        let migrations = assemble([file("0001-postgres-only.postgres.sql")]).unwrap();
        assert!(migrations[0].render(Some(SqlDialect::SqliteText)).is_none());
        assert!(migrations[0].render(Some(SqlDialect::Postgres)).is_some());
    }

    #[test]
    fn dialect_names_resolve_like_the_backend_kinds() {
        assert_eq!(parse_dialect("sqlite"), Some(SqlDialect::SqliteText));
        assert_eq!(parse_dialect("turso"), Some(SqlDialect::SqliteText));
        assert_eq!(parse_dialect("postgres"), Some(SqlDialect::Postgres));
        assert_eq!(parse_dialect("postgresql"), Some(SqlDialect::Postgres));
        assert_eq!(parse_dialect("mysql"), None);
    }

    #[test]
    fn ddl_leads_with_the_bookkeeping_table() {
        let migrations = assemble([file("0001-first.sql")]).unwrap();
        let scripts = ddl(&migrations, SqlDialect::SqliteText);
        assert_eq!(scripts.len(), 2);
        assert!(scripts[0].contains("CREATE TABLE IF NOT EXISTS migrations"));
    }

    fn store(path: &std::path::Path) -> RecordStore {
        RecordStore::sqlite_writable(path.to_str().unwrap(), Vec::new(), Vec::new(), Vec::new())
            .unwrap()
    }

    fn migration(id: i64, name: &str, sql: &str) -> Migration {
        Migration::new(id, name, [(None, sql.to_owned())]).unwrap()
    }

    #[tokio::test]
    async fn initialized_answers_for_owned_tables_only() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        assert!(!initialized(&store).await.unwrap());

        // A table this schema does not own, as an `init` hook could create, must not
        // make an empty database look bootstrapped.
        store
            .execute_script("CREATE TABLE unrelated (id INTEGER PRIMARY KEY);")
            .await
            .unwrap();
        assert!(!initialized(&store).await.unwrap());

        let migrations = [migration(
            1,
            "first",
            "CREATE TABLE users (id INTEGER PRIMARY KEY);",
        )];
        migrate(&store, &migrations, &mut SilentReporter)
            .await
            .unwrap();
        assert!(initialized(&store).await.unwrap());
    }

    #[tokio::test]
    async fn migrate_applies_pending_in_order_and_is_idempotent() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        let migrations = [
            migration(1, "first", "CREATE TABLE first (id INTEGER PRIMARY KEY);"),
            migration(2, "second", "CREATE TABLE second (id INTEGER PRIMARY KEY);"),
        ];

        let applied = migrate(&store, &migrations, &mut SilentReporter)
            .await
            .unwrap();
        assert_eq!(applied, [1, 2]);
        assert_eq!(applied_ids(&store).await.unwrap(), [1, 2]);

        let again = migrate(&store, &migrations, &mut SilentReporter)
            .await
            .unwrap();
        assert_eq!(again, Vec::<i64>::new());
    }

    #[tokio::test]
    async fn a_failed_migration_names_itself_and_is_not_recorded() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        let migrations = [migration(
            1,
            "broken",
            "CREATE TABLE broken (this is not sql);",
        )];

        let error = migrate(&store, &migrations, &mut SilentReporter)
            .await
            .unwrap_err();
        assert!(
            error
                .to_string()
                .starts_with("Migration 1 (broken) failed.")
        );
        assert_eq!(applied_ids(&store).await.unwrap(), Vec::<i64>::new());
    }

    #[tokio::test]
    async fn a_reporter_is_told_each_migration_in_order() {
        struct Recorder(Vec<(String, i64, usize, usize)>);

        impl MigrationReporter for Recorder {
            fn starting(
                &mut self,
                migration: &Migration,
                index: usize,
                total: usize,
            ) -> Result<(), ReporterError> {
                self.0
                    .push(("starting".into(), migration.id(), index, total));
                Ok(())
            }

            fn finished(&mut self, migration: &Migration) -> Result<(), ReporterError> {
                self.0.push(("finished".into(), migration.id(), 0, 0));
                Ok(())
            }
        }

        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        let migrations = [
            migration(1, "first", "CREATE TABLE first (id INTEGER PRIMARY KEY);"),
            migration(2, "second", "CREATE TABLE second (id INTEGER PRIMARY KEY);"),
        ];

        let mut recorder = Recorder(Vec::new());
        migrate(&store, &migrations, &mut recorder).await.unwrap();
        assert_eq!(
            recorder.0,
            [
                ("starting".into(), 1, 0, 2),
                ("finished".into(), 1, 0, 0),
                ("starting".into(), 2, 1, 2),
                ("finished".into(), 2, 0, 0),
            ]
        );
    }

    #[tokio::test]
    async fn migrate_executes_multi_statement_scripts() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        let migrations = [migration(
            1,
            "multi",
            "CREATE TABLE one (id INTEGER PRIMARY KEY);\n\
             CREATE TABLE two (id INTEGER PRIMARY KEY);\n\
             CREATE INDEX ix_two ON two (id);",
        )];

        migrate(&store, &migrations, &mut SilentReporter)
            .await
            .unwrap();

        let tables = names(&store, "table").await;
        assert!(tables.contains("one") && tables.contains("two"));
        assert!(names(&store, "index").await.contains("ix_two"));
    }

    /// The names of every `kind` ("table" or "index") the schema holds.
    async fn names(store: &RecordStore, kind: &str) -> HashSet<String> {
        let rows = store
            .fetch_dynamic(
                None,
                "SELECT name FROM sqlite_master WHERE type = ?",
                vec![crate::Parameter::Text(kind.to_owned())],
            )
            .await
            .unwrap();
        rows.iter().map(|row| text(row, "name")).collect()
    }

    /// The column names of `table`, in declaration order.
    async fn columns(store: &RecordStore, table: &str) -> Vec<String> {
        let rows = store
            .fetch_dynamic(None, &format!("PRAGMA table_info({table})"), Vec::new())
            .await
            .unwrap();
        rows.iter().map(|row| text(row, "name")).collect()
    }

    /// The named column's text value in one row.
    fn text(row: &crate::Row, column: &str) -> String {
        match cell(row, column) {
            Cell::Text(held) => held.clone(),
            other => panic!("{column} holds {other:?} rather than text"),
        }
    }

    /// The named column's integer value in one row.
    fn integer(row: &crate::Row, column: &str) -> i64 {
        match cell(row, column) {
            Cell::Integer(held) => *held,
            other => panic!("{column} holds {other:?} rather than an integer"),
        }
    }

    fn cell<'row>(row: &'row crate::Row, column: &str) -> &'row Cell {
        &row.iter()
            .find(|(name, _)| name == column)
            .unwrap_or_else(|| panic!("no {column} column"))
            .1
    }

    async fn fetch(store: &RecordStore, sql: &str) -> Vec<crate::Row> {
        store.fetch_dynamic(None, sql, Vec::new()).await.unwrap()
    }

    #[tokio::test]
    async fn migration_2_transforms_the_old_schema() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        let baseline = all().iter().find(|held| held.id() == 1).unwrap();

        // Create workspaces with the pre-collapse check constraint first so the baseline
        // script's `CREATE TABLE IF NOT EXISTS` leaves it alone. This reproduces a
        // database that predates the baseline snapshot, where `general_*` still allowed
        // the wider 'operators' and 'admins' values migration 2 is responsible for
        // narrowing.
        store
            .execute_script(
                "CREATE TABLE workspaces (\
                 id CHAR(32) NOT NULL, \
                 name TEXT NOT NULL, \
                 general_viewership VARCHAR DEFAULT 'private' NOT NULL, \
                 general_editorship VARCHAR DEFAULT 'private' NOT NULL, \
                 general_managership VARCHAR DEFAULT 'private' NOT NULL, \
                 data JSON DEFAULT '{}' NOT NULL, \
                 CONSTRAINT pk_workspaces PRIMARY KEY (id), \
                 CONSTRAINT ck_workspaces__general_viewership \
                 CHECK (general_viewership IN ('anyone', 'operators', 'admins', 'private')), \
                 CONSTRAINT ck_workspaces__general_editorship \
                 CHECK (general_editorship IN ('anyone', 'operators', 'admins', 'private')), \
                 CONSTRAINT ck_workspaces__general_managership \
                 CHECK (general_managership IN ('anyone', 'operators', 'admins', 'private'))\
                 );",
            )
            .await
            .unwrap();
        store
            .execute_script(baseline.render(Some(SqlDialect::SqliteText)).unwrap())
            .await
            .unwrap();
        store
            .execute_script(
                "INSERT INTO users (id, username, email, password, role, disabled) VALUES \
                 ('u1', 'alice', 'a@a', 'x', 'admin', 0), \
                 ('u2', 'bob', 'b@b', 'x', 'operator', 0), \
                 ('u3', 'carol', 'c@c', 'x', 'viewer', 0);\n\
                 INSERT INTO workspaces (id, name, general_viewership, general_editorship, \
                 general_managership, data) VALUES \
                 ('w1', 'open', 'anyone', 'operators', 'admins', '{}');\n\
                 INSERT INTO settings (user_id, name, value) VALUES ('u1', 'theme', '\"dark\"');\n\
                 INSERT INTO workspace_memberships (user_id, workspace_id, role) VALUES \
                 ('u1', 'w1', 'viewer');",
            )
            .await
            .unwrap();

        migrate(&store, all(), &mut SilentReporter).await.unwrap();

        let users = fetch(&store, "SELECT id, admin FROM users ORDER BY id").await;
        let admins: Vec<(String, i64)> = users
            .iter()
            .map(|row| (text(row, "id"), integer(row, "admin")))
            .collect();
        assert_eq!(
            admins,
            [("u1".into(), 1), ("u2".into(), 0), ("u3".into(), 0)]
        );
        assert!(!columns(&store, "users").await.contains(&"role".into()));

        // The users table rebuild (required to drop `role` alongside its check
        // constraint) must preserve rows in tables that reference users by foreign key.
        let settings = fetch(
            &store,
            "SELECT user_id, name, value FROM settings WHERE user_id = 'u1'",
        )
        .await;
        assert_eq!(settings.len(), 1);
        assert_eq!(text(&settings[0], "name"), "theme");
        assert_eq!(text(&settings[0], "value"), "\"dark\"");

        // The workspaces table is rebuilt three separate times across the migration
        // sequence, to narrow its check constraints, to make the placement column
        // required, and to drop the general access columns. The row has to survive every
        // one of them.
        let workspaces = fetch(
            &store,
            "SELECT id, name, scope FROM workspaces WHERE id = 'w1'",
        )
        .await;
        assert_eq!(workspaces.len(), 1);
        assert_eq!(text(&workspaces[0], "name"), "open");
        assert_eq!(text(&workspaces[0], "scope"), "~");

        // The general access columns and the memberships table are gone by the end of the
        // sequence so a database that predates the baseline still lands on the current
        // schema.
        let held = columns(&store, "workspaces").await;
        assert!(!held.contains(&"general_viewership".into()));
        assert!(held.contains(&"owner_id".into()));

        assert!(
            !names(&store, "table")
                .await
                .contains("workspace_memberships")
        );
    }

    #[tokio::test]
    async fn migration_3_converts_root_grants_and_deletes_root_state() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));
        let baseline = all().iter().find(|held| held.id() == 1).unwrap();

        store
            .execute_script(baseline.render(Some(SqlDialect::SqliteText)).unwrap())
            .await
            .unwrap();
        store
            .execute_script(
                "INSERT INTO users (id, username, email, password, role, disabled) VALUES \
                 ('u1', 'alice', 'a@a', 'x', 'admin', 0);\n\
                 INSERT INTO user_permissions (user_id, target_type, target, level) VALUES \
                 ('u1', 'component', '@', 'operate');\n\
                 INSERT INTO variables (address, name, value) VALUES ('@', 'enabled', 'true');",
            )
            .await
            .unwrap();

        migrate(&store, all(), &mut SilentReporter).await.unwrap();

        let grants = fetch(
            &store,
            "SELECT target_type, target, level FROM user_permissions WHERE user_id = 'u1'",
        )
        .await;
        assert_eq!(grants.len(), 1);
        assert_eq!(text(&grants[0], "target_type"), "all");
        assert_eq!(text(&grants[0], "target"), "");
        assert_eq!(text(&grants[0], "level"), "operate");

        let counted = fetch(
            &store,
            "SELECT COUNT(*) AS count FROM variables WHERE address = '@'",
        )
        .await;
        assert_eq!(integer(&counted[0], "count"), 0);
    }

    // SQLite rebuilds a table by copying it, with foreign keys off across the swap. That
    // pragma does nothing inside a transaction someone else opened so a runner that
    // wrapped the whole script in one would leave the rebuilt tables without the
    // constraints the migration meant to carry over. It would do it without failing, and
    // the rows would still be there so the constraints themselves have to be checked.
    #[tokio::test]
    async fn a_table_rebuild_puts_back_the_foreign_keys_it_turned_off() {
        let directory = tempfile::tempdir().unwrap();
        let store = store(&directory.path().join("test.sqlite"));

        migrate(&store, all(), &mut SilentReporter).await.unwrap();

        let rows = fetch(
            &store,
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL",
        )
        .await;
        let schema: HashMap<String, String> = rows
            .iter()
            .map(|row| (text(row, "name"), text(row, "sql")))
            .collect();

        // Both of these are rebuilt by a later migration, and both point back at `users`.
        assert!(schema["group_memberships"].contains("REFERENCES users"));
        assert!(schema["user_permissions"].contains("REFERENCES users"));
    }
}
