//! What the table commands do to a real database.
//!
//! Every test here runs the built binary against a temporary SQLite project and then
//! reads the rows back, because what a write did is the only thing worth asserting about
//! it. The unit tests cover how an invocation parses, which is a different question.
//!
//! `CERES_PYTHON` is pointed at a path that does not exist, so any command that hands off
//! to the Python runtime fails loudly instead of quietly passing. That is deliberate.
//! These commands are meant to be served natively end to end, and a test suite that
//! cannot tell the difference would not notice them slipping back.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};

/// A temporary project the binary can be pointed at.
struct Project {
    directory: tempfile::TempDir,
}

impl Project {
    /// Build a project whose database holds the rows every test starts from.
    async fn seed() -> Self {
        let directory = tempfile::tempdir().expect("a temporary directory");
        let database = directory.path().join("records.sqlite");

        // The configuration names the database by absolute path, so the binary finds it
        // whatever directory the test process happens to be in.
        std::fs::write(
            directory.path().join("ceres.yaml"),
            format!(
                "components: []\ndatabase:\n  type: sqlite\n  path: {}\n",
                database.display()
            ),
        )
        .expect("the configuration writes");

        let url = format!("sqlite://{}?mode=rwc", database.display());
        let pool = sqlx::SqlitePool::connect(&url)
            .await
            .expect("the database opens");

        // The column types are the migration's own.
        sqlx::query(
            "CREATE TABLE variables (address TEXT, name TEXT, value JSON, \
             PRIMARY KEY (address, name))",
        )
        .execute(&pool)
        .await
        .expect("the table is created");

        for (address, name, value) in [
            ("@motor", "speed", "5"),
            ("@motor", "torque", "2"),
            ("@sensor", "reading", "1.5"),
            ("@sensor", "enabled", "true"),
        ] {
            sqlx::query("INSERT INTO variables VALUES (?, ?, ?)")
                .bind(address)
                .bind(name)
                .bind(value)
                .execute(&pool)
                .await
                .expect("the row inserts");
        }

        pool.close().await;
        Self { directory }
    }

    fn config(&self) -> PathBuf {
        self.directory.path().join("ceres.yaml")
    }

    fn path(&self) -> &Path {
        self.directory.path()
    }

    /// Run the binary against this project.
    fn run(&self, arguments: &[&str]) -> Output {
        self.run_with(&["--no-color"], arguments, &[])
    }

    /// Run the binary as though someone were reading its output at a terminal.
    fn watched(&self, arguments: &[&str]) -> Output {
        self.run_with(&[], arguments, &[("FORCE_COLOR", "1")])
    }

    /// Run the binary with explicit global flags and environment.
    fn run_with(
        &self,
        globals: &[&str],
        arguments: &[&str],
        environment: &[(&str, &str)],
    ) -> Output {
        Command::new(env!("CARGO_BIN_EXE_ceres"))
            .arg("--config")
            .arg(self.config())
            .args(globals)
            .args(arguments)
            // A command that hands off to Python cannot find an interpreter here, so
            // delegation shows up as a failure rather than as a quiet pass.
            .env("CERES_PYTHON", self.path().join("no-such-interpreter"))
            .envs(environment.iter().copied())
            .output()
            .expect("the binary runs")
    }

    /// Every variable in the database, as `address name value` lines.
    async fn variables(&self) -> Vec<String> {
        let url = format!(
            "sqlite://{}",
            self.directory.path().join("records.sqlite").display()
        );
        let pool = sqlx::SqlitePool::connect(&url)
            .await
            .expect("the database opens");
        let rows: Vec<(String, String, String)> = sqlx::query_as(
            "SELECT address, name, CAST(value AS TEXT) FROM variables ORDER BY address, name",
        )
        .fetch_all(&pool)
        .await
        .expect("the rows read");

        pool.close().await;
        rows.into_iter()
            .map(|(address, name, value)| format!("{address} {name} {value}"))
            .collect()
    }
}

/// The standard output of a command that was expected to succeed.
fn succeeded(output: &Output) -> String {
    assert!(
        output.status.success(),
        "the command failed with {:?}\n{}",
        output.status.code(),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout.clone()).expect("the output is text")
}

#[tokio::test]
async fn a_select_reads_the_rows_it_was_filtered_to() {
    let project = Project::seed().await;

    let all = succeeded(&project.run(&["variables", "select"]));
    assert_eq!(all.lines().count(), 4, "{all}");

    let filtered = succeeded(&project.run(&["variables", "select", "--address", "@motor"]));
    assert_eq!(filtered.lines().count(), 2, "{filtered}");

    // A repeated key matches any of its values.
    let several =
        succeeded(&project.run(&["variables", "select", "--name", "speed", "--name", "torque"]));
    assert_eq!(several.lines().count(), 2, "{several}");
}

