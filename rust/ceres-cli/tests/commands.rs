//! What the table commands do to a real database.
//!
//! Every test here runs the built binary against a temporary SQLite project and then
//! reads the rows back because what a write did is the only thing worth asserting about
//! it. The unit tests cover how an invocation parses, which is a different question.
//!
//! `CERES_PYTHON` is pointed at a path that does not exist so any command that hands off
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

        // The configuration names the database by absolute path so the binary finds it
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

    /// Build a project whose database holds the groups and grants tables.
    ///
    /// These are separate from the seed above because no test needs both, and every test
    /// pays for whatever the seed it calls creates.
    async fn access() -> Self {
        let directory = tempfile::tempdir().expect("a temporary directory");
        let database = directory.path().join("records.sqlite");
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

        // The column types and the check constraints are the migrations' own so a value
        // the surface admits but the schema refuses fails here the way it would in a real
        // database. The foreign keys are left off because nothing here asserts what a
        // dangling reference does and creating them would mean creating `users` too.
        for statement in [
            "CREATE TABLE groups (id CHAR(32) NOT NULL, name TEXT NOT NULL, \
             description TEXT DEFAULT '' NOT NULL, CONSTRAINT pk_groups PRIMARY KEY (id), \
             CONSTRAINT uq_groups__name UNIQUE (name))",
            "CREATE TABLE group_memberships (user_id CHAR(32) NOT NULL, \
             group_id CHAR(32) NOT NULL, \
             CONSTRAINT pk_group_memberships PRIMARY KEY (user_id, group_id))",
            "CREATE TABLE group_permissions (group_id CHAR(32) NOT NULL, \
             target_type VARCHAR NOT NULL, target TEXT NOT NULL, level VARCHAR NOT NULL, \
             CONSTRAINT pk_group_permissions PRIMARY KEY (group_id, target_type, target), \
             CONSTRAINT ck_group_permissions__target_type \
             CHECK (target_type IN ('component', 'tag', 'all')), \
             CONSTRAINT ck_group_permissions__level CHECK (level IN ('view', 'operate', 'manage')))",
            "CREATE TABLE user_permissions (user_id CHAR(32) NOT NULL, \
             target_type VARCHAR NOT NULL, target TEXT NOT NULL, level VARCHAR NOT NULL, \
             CONSTRAINT pk_user_permissions PRIMARY KEY (user_id, target_type, target), \
             CONSTRAINT ck_user_permissions__target_type \
             CHECK (target_type IN ('component', 'tag', 'all')), \
             CONSTRAINT ck_user_permissions__level CHECK (level IN ('view', 'operate', 'manage')))",
        ] {
            sqlx::query(statement)
                .execute(&pool)
                .await
                .expect("the table is created");
        }

        sqlx::query("INSERT INTO groups VALUES ('019fbae5954c7321b29edfa121e5cdea', ?, ?)")
            .bind("operators")
            .bind("on call")
            .execute(&pool)
            .await
            .expect("the row inserts");

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

    /// Run the binary asking for columns, with color turned on.
    ///
    /// Both have to be said because neither is inferred. A dump is JSON lines whoever is
    /// reading it, and `FORCE_COLOR` decides only color.
    fn watched(&self, arguments: &[&str]) -> Output {
        let mut named: Vec<&str> = arguments.to_vec();
        named.extend(["--format", "table"]);
        self.run_with(&[], &named, &[("FORCE_COLOR", "1")])
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
        "--format",
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

    // Tests do not run at a terminal so a write that would ask is refused rather than
    // assumed. The rows stay exactly as they were.
    let asked = project.run(&["variables", "delete", "--address", "@motor"]);
    assert!(!asked.status.success());
    let refusal = String::from_utf8_lossy(&asked.stderr);
    assert!(refusal.contains("--no-confirm"), "{refusal}");
    assert_eq!(project.variables().await.len(), 4);

    // Saying so lets it through.
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
async fn an_update_sets_the_values_it_was_given() {
    let project = Project::seed().await;

    let updated = succeeded(&project.run(&[
        "variables",
        "update",
        "--name",
        "speed",
        "--set",
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
    // The filter surface is generated from the entity's own fields so the table's
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
async fn a_dump_asked_for_columns_is_drawn_as_a_table() {
    let project = Project::seed().await;

    let table = succeeded(&project.watched(&["variables", "select", "--address", "@motor"]));
    assert!(table.contains('\u{256d}'), "{table}");
    assert!(table.contains("speed"), "{table}");
    assert!(table.contains("torque"), "{table}");
    // A table is columns, not one object per line.
    assert!(!table.contains('{'), "{table}");

    // The same command without it is JSON lines, the default for every dump, so a
    // script reads the same bytes either way.
    let piped = succeeded(&project.run(&["variables", "select", "--address", "@motor"]));
    assert!(piped.starts_with('{'), "{piped}");
}

#[tokio::test]
async fn turning_color_off_leaves_the_columns_that_were_asked_for() {
    let project = Project::seed().await;

    // Color and shape are separate questions so answering one does not answer the other.
    // A reader who wants columns without color gets exactly that.
    let bare = succeeded(&project.run_with(
        &[],
        &["variables", "select", "--format", "table"],
        &[("NO_COLOR", "1")],
    ));
    assert!(bare.contains('\u{256d}'), "{bare}");
    assert!(!bare.contains('\u{1b}'), "{bare}");

    // The same command with color on draws the same box, colored.
    let colored = succeeded(&project.watched(&["variables", "select"]));
    assert!(colored.contains('\u{256d}'), "{colored}");
    assert!(colored.contains('\u{1b}'), "{colored}");
}

#[tokio::test]
async fn a_one_value_answer_is_colored_like_the_same_value_in_a_row() {
    let project = Project::seed().await;

    // A count and an existence check never pass through a row renderer so their color
    // is applied where they are written and is worth pinning here.
    let counted = succeeded(&project.run_with(
        &["--color"],
        &["variables", "count", "--address", "@motor"],
        &[],
    ));
    assert!(counted.contains('\u{1b}'), "{counted}");
    assert!(counted.contains('2'), "{counted}");

    // Piped, it stays the bare number a script captures.
    let piped = succeeded(&project.run(&["variables", "count", "--address", "@motor"]));
    assert_eq!(piped.trim(), "2");
    assert!(!piped.contains('\u{1b}'), "{piped}");
}

#[tokio::test]
async fn a_dump_written_to_a_file_carries_no_color_into_it() {
    let project = Project::seed().await;

    // An escape sequence written to a file is read back as the characters it is made of
    // so a dump that named a destination is uncolored however the terminal is set.
    for format in ["json", "table"] {
        let path = project.path().join(format!("rows-{format}.out"));
        let named = path.to_string_lossy().into_owned();
        succeeded(&project.run_with(
            &[],
            &[
                "variables",
                "select",
                "--format",
                format,
                "--output",
                &named,
            ],
            &[("FORCE_COLOR", "1")],
        ));

        let written = std::fs::read_to_string(&path).expect("the dump wrote its file");
        assert!(!written.contains('\u{1b}'), "{format}: {written}");
        // Naming a shape is what reaches it anywhere but a terminal so the file holds
        // the shape that was asked for rather than the one a destination would infer.
        match format {
            "table" => assert!(written.contains('\u{256d}'), "{written}"),
            _ => assert!(written.starts_with('{'), "{written}"),
        }
    }
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
    // which makes a write scriptable against what it actually changed.
    let touched = succeeded(&project.run(&[
        "variables",
        "update",
        "--address",
        "@motor",
        "--set",
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

    // The rows a delete collected are the ones that went so they can be kept.
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
async fn a_set_value_the_writer_will_not_take_says_why() {
    let project = Project::seed().await;

    // A column that is not there names the ones that are.
    let unknown = project.run(&[
        "variables",
        "update",
        "--name",
        "speed",
        "--set",
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
        "--set",
        "{\"address\": \"@elsewhere\"}",
        "--no-confirm",
    ]);
    assert!(!identity.status.success());
    let message = String::from_utf8_lossy(&identity.stderr);
    assert!(message.contains("identifies a row"), "{message}");

    // Nothing was written by either because a refusal happens before the transaction.
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
    // A load either lands whole or not at all so the good first row is not there.
    assert_eq!(project.variables().await.len(), 4);
}

#[tokio::test]
async fn a_conflicting_load_does_what_its_mode_says() {
    let project = Project::seed().await;
    let collide = project.path().join("collide.jsonl");
    std::fs::write(
        &collide,
        "{\"address\": \"@motor\", \"name\": \"speed\", \"value\": 99}\n",
    )
    .expect("the file writes");
    let path = collide.to_str().expect("a text path");

    // The default refuses the collision and rolls the whole load back.
    let refused = project.run(&["variables", "load", path]);
    assert!(!refused.status.success());
    assert!(
        project
            .variables()
            .await
            .contains(&"@motor speed 5".to_string())
    );

    // Ignoring one keeps the row that was already there.
    let ignored = succeeded(&project.run(&["variables", "load", path, "--on-conflict", "ignore"]));
    assert_eq!(ignored.trim(), "1");
    assert!(
        project
            .variables()
            .await
            .contains(&"@motor speed 5".to_string())
    );

    // Updating takes the incoming value instead.
    let updated = succeeded(&project.run(&["variables", "load", path, "--on-conflict", "update"]));
    assert_eq!(updated.trim(), "1");
    assert!(
        project
            .variables()
            .await
            .contains(&"@motor speed 99".to_string())
    );
}

#[tokio::test]
async fn a_csv_dump_carries_its_header_even_with_no_rows() {
    let project = Project::seed().await;

    // The header names the columns, which makes an empty result readable as an empty
    // table rather than as nothing at all.
    let empty = succeeded(&project.run(&[
        "variables",
        "select",
        "--name",
        "nothing-matches-this",
        "--format",
        "csv",
    ]));
    assert_eq!(empty.trim(), "address,name,value");

    // Suppressing it leaves the data rows alone, for appending to something.
    let rows = succeeded(&project.run(&[
        "variables",
        "select",
        "--address",
        "@motor",
        "--format",
        "csv",
        "--no-header",
    ]));
    assert!(!rows.contains("address,name,value"), "{rows}");
    assert_eq!(rows.lines().count(), 2, "{rows}");
}

#[tokio::test]
async fn a_dump_to_a_file_carries_every_row() {
    let project = Project::seed().await;
    let out = project.path().join("rows.jsonl");

    let written = succeeded(&project.run(&[
        "variables",
        "select",
        "--output",
        out.to_str().expect("a text path"),
    ]));
    // The rows went to the file so nothing was printed.
    assert!(written.is_empty(), "{written}");

    let held = std::fs::read_to_string(&out).expect("the file reads");
    assert_eq!(held.lines().count(), 4, "{held}");
}

#[tokio::test]
async fn the_groups_and_grants_tables_serve_the_whole_verb_set() {
    let project = Project::access().await;

    let created = succeeded(&project.run(&["groups", "create", "--name", "viewers"]));
    // The ID and the empty description are defaults the create model supplies.
    assert!(created.contains("\"name\":\"viewers\""), "{created}");
    assert!(created.contains("\"description\":\"\""), "{created}");

    let all = succeeded(&project.run(&["groups", "select"]));
    assert_eq!(all.lines().count(), 2, "{all}");

    let updated = succeeded(&project.run(&[
        "groups",
        "update",
        "--name",
        "viewers",
        "--set",
        "{\"description\": \"read only\"}",
        "--no-confirm",
    ]));
    assert_eq!(updated.trim(), "1", "{updated}");

    let read = succeeded(&project.run(&["groups", "select", "--name", "viewers"]));
    assert!(read.contains("\"description\":\"read only\""), "{read}");

    let deleted =
        succeeded(&project.run(&["groups", "delete", "--name", "viewers", "--no-confirm"]));
    assert_eq!(deleted.trim(), "1", "{deleted}");

    let left = succeeded(&project.run(&["groups", "count"]));
    assert_eq!(left.trim(), "1", "{left}");
}

#[tokio::test]
async fn a_grant_filters_and_collects_on_its_enum_columns() {
    let project = Project::access().await;
    let group = "019fbae5954c7321b29edfa121e5cdea";

    succeeded(&project.run(&[
        "group-permissions",
        "create",
        "--group-id",
        group,
        "--target-type",
        "tag",
        "--target",
        "outdoor",
        "--level",
        "view",
    ]));

    let matched = succeeded(&project.run(&["group-permissions", "count", "--level", "view"]));
    assert_eq!(matched.trim(), "1", "{matched}");

    let missed = succeeded(&project.run(&["group-permissions", "count", "--level", "manage"]));
    assert_eq!(missed.trim(), "0", "{missed}");

    // The rows a write touched come back from the write itself.
    let raised = succeeded(&project.run(&[
        "group-permissions",
        "update",
        "--target-type",
        "tag",
        "--set",
        "{\"level\": \"manage\"}",
        "--no-confirm",
        "--collect",
    ]));
    assert!(raised.contains("\"level\":\"manage\""), "{raised}");
}

#[tokio::test]
async fn a_grant_refuses_a_level_the_schema_cannot_store() {
    let project = Project::access().await;

    // `deny` names the absence of a grant rather than a level a row can hold. It has to
    // be turned away while the filter or the row is still being read because a value
    // that reaches the database comes back as a constraint violation naming the
    // constraint, which tells the reader nothing about what they typed.
    let filtered = project.run(&["group-permissions", "count", "--level", "deny"]);
    assert!(!filtered.status.success());
    let complaint = String::from_utf8_lossy(&filtered.stderr);
    assert!(complaint.contains("invalid level"), "{complaint}");

    let created = project.run(&[
        "group-permissions",
        "create",
        "--group-id",
        "019fbae5954c7321b29edfa121e5cdea",
        "--target-type",
        "tag",
        "--target",
        "indoor",
        "--level",
        "deny",
    ]);
    assert!(!created.status.success());
    let refusal = String::from_utf8_lossy(&created.stderr);
    assert!(
        !refusal.contains("CHECK constraint"),
        "the database answered instead of the surface: {refusal}"
    );
}

#[tokio::test]
async fn a_user_grant_reads_and_writes_like_a_group_grant() {
    let project = Project::access().await;
    let user = "019fbae594ef771394ae5a870bc1c722";

    succeeded(&project.run(&[
        "user-permissions",
        "create",
        "--user-id",
        user,
        "--target-type",
        "component",
        "--target",
        "@motor",
        "--level",
        "operate",
    ]));

    let read =
        succeeded(&project.run(&["user-permissions", "select", "--target-type", "component"]));
    assert!(read.contains("\"target\":\"@motor\""), "{read}");
    assert!(read.contains("\"level\":\"operate\""), "{read}");

    // A grant covering everything carries an empty target, which is a value like any
    // other rather than an absent one.
    succeeded(&project.run(&[
        "user-permissions",
        "create",
        "--user-id",
        user,
        "--target-type",
        "all",
        "--target",
        "",
        "--level",
        "view",
    ]));
    let every = succeeded(&project.run(&["user-permissions", "count"]));
    assert_eq!(every.trim(), "2", "{every}");
}

#[tokio::test]
async fn a_membership_refuses_setting_a_key_column() {
    let project = Project::access().await;

    // Both of a membership's columns identify it, which is why its update model carries
    // no fields at all.
    let output = project.run(&[
        "group-memberships",
        "update",
        "--set",
        "{\"group_id\": \"019fbae5954c7321b29edfa121e5cdea\"}",
        "--no-confirm",
    ]);
    assert!(!output.status.success());
    let complaint = String::from_utf8_lossy(&output.stderr);
    assert!(complaint.contains("group_id"), "{complaint}");
}

/// A project holding an enablement seed, for the offline engine commands.
///
/// The configuration declares a small component tree, and the variables table holds one
/// component enabled and one explicitly disabled, with the nested one never toggled.
async fn enablement_project() -> Project {
    let project = Project::seed().await;
    std::fs::write(
        project.config(),
        format!(
            "components:\n  - name: motor\n    components:\n      - name: driver\n  \
             - name: sensor\ndatabase:\n  type: sqlite\n  path: {}\n",
            project.path().join("records.sqlite").display()
        ),
    )
    .expect("the configuration writes");

    let url = format!(
        "sqlite://{}",
        project.path().join("records.sqlite").display()
    );
    let pool = sqlx::SqlitePool::connect(&url)
        .await
        .expect("the database opens");
    for (address, value) in [("@motor", "true"), ("@sensor", "false")] {
        sqlx::query("INSERT INTO variables VALUES (?, '__enabled__', ?)")
            .bind(address)
            .bind(value)
            .execute(&pool)
            .await
            .expect("the row inserts");
    }

    pool.close().await;
    project
}

#[tokio::test]
async fn offline_toggles_flip_only_rows_holding_the_other_state() {
    let project = enablement_project().await;

    // Only the enabled component reports because the disabled one already holds the
    // asked-for state and the never-toggled child has no row to flip.
    let disabled = succeeded(&project.run(&["disable", "@motor", "@sensor", "@motor.driver"]));
    assert_eq!(disabled.trim(), "{\"disabled\":[\"@motor\"]}");
    let held = project.variables().await;
    assert!(
        held.contains(&"@motor __enabled__ false".to_string()),
        "{held:?}"
    );

    let enabled = succeeded(&project.run(&["enable", "@sensor"]));
    assert_eq!(enabled.trim(), "{\"enabled\":[\"@sensor\"]}");
    let held = project.variables().await;
    assert!(
        held.contains(&"@sensor __enabled__ true".to_string()),
        "{held:?}"
    );

    // A component that was never toggled has no row so enabling it reports nothing and
    // writes nothing, matching the runtime's offline path.
    let untouched = succeeded(&project.run(&["enable", "@motor.driver"]));
    assert_eq!(untouched.trim(), "{\"enabled\":[]}");
}

#[tokio::test]
async fn offline_status_lists_the_configured_components_with_stored_enablement() {
    let project = enablement_project().await;

    let output = project.run(&["status"]);
    assert!(output.status.success());
    let report = String::from_utf8_lossy(&output.stderr);

    // The engine table reads stopped, and the components come from the configuration's
    // own tree, parents before children, with enablement from the database.
    assert!(report.contains("Engine"), "{report}");
    assert!(report.contains("(Stopped)"), "{report}");
    let motor = report.find("@motor").expect("the parent is listed");
    let driver = report.find("@motor.driver").expect("the child is listed");
    let sensor = report.find("@sensor").expect("the sensor is listed");
    assert!(motor < driver && driver < sensor, "{report}");
}
