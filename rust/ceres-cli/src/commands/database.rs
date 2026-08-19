//! The `database` command group: schema DDL, migrations, clearing, and the shell.
//!
//! Everything here runs on the native store, reading the project's database
//! configuration directly, so no command in the group needs the Python runtime.

use std::collections::HashSet;
use std::io::Write;
use std::path::Path;

use ceres_config::{DatabaseConfig, SharedDatabaseConfig};
use ceres_database::migrations::{self, Migration, MigrationReporter, ReporterError};
use ceres_database::{EntityTable, RecordStore, RecordTable, SqlDialect};

use crate::commands::dump::{open_postgres, shared_hooks};
use crate::error::{Exit, Result};
use crate::output::Output;
use crate::project::Project;
use crate::runtime;

/// The dialect a configuration's scripts render in.
fn dialect(config: &DatabaseConfig) -> SqlDialect {
    match config {
        DatabaseConfig::Sqlite(_) | DatabaseConfig::Turso(_) => SqlDialect::SqliteText,
        DatabaseConfig::Postgres(_) => SqlDialect::Postgres,
    }
}

/// A resolved database file for the SQLite family.
///
/// A configuration naming no path gets a temporary file, the way an unconfigured
/// database runs everywhere else, and the command that resolved it deletes it on the
/// way out.
struct DatabaseFile {
    path: String,
    temporary: bool,
}

impl DatabaseFile {
    /// Resolve the configured path, or make a temporary one under the given extension.
    ///
    /// A relative path names a file beside the configuration, so the same project opens
    /// the same database whatever directory the command ran from.
    fn resolve(path: Option<&Path>, directory: &Path, extension: &str) -> Result<Self> {
        match path {
            Some(path) => {
                let path = ceres_config::resolve_path(path, directory);
                let absolute = std::path::absolute(&path).map_err(|error| {
                    Exit::failed(format!("Cannot resolve {}. {error}", path.display()))
                })?;
                Ok(Self {
                    path: absolute.to_string_lossy().into_owned(),
                    temporary: false,
                })
            }
            None => {
                let name = format!("ceres-{}.{extension}", uuid::Uuid::new_v4());
                Ok(Self {
                    path: std::env::temp_dir()
                        .join(name)
                        .to_string_lossy()
                        .into_owned(),
                    temporary: true,
                })
            }
        }
    }

    /// Delete a temporary database and the sidecar files its journal modes write.
    fn cleanup(&self) {
        if !self.temporary {
            return;
        }

        for suffix in ["", "-wal", "-shm", "-journal"] {
            let _ = std::fs::remove_file(format!("{}{suffix}", self.path));
        }
    }
}

/// Open the project's writable store, creating a missing SQLite-family file.
///
/// This differs from the dump commands' opener in one way: those read an existing
/// database and refuse a missing file, while `migrate` exists to create one.
fn open_writable(
    config: &DatabaseConfig,
    directory: &Path,
) -> Result<(tokio::runtime::Runtime, RecordStore, DatabaseFile)> {
    // Pool construction spawns maintenance tasks, so the runtime has to exist first.
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("the runtime always builds");
    let guard = runtime.enter();

    let (store, file) = match config {
        DatabaseConfig::Sqlite(sqlite) => {
            let file = DatabaseFile::resolve(sqlite.path.as_deref(), directory, "sqlite")?;
            let (on_init, on_connect, on_close) = shared_hooks(&sqlite.shared);
            let store = RecordStore::sqlite_writable(&file.path, on_init, on_connect, on_close)
                .map_err(|error| Exit::failed(format!("Cannot open {}. {error}", file.path)))?;
            (store, file)
        }
        DatabaseConfig::Turso(turso) => {
            let file = DatabaseFile::resolve(turso.path.as_deref(), directory, "turso")?;
            let (on_init, on_connect, on_close) = shared_hooks(&turso.shared);
            let store = RecordStore::turso(&file.path, turso.mvcc, on_init, on_connect, on_close);
            (store, file)
        }
        DatabaseConfig::Postgres(postgres) => {
            let store = open_postgres(postgres).map_err(Exit::failed)?;
            let file = DatabaseFile {
                path: String::new(),
                temporary: false,
            };
            (store, file)
        }
    };

    drop(guard);
    Ok((runtime, store, file))
}