#[tokio::test]
async fn a_projection_selects_and_renames_the_output_fields() {
    let project = Project::seed().await;

    let rows = succeeded(&project.run(&[
        "variables",
        "select",
        "--address",
        "@motor",
        "name:label",
        "--data-format",
        "csv",
    ]));

    let mut lines = rows.lines();
    assert_eq!(lines.next(), Some("label"));
    assert_eq!(lines.next(), Some("speed"));
    assert_eq!(lines.next(), Some("torque"));
    assert_eq!(lines.next(), None);
}

#[tokio::test]
async fn a_count_and_an_existence_check_report_through_their_status() {
    let project = Project::seed().await;

    assert_eq!(succeeded(&project.run(&["variables", "count"])).trim(), "4");

    let present = project.run(&["variables", "any", "--name", "speed"]);
    assert!(present.status.success());
    assert_eq!(succeeded(&present).trim(), "true");

    // Nothing matching is the answer a shell condition reads off the exit status.
    let absent = project.run(&["variables", "any", "--name", "nope"]);
    assert_eq!(absent.status.code(), Some(1));
    assert_eq!(String::from_utf8_lossy(&absent.stdout).trim(), "false");
}

#[tokio::test]
async fn a_create_writes_one_row_and_reports_it() {
    let project = Project::seed().await;

    let created = succeeded(&project.run(&[
        "variables",
        "create",
        "--address",
        "@motor",
        "--name",
        "ratio",
        "--value",
        "7",
    ]));
    assert!(created.contains("ratio"), "{created}");

    assert!(
        project
            .variables()
            .await
            .contains(&"@motor ratio 7".to_string())
    );
}

#[tokio::test]
async fn a_write_goes_through_only_when_it_was_told_not_to_ask() {
    let project = Project::seed().await;

    // Tests do not run at a terminal, so a write that would ask is refused rather than
    // assumed. The rows stay exactly as they were.
    let asked = project.run(&["variables", "delete", "--address", "@motor"]);
    assert!(!asked.status.success());
    let refusal = String::from_utf8_lossy(&asked.stderr);
    assert!(refusal.contains("--no-confirm"), "{refusal}");
    assert_eq!(project.variables().await.len(), 4);

    // Saying so is what lets it through.
    let deleted =
        succeeded(&project.run(&["variables", "delete", "--address", "@motor", "--no-confirm"]));
    assert_eq!(deleted.trim(), "2");

    let left = project.variables().await;
    assert_eq!(left.len(), 2);
    assert!(
        left.iter().all(|row| row.starts_with("@sensor")),
        "{left:?}"
    );
}

#[tokio::test]
async fn an_update_assigns_the_values_it_was_given() {
    let project = Project::seed().await;

    let updated = succeeded(&project.run(&[
        "variables",
        "update",
        "--name",
        "speed",
        "--assign",
        "{\"value\": 9}",
        "--no-confirm",
    ]));
    assert_eq!(updated.trim(), "1");

    assert!(
        project
            .variables()
            .await
            .contains(&"@motor speed 9".to_string())
    );
}

#[tokio::test]
async fn a_load_reads_a_file_and_says_how_many_rows_it_wrote() {
    let project = Project::seed().await;
    let rows = project.path().join("rows.jsonl");
    std::fs::write(
        &rows,
        "{\"address\": \"@loaded\", \"name\": \"one\", \"value\": 1}\n\
         {\"address\": \"@loaded\", \"name\": \"two\", \"value\": 2}\n",
    )
    .expect("the file writes");

    let loaded =
        succeeded(&project.run(&["variables", "load", rows.to_str().expect("a text path")]));
    assert_eq!(loaded.trim(), "2");
    assert_eq!(project.variables().await.len(), 6);
}

#[tokio::test]
async fn a_load_of_a_file_that_is_not_there_says_so_and_changes_nothing() {
    let project = Project::seed().await;

    let missing = project.run(&["variables", "load", "absent.jsonl"]);
    assert!(!missing.status.success());
    let message = String::from_utf8_lossy(&missing.stderr);
    assert!(message.contains("absent.jsonl"), "{message}");
    assert_eq!(project.variables().await.len(), 4);
}

#[tokio::test]
async fn an_unknown_flag_is_refused_with_the_one_that_was_meant() {
    let project = Project::seed().await;

    let refused = project.run(&["variables", "select", "--naem", "speed"]);
    assert_eq!(refused.status.code(), Some(2));

    let message = String::from_utf8_lossy(&refused.stderr);
    assert!(message.contains("--naem"), "{message}");
    assert!(message.contains("--name"), "{message}");
}