/// Ask the database a question it can answer without a schema.
async fn ping(store: &RecordStore) -> Result<()> {
    store
        .fetch_dynamic(None, "SELECT 1", Vec::new())
        .await
        .map(|_| ())
        .map_err(|_| Exit::failed("Failed to connect to database."))
}

/// Ask a yes/no question on stderr, reading answers until one decides.
///
/// A closed stdin cannot consent, so it declines cleanly instead of crashing.
fn confirmed(question: &str) -> Result<bool> {
    use std::io::BufRead;

    loop {
        let mut stderr = std::io::stderr();
        write!(stderr, "{question} (y/n): ")
            .and_then(|()| stderr.flush())
            .map_err(|error| Exit::failed(format!("Cannot ask for confirmation. {error}")))?;

        let mut answer = String::new();
        let read = std::io::stdin()
            .lock()
            .read_line(&mut answer)
            .map_err(|error| Exit::failed(format!("Cannot read an answer. {error}")))?;
        if read == 0 {
            return Ok(false);
        }

        match answer.trim().to_ascii_lowercase().as_str() {
            "y" | "yes" => return Ok(true),
            "n" | "no" => return Ok(false),
            _ => {}
        }
    }
}

/// Open the project's writable store, run one command against it, and clean up.
///
/// The store closes before a temporary database file is deleted, so its pool never
/// touches a file on the way out.
fn with_store(project: &Project, run: impl AsyncFnOnce(&RecordStore) -> Result<()>) -> Result<()> {
    let meta = project.load_meta()?;
    let (runtime, store, file) = open_writable(&meta.database, project.directory())?;
    let outcome = runtime.block_on(run(&store));
    drop(store);
    file.cleanup();
    outcome
}

/// Print the DDL statements used for database initialization to stdout.
pub fn ddl(project: &Project) -> Result<()> {
    let meta = project.load_meta()?;
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    for script in migrations::ddl(migrations::all(), dialect(&meta.database)) {
        let _ = writeln!(lock, "{script}");
    }

    Ok(())
}

/// Print each known migration with its applied or pending status.
pub fn list_migrations(project: &Project, output: &Output) -> Result<()> {
    with_store(project, async |store| {
        ping(store).await?;
        let applied = applied_set(store).await?;

        for migration in migrations::all() {
            let status = if applied.contains(&migration.id()) {
                "applied"
            } else {
                "pending"
            };
            output.write(format!(
                "{}: {} ({status})",
                migration.id(),
                migration.name()
            ));
        }

        for id in unknown_ids(&applied) {
            output.write(format!(
                "{id}: unknown (database is newer than this version)"
            ));
        }

        Ok(())
    })
}

/// List pending migrations, prompt for confirmation, and apply them in order.
pub fn migrate(project: &Project, output: &Output, yes: bool) -> Result<()> {
    with_store(project, async |store| run_migrate(store, output, yes).await)
}

async fn run_migrate(store: &RecordStore, output: &Output, yes: bool) -> Result<()> {
    ping(store).await?;

    let applied = applied_set(store).await?;
    refuse_unknown(&applied)?;

    let pending: Vec<&Migration> = migrations::all()
        .iter()
        .filter(|migration| !applied.contains(&migration.id()))
        .collect();
    if pending.is_empty() {
        output.write("Database is up to date.");
        return Ok(());
    }

    // A database with nothing applied is being created, so the run reads as one step.
    let bootstrapping = applied.is_empty();
    let question = if bootstrapping {
        "Create the project database?"
    } else {
        for migration in &pending {
            output.write(format!("{}: {}", migration.id(), migration.name()));
        }

        "Apply the above migrations now?"
    };

    if !yes && !confirmed(question)? {
        output.write("Database has not been modified.");
        return Ok(());
    }

    let mut reporter = Progress {
        output,
        announce: !bootstrapping,
    };
    let applied = migrations::migrate(store, migrations::all(), &mut reporter)
        .await
        .map_err(|error| Exit::failed(error.to_string()))?;

    if bootstrapping {
        output.write(format!(
            "Created the database with {} migration(s).",
            applied.len()
        ));
    } else {
        output.write(format!("Applied {} migration(s).", applied.len()));
    }

    Ok(())
}

/// Name the migration running now and say how far through the list it is.
///
/// Bootstrapping runs announce nothing per migration, the run reading as one step, but
/// a destructive migration's warning is printed either way.
struct Progress<'output> {
    output: &'output Output,
    announce: bool,
}

impl MigrationReporter for Progress<'_> {
    fn starting(
        &mut self,
        migration: &Migration,
        index: usize,
        total: usize,
    ) -> std::result::Result<(), ReporterError> {
        if self.announce {
            self.output.write(format!(
                "{:04} {} ({}/{total})",
                migration.id(),
                migration.name(),
                index + 1
            ));
        }

        if let Some(warning) = migrations::destructive_warning(migration.name()) {
            self.output.warn(format!(
                "Migration {} ({}) is destructive. {warning}",
                migration.id(),
                migration.name()
            ));
        }

        Ok(())
    }

    fn finished(&mut self, _: &Migration) -> std::result::Result<(), ReporterError> {
        Ok(())
    }
}

/// Prompt for confirmation, then truncate every table in the project database.
pub fn clear(project: &Project, output: &Output) -> Result<()> {
    with_store(project, async |store| run_clear(store, output).await)
}

async fn run_clear(store: &RecordStore, output: &Output) -> Result<()> {
    ping(store).await?;
    if !migrations::initialized(store)
        .await
        .map_err(|error| Exit::failed(error.to_string()))?
    {
        return Err(Exit::failed("Database appears uninitialized, exiting."));
    }

    assert_schema_current(store).await?;

    if !confirmed("Clear all data from the project database?")? {
        output.write("Database has not been modified. Exiting.");
        return Ok(());
    }

    let started = std::time::Instant::now();

    // Deleting in reverse of the stored order empties a table only once nothing points
    // at it, so foreign keys never block the sweep.
    let tables: Vec<&str> = RecordTable::ALL
        .iter()
        .map(RecordTable::name)
        .chain(EntityTable::ALL.iter().map(EntityTable::name))
        .collect();
    let deletes: Vec<String> = tables
        .iter()
        .rev()
        .map(|table| format!("DELETE FROM {table};"))
        .collect();
    store
        .execute_script(&deletes.join("\n"))
        .await
        .map_err(|error| Exit::failed(error.to_string()))?;

    output.write(format!(
        "Cleared all data from database in {:.2}s.",
        started.elapsed().as_secs_f64()
    ));
    Ok(())
}

/// Verify the database schema matches this version of Ceres.
async fn assert_schema_current(store: &RecordStore) -> Result<()> {
    let applied = applied_set(store).await?;
    refuse_unknown(&applied)?;

    let pending = migrations::all()
        .iter()
        .filter(|migration| !applied.contains(&migration.id()))
        .count();
    if pending > 0 {
        return Err(Exit::failed(format!(
            "Database has {pending} pending migration(s). Run `ceres database migrate` to \
             apply {}.",
            if pending == 1 { "it" } else { "them" }
        )));
    }

    Ok(())
}