#[tokio::test]
async fn help_is_answered_without_starting_an_interpreter() {
    let project = Project::seed().await;

    let help = succeeded(&project.run(&["variables", "select", "--help"]));
    // The filter surface is generated from the entity's own fields, so the table's
    // columns and the operations over them are all listed.
    assert!(help.contains("--address"), "{help}");
    assert!(help.contains("--name-contains"), "{help}");
    assert!(help.contains("--limit"), "{help}");
    // Booleans advertise the half that is not listed separately.
    assert!(help.contains("--no-internal"), "{help}");
    // And each verb carries examples written against this table's own fields.
    assert!(
        help.contains("ceres variables select --address @motor"),
        "{help}"
    );
}

#[tokio::test]
async fn a_dump_someone_is_reading_is_drawn_as_a_table() {
    let project = Project::seed().await;

    let table = succeeded(&project.watched(&["variables", "select", "--address", "@motor"]));
    assert!(table.contains('\u{256d}'), "{table}");
    assert!(table.contains("speed"), "{table}");
    assert!(table.contains("torque"), "{table}");
    // A table is columns, not one object per line.
    assert!(!table.contains('{'), "{table}");

    // The same command with nothing reading it stays machine-readable, so a script that
    // pipes this is unaffected by any of it.
    let piped = succeeded(&project.run(&["variables", "select", "--address", "@motor"]));
    assert!(piped.starts_with('{'), "{piped}");
}

#[tokio::test]
async fn a_dump_of_nothing_says_so_rather_than_printing_an_empty_box() {
    let project = Project::seed().await;

    let drawn = project.watched(&["variables", "select", "--name", "nothing-matches-this"]);
    assert_eq!(succeeded(&drawn).trim(), "No rows.");
}

#[tokio::test]
async fn a_collected_write_hands_back_the_rows_it_touched() {
    let project = Project::seed().await;

    // `--collect` answers with the rows themselves rather than how many there were,
    // which is what makes a write scriptable against what it actually changed.
    let touched = succeeded(&project.run(&[
        "variables",
        "update",
        "--address",
        "@motor",
        "--assign",
        "{\"value\": 9}",
        "--no-confirm",
        "--collect",
    ]));

    let rows: Vec<&str> = touched.lines().collect();
    assert_eq!(rows.len(), 2, "{touched}");
    assert!(
        rows.iter().all(|row| row.contains("\"value\":9")),
        "{touched}"
    );

    // The rows a delete collected are the ones that went, so they can be kept.
    let gone = succeeded(&project.run(&[
        "variables",
        "delete",
        "--address",
        "@motor",
        "--no-confirm",
        "--collect",
    ]));
    assert_eq!(gone.lines().count(), 2, "{gone}");
    assert_eq!(project.variables().await.len(), 2);
}

#[tokio::test]
async fn an_assignment_the_writer_will_not_take_says_why() {
    let project = Project::seed().await;

    // A column that is not there names the ones that are.
    let unknown = project.run(&[
        "variables",
        "update",
        "--name",
        "speed",
        "--assign",
        "{\"nope\": 1}",
        "--no-confirm",
    ]);
    assert!(!unknown.status.success());
    let message = String::from_utf8_lossy(&unknown.stderr);
    assert!(message.contains("`nope`"), "{message}");
    assert!(message.contains("`value`"), "{message}");

    // A column that identifies the row says so, rather than reporting it as missing.
    let identity = project.run(&[
        "variables",
        "update",
        "--name",
        "speed",
        "--assign",
        "{\"address\": \"@elsewhere\"}",
        "--no-confirm",
    ]);
    assert!(!identity.status.success());
    let message = String::from_utf8_lossy(&identity.stderr);
    assert!(message.contains("identifies a row"), "{message}");

    // Nothing was written by either, because a refusal happens before the transaction.
    assert!(
        project
            .variables()
            .await
            .contains(&"@motor speed 5".to_string())
    );
}

#[tokio::test]
async fn a_load_names_the_row_it_could_not_read() {
    let project = Project::seed().await;
    let rows = project.path().join("rows.jsonl");
    std::fs::write(
        &rows,
        "{\"address\": \"@loaded\", \"name\": \"one\", \"value\": 1}\nnot an object at all\n",
    )
    .expect("the file writes");

    let refused = project.run(&["variables", "load", rows.to_str().expect("a text path")]);
    assert!(!refused.status.success());

    let message = String::from_utf8_lossy(&refused.stderr);
    assert!(message.contains("Row 2"), "{message}");
    // A load either lands whole or not at all, so the good first row is not there.
    assert_eq!(project.variables().await.len(), 4);
}