/// Launch the appropriate database shell, replacing this process.
pub fn shell(project: &Project) -> Result<()> {
    let meta = project.load_meta()?;
    let mut command;
    match &meta.database {
        DatabaseConfig::Postgres(postgres) => {
            // The server has to be reachable before the shell is worth launching, and
            // the failure should name the database rather than be psql's to explain.
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("the runtime always builds");
            let guard = runtime.enter();
            let store = open_postgres(postgres).map_err(Exit::failed)?;
            drop(guard);
            runtime.block_on(ping(&store))?;
            drop(store);

            command = executable("psql")?;
            command.arg("--host").arg(&postgres.host);
            if let Some(port) = postgres.port {
                command.arg("--port").arg(port.to_string());
            }

            command.arg("--user").arg(&postgres.user);
            command.arg(&postgres.database);
            if let Some(password) = &postgres.password {
                command.env("PGPASSWORD", password.expose());
            }
        }
        DatabaseConfig::Turso(turso) if turso.mvcc => {
            let file = DatabaseFile::resolve(turso.path.as_deref(), project.directory(), "turso")?;
            return Err(Exit::failed(format!(
                "MVCC journaling makes the database file unreadable to 'sqlite3'. Use \
                 Turso's own shell against it instead, for example: tursodb {}",
                file.path
            )));
        }
        DatabaseConfig::Sqlite(sqlite) => {
            command = sqlite_shell(project, sqlite.path.as_deref(), &sqlite.shared, "sqlite")?;
        }
        DatabaseConfig::Turso(turso) => {
            command = sqlite_shell(project, turso.path.as_deref(), &turso.shared, "turso")?;
        }
    }

    match runtime::replace(command)? {}
}

/// The `sqlite3` invocation for a SQLite-family database, hooks applied.
fn sqlite_shell(
    project: &Project,
    path: Option<&Path>,
    shared: &SharedDatabaseConfig,
    extension: &str,
) -> Result<std::process::Command> {
    let file = DatabaseFile::resolve(path, project.directory(), extension)?;

    let mut command = executable("sqlite3")?;
    command.arg(&file.path);
    // The setup statements run silenced so the shell opens quiet, then output comes back
    // for the session itself.
    command.args(["-cmd", &format!(".output {}", os_null())]);
    // What the store sets on every connection it opens so the shell sees the database the
    // way the running engine does. A shell without foreign keys on would let a statement
    // through that the engine would refuse.
    for statement in ["PRAGMA foreign_keys = ON", "PRAGMA busy_timeout = 30000"] {
        command.args(["-cmd", statement]);
    }

    for statement in shared.hooks.connect.iter().flatten() {
        command.args(["-cmd", statement]);
    }

    for statement in shared.hooks.init.iter().flatten() {
        command.args(["-cmd", statement]);
    }

    command.args(["-cmd", ".output"]);
    Ok(command)
}

/// The platform's discard file, where the shell's setup output goes.
fn os_null() -> &'static str {
    if cfg!(unix) { "/dev/null" } else { "NUL" }
}

/// A shell executable that has to be installed to serve the command.
fn executable(name: &str) -> Result<std::process::Command> {
    match runtime::which(name) {
        Some(path) => Ok(std::process::Command::new(path)),
        None => Err(Exit::failed(format!(
            "Executable {name:?} was not found in system path. It must be installed to \
             use this command."
        ))),
    }
}

/// The applied migration IDs as a set, with store failures worded for the reader.
async fn applied_set(store: &RecordStore) -> Result<HashSet<i64>> {
    migrations::applied_ids(store)
        .await
        .map(|ids| ids.into_iter().collect())
        .map_err(|error| Exit::failed(error.to_string()))
}

/// The applied migration IDs this version does not know about, in ascending order.
fn unknown_ids(applied: &HashSet<i64>) -> Vec<i64> {
    let known: HashSet<i64> = migrations::all().iter().map(Migration::id).collect();
    let mut unknown: Vec<i64> = applied
        .iter()
        .copied()
        .filter(|id| !known.contains(id))
        .collect();
    unknown.sort_unstable();
    unknown
}

/// Refuse to touch a database whose applied migrations outrun this version.
fn refuse_unknown(applied: &HashSet<i64>) -> Result<()> {
    let unknown = unknown_ids(applied);
    if unknown.is_empty() {
        return Ok(());
    }

    Err(Exit::failed(format!(
        "Database contains migrations unknown to this version of ceres: {}. The database \
         is newer than the running version.",
        join_ids(&unknown)
    )))
}

/// Comma-separated IDs, for the messages that list them.
fn join_ids(ids: &[i64]) -> String {
    ids.iter()
        .map(i64::to_string)
        .collect::<Vec<_>>()
        .join(", ")
}
