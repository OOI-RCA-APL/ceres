//! The declared argument surface of the table commands.
//!
//! The eight entity and record groups take the same verbs over the same controls,
//! differing only in the fields their table holds, so the whole tree is generated from
//! the entity definitions rather than written out. A filter argument comes from the
//! table's filter keys and a create's arguments from its columns, each key already
//! carrying whether it is a bare flag or takes a value, which is what keeps the parser
//! and the compiler from disagreeing about what a key is.
//!
//! Declaring the surface here is what lets the binary answer `--help` and report an
//! argument error itself. A key outside the native subset still parses, because
//! belonging to the surface and being servable in one native pass are different
//! questions, and the compiler is the one that answers the second.

use ceres_database::{
    Arity, EntityFilter, EntityTable, FilterKey, OperationKind, RecordFilter, RecordTable, Role,
    Window,
};
use clap::{Arg, ArgAction, Command};

/// The verbs a table command takes.
///
/// `follow` reads a running engine rather than the database, so only the record tables
/// components fill declare it.
pub(crate) const VERBS: [&str; 8] = [
    "select", "count", "any", "create", "update", "delete", "load", "follow",
];

/// Which table a group of commands manages.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) enum Table {
    Record(RecordTable),
    Entity(EntityTable),
}

impl Table {
    /// Every group the CLI declares, in the order they appear in help.
    pub(crate) fn all() -> [Self; 13] {
        [
            Self::Record(RecordTable::Alerts),
            Self::Record(RecordTable::Logs),
            Self::Record(RecordTable::Messages),
            Self::Record(RecordTable::Particles),
            Self::Entity(EntityTable::Settings),
            Self::Entity(EntityTable::Users),
            Self::Entity(EntityTable::Variables),
            Self::Entity(EntityTable::Workspaces),
            Self::Entity(EntityTable::WorkspaceEdits),
            Self::Entity(EntityTable::Groups),
            Self::Entity(EntityTable::GroupMemberships),
            Self::Entity(EntityTable::UserPermissions),
            Self::Entity(EntityTable::GroupPermissions),
        ]
    }

    /// The command group's name, which is the table's own plural.
    ///
    /// A table whose name is two words hyphenates here, the way a flag's wire key does,
    /// so `user_permissions` is reached as `ceres user-permissions`.
    pub(crate) fn group(self) -> &'static str {
        match self {
            Self::Record(RecordTable::Alerts) => "alerts",
            Self::Record(RecordTable::Logs) => "logs",
            Self::Record(RecordTable::Messages) => "messages",
            Self::Record(RecordTable::Particles) => "particles",
            Self::Entity(EntityTable::Settings) => "settings",
            Self::Entity(EntityTable::Users) => "users",
            Self::Entity(EntityTable::Variables) => "variables",
            Self::Entity(EntityTable::Workspaces) => "workspaces",
            Self::Entity(EntityTable::WorkspaceEdits) => "workspace-edits",
            Self::Entity(EntityTable::Groups) => "groups",
            Self::Entity(EntityTable::GroupMemberships) => "group-memberships",
            Self::Entity(EntityTable::UserPermissions) => "user-permissions",
            Self::Entity(EntityTable::GroupPermissions) => "group-permissions",
        }
    }

    /// What one row is called, for the help text a verb carries.
    fn singular(self) -> &'static str {
        match self {
            Self::Record(RecordTable::Alerts) => "alert",
            Self::Record(RecordTable::Logs) => "log entry",
            Self::Record(RecordTable::Messages) => "message",
            Self::Record(RecordTable::Particles) => "particle",
            Self::Entity(EntityTable::Settings) => "setting",
            Self::Entity(EntityTable::Users) => "user",
            Self::Entity(EntityTable::Variables) => "variable",
            Self::Entity(EntityTable::Workspaces) => "workspace",
            Self::Entity(EntityTable::WorkspaceEdits) => "workspace edit",
            Self::Entity(EntityTable::Groups) => "group",
            Self::Entity(EntityTable::GroupMemberships) => "group membership",
            Self::Entity(EntityTable::UserPermissions) => "user permission",
            Self::Entity(EntityTable::GroupPermissions) => "group permission",
        }
    }

    /// Whether the table streams new rows from a running engine, which the record
    /// tables components fill do and the operator-edited tables do not.
    fn follows(self) -> bool {
        matches!(self, Self::Record(_))
    }

    /// A filter worth showing in this table's examples.
    ///
    /// Each names a field the table actually has, because an example a reader cannot
    /// run against their own data teaches them nothing.
    fn example_filter(self) -> &'static str {
        match self {
            Self::Record(RecordTable::Alerts) => "--address @sensor.temp --max-age 24h",
            Self::Record(RecordTable::Logs) => "--min-level warning --max-age 1h",
            Self::Record(RecordTable::Messages) => "--address @sensor.temp --max-age 2h",
            Self::Record(RecordTable::Particles) => "--address @sensor.temp --after 2026-01-01",
            Self::Entity(EntityTable::Settings) => "--name theme",
            Self::Entity(EntityTable::Users) => "--username ada",
            Self::Entity(EntityTable::Variables) => "--address @motor --name speed",
            Self::Entity(EntityTable::Workspaces) => "--name Overview",
            Self::Entity(EntityTable::WorkspaceEdits) => "--user-id UUID",
            Self::Entity(EntityTable::Groups) => "--name operators",
            Self::Entity(EntityTable::GroupMemberships) => "--group-id UUID",
            Self::Entity(EntityTable::UserPermissions) => "--user-id UUID --level manage",
            Self::Entity(EntityTable::GroupPermissions) => "--target-type tag --target outdoor",
        }
    }

    /// The fields a create example fills, enough of them to succeed.
    fn example_create(self) -> &'static str {
        match self {
            Self::Record(RecordTable::Alerts) => "--address @sensor.temp --content 'too hot'",
            Self::Record(RecordTable::Logs) => "--address @sensor --level warning --content 'slow'",
            Self::Record(RecordTable::Messages) => {
                "--address @sensor.temp --direction receive --data hello"
            }
            Self::Record(RecordTable::Particles) => "--address @sensor.temp --value 21.5",
            Self::Entity(EntityTable::Settings) => "--user-id UUID --name theme --value '\"dark\"'",
            Self::Entity(EntityTable::Users) => {
                "--username ada --email ada@example.com --password secret"
            }
            Self::Entity(EntityTable::Variables) => "--address @motor --name speed --value 5",
            Self::Entity(EntityTable::Workspaces) => "--name Overview --scope @motor",
            Self::Entity(EntityTable::WorkspaceEdits) => {
                "--user-id UUID --workspace-id UUID --data '{}'"
            }
            Self::Entity(EntityTable::Groups) => "--name operators",
            Self::Entity(EntityTable::GroupMemberships) => "--user-id UUID --group-id UUID",
            Self::Entity(EntityTable::UserPermissions) => {
                "--user-id UUID --target-type component --target @motor --level operate"
            }
            Self::Entity(EntityTable::GroupPermissions) => {
                "--group-id UUID --target-type all --target '' --level view"
            }
        }
    }

    /// An assignment worth showing, naming a column the table's update model allows.
    fn example_assign(self) -> &'static str {
        match self {
            Self::Record(RecordTable::Alerts) => "{\"content\": \"acknowledged\"}",
            Self::Record(RecordTable::Logs) => "{\"content\": \"redacted\"}",
            Self::Record(RecordTable::Messages) => "{\"data\": \"redacted\"}",
            Self::Record(RecordTable::Particles) => "{\"value\": 0}",
            Self::Entity(EntityTable::Settings) => "{\"value\": \"solar\"}",
            Self::Entity(EntityTable::Users) => "{\"admin\": true}",
            Self::Entity(EntityTable::Variables) => "{\"value\": 9}",
            Self::Entity(EntityTable::Workspaces) => "{\"name\": \"Home\"}",
            Self::Entity(EntityTable::WorkspaceEdits) => "{\"data\": {}}",
            Self::Entity(EntityTable::Groups) => "{\"description\": \"on call\"}",
            // A membership is created or deleted rather than edited, so the example shows
            // the one shape an update can take, which is no assignment at all.
            Self::Entity(EntityTable::GroupMemberships) => "{}",
            Self::Entity(EntityTable::UserPermissions) => "{\"level\": \"manage\"}",
            Self::Entity(EntityTable::GroupPermissions) => "{\"level\": \"view\"}",
        }
    }

    /// The table's filter keys, each with the argument form its family gives it.
    pub(crate) fn keys(self) -> Vec<FilterKey> {
        match self {
            Self::Record(table) => RecordFilter::keys(table),
            Self::Entity(table) => EntityFilter::keys(table),
        }
    }

    /// The columns a create may name, which is a different surface from the filter's.
    pub(crate) fn columns(self) -> Vec<FilterKey> {
        match self {
            Self::Record(table) => RecordFilter::columns(table),
            Self::Entity(table) => EntityFilter::columns(table),
        }
    }
}

/// The long form of a wire key, `max_age` arriving as `--max-age`.
pub(crate) fn long(key: &str) -> String {
    key.replace('_', "-")
}

/// Read the keys a parsed invocation carried, as the wire pairs the compiler takes.
///
/// Argument order is preserved, because a filter reads as a sequence and a reader who
/// wrote their flags in an order expects to see it kept. A boolean arrives as the value
/// its spelling names rather than as a value of its own.
pub(crate) fn pairs(keys: &[FilterKey], matches: &clap::ArgMatches) -> Vec<(String, String)> {
    let mut placed: Vec<(usize, String, String)> = Vec::new();
    for key in keys {
        match key.arity {
            Arity::Value => {
                let Some(values) = matches.get_many::<String>(key.key) else {
                    continue;
                };
                let indices = matches
                    .indices_of(key.key)
                    .expect("a present argument has indices");
                for (index, value) in indices.zip(values) {
                    placed.push((index, key.key.to_string(), value.clone()));
                }
            }
            Arity::Flag => {
                let negated = format!("no-{}", long(key.key));
                // Only one of the pair survives, each overriding the other, so whichever
                // is set is the one the reader wrote last.
                for (id, held) in [(key.key.to_string(), "true"), (negated, "false")] {
                    if !matches.get_flag(&id) {
                        continue;
                    }

                    let index = matches.index_of(&id).unwrap_or_default();
                    placed.push((index, key.key.to_string(), held.to_string()));
                }
            }
        }
    }

    placed.sort_by_key(|(index, _, _)| *index);
    placed
        .into_iter()
        .map(|(_, key, value)| (key, value))
        .collect()
}

/// Declare one key as the arguments that carry it.
///
/// A value key is repeatable, because a field folding several values into a set is how
/// an `IN` comparison is written. A boolean is a `--key` and `--no-key` pair carrying no
/// value of its own, each overriding the other so the last one wins.
fn argument(key: FilterKey, help: String, heading: &'static str) -> Vec<Arg> {
    let name = long(key.key);
    match key.arity {
        Arity::Value => vec![
            Arg::new(key.key.to_string())
                .long(name)
                .action(ArgAction::Append)
                .value_name("VALUE")
                .help_heading(heading)
                .help(help),
        ],
        Arity::Flag => {
            let negated = format!("no-{name}");
            // The negated half is real surface but listing it doubles the boolean
            // entries for nothing, so it hides and the visible half names it. A reader
            // who cannot see `--no-internal` will not guess it exists.
            let help = format!("{help} Pass `--{negated}` for the opposite.");
            vec![
                Arg::new(key.key.to_string())
                    .long(name)
                    .action(ArgAction::SetTrue)
                    .overrides_with(negated.clone())
                    .help_heading(heading)
                    .help(help),
                Arg::new(negated.clone())
                    .long(negated)
                    .action(ArgAction::SetTrue)
                    .overrides_with(key.key.to_string())
                    .hide(true),
            ]
        }
    }
}

/// What one filter key does, said in a line.
///
/// Written from the key's role rather than its spelling, so a key added to an entity
/// arrives with a description that is right by construction. `plural` names the rows
/// being narrowed, which is what makes the sentence read as advice rather than as a
/// restatement of the flag's own name.
fn filter_help(key: FilterKey, plural: &str) -> String {
    let field = key.field.map(long).unwrap_or_default();
    match key.role {
        Role::Equality => match key.arity {
            Arity::Flag => format!("Only {plural} whose {field} is set."),
            Arity::Value => {
                format!("Only {plural} with this {field}. Repeat to match any of several.")
            }
        },
        Role::Operation(kind) => {
            let matching = match kind {
                OperationKind::Contains => "contains",
                OperationKind::Prefix => "starts with",
                OperationKind::Suffix => "ends with",
            };
            format!("Only {plural} whose {field} {matching} this.")
        }
        Role::Root => "Resolve relative address selectors against this address.".to_string(),
        Role::Window(Window::Absolute) => {
            let side = if key.key.starts_with("after") {
                "at or after"
            } else {
                "before"
            };
            format!("Only {plural} recorded {side} this time.")
        }
        Role::Window(Window::Age) => {
            let side = if key.key.starts_with("max") {
                "newer"
            } else {
                "older"
            };
            format!("Only {plural} {side} than this, as a duration like `2h` or `P1D`.")
        }
        Role::Window(Window::Span) => {
            format!("Only {plural} inside this span, as two times or a time and a duration.")
        }
        Role::Window(Window::Clock) => {
            let unit = if key.key.ends_with("hour") {
                "hour"
            } else {
                "minute"
            };
            let side = if key.key.starts_with("after") {
                "at or after"
            } else {
                "before"
            };
            format!("Only {plural} recorded {side} this {unit} of the day, whatever the date.")
        }
        Role::Window(Window::Subsample) => {
            "Thin the result, keeping one row per interval.".to_string()
        }
        Role::Bound => {
            let side = if key.key.starts_with("min") {
                "at or above"
            } else {
                "at or below"
            };
            format!("Only {plural} whose {field} is {side} this.")
        }
        Role::Computed => format!(
            "Only {plural} that are {}.",
            long(key.key).replace('-', " ")
        ),
        Role::Query => match key.key {
            "order" => "Sort by this field, `field:desc` to reverse. Repeatable.".to_string(),
            "limit" => format!("Return at most this many {plural}."),
            _ => format!("Skip this many {plural} before returning any."),
        },
        Role::Group => {
            let joining = if key.key == "or" { "any" } else { "all" };
            format!("Only {plural} matching {joining} of these subfilters, as a JSON or YAML list.")
        }
    }
}

/// The heading a filter argument is listed under.
///
/// A table brings twenty or more of these, so listing them beside the handful of output
/// controls buries both. The headings are what make a long list readable.
const FILTERING: &str = "Filtering";
const OUTPUT: &str = "Output";
const WRITING: &str = "Writing";
const VALUES: &str = "Values";

/// The filter arguments a table's verbs take.
fn filter_arguments(table: Table) -> Vec<Arg> {
    let plural = table.group();
    table
        .keys()
        .into_iter()
        .flat_map(|key| argument(key, filter_help(key, plural), FILTERING))
        .collect()
}

/// The arguments a create takes, one per column it may fill.
fn create_arguments(table: Table) -> Vec<Arg> {
    let singular = table.singular();
    table
        .columns()
        .into_iter()
        .flat_map(|key| {
            let field = long(key.key);
            let help = match key.arity {
                Arity::Flag => format!("Mark the {singular} {field}."),
                Arity::Value => format!("The {singular}'s {field}."),
            };
            argument(key, help, VALUES)
        })
        .collect()
}

/// The destination a verb writes to, which every verb declares.
fn output() -> Arg {
    Arg::new("output")
        .long("output")
        .short('o')
        .value_name("PATH")
        .help_heading(OUTPUT)
        .help("Write to this file rather than standard output.")
}

/// The output controls a verb rendering rows takes.
///
/// A verb rendering one value takes only a destination, because a field selection, a
/// data format, and a header row mean nothing for a count or an existence check.
fn row_arguments() -> Vec<Arg> {
    vec![
        output(),
        Arg::new("data_format")
            .long("data-format")
            .short('f')
            .value_name("FORMAT")
            .value_parser(["json", "csv", "table"])
            .help_heading(OUTPUT)
            .help(
                "Render as JSON lines, CSV, or a table. Inferred from --output, or from \
                 whether anyone is reading, when unset.",
            ),
        Arg::new("field")
            .long("field")
            .action(ArgAction::Append)
            .value_name("FIELD[:ALIAS]")
            .help_heading(OUTPUT)
            .help("Output only this field, optionally renamed. Repeatable."),
        Arg::new("header")
            .long("header")
            .action(ArgAction::SetTrue)
            .overrides_with("no-header")
            .help_heading(OUTPUT)
            .help("Write a CSV header row, which is the default. `--no-header` omits it."),
        Arg::new("no-header")
            .long("no-header")
            .action(ArgAction::SetTrue)
            .overrides_with("header")
            .hide(true),
    ]
}

/// The positional field selection a verb choosing its own columns takes.
fn field_positional() -> Arg {
    Arg::new("fields")
        .action(ArgAction::Append)
        .value_name("FIELDS")
        .help("Output only these fields, each optionally renamed as `field:alias`.")
}

/// The confirmation and collection controls a filtered write takes.
fn write_arguments(verb: &str) -> Vec<Arg> {
    vec![
        Arg::new("confirm")
            .long("confirm")
            .action(ArgAction::SetTrue)
            .overrides_with("no-confirm")
            .help_heading(WRITING)
            .help("Ask before writing, which is the default when standard input is a terminal."),
        Arg::new("no-confirm")
            .long("no-confirm")
            .short('y')
            .action(ArgAction::SetTrue)
            .overrides_with("confirm")
            .help_heading(WRITING)
            .help("Write without asking."),
        Arg::new("collect")
            .long("collect")
            .action(ArgAction::SetTrue)
            .help_heading(WRITING)
            .help(format!(
                "Output the {verb} rows rather than how many. Ordering is not preserved."
            )),
    ]
}

/// Add every table command group to the declared command tree.
pub(crate) fn augment(command: Command) -> Command {
    Table::all()
        .into_iter()
        .fold(command, |command, table| command.subcommand(group(table)))
}

/// The table one group name manages, `None` for a command that is not a table group.
pub(crate) fn table(name: &str) -> Option<Table> {
    Table::all().into_iter().find(|table| table.group() == name)
}

/// Build the whole command group for one table.
pub(crate) fn group(table: Table) -> Command {
    let plural = table.group();
    let singular = table.singular();
    let mut command = Command::new(plural)
        .about(format!("Manage {plural}"))
        .subcommand_required(true)
        .arg_required_else_help(true);

    for verb in VERBS {
        if verb == "follow" && !table.follows() {
            continue;
        }

        command = command.subcommand(self::verb(table, verb, plural, singular));
    }

    command
}

/// Worked examples for one verb, shown under its help.
///
/// Each one uses the table's own fields, because an example naming a field the reader
/// does not have is worse than none. The generic shape of a verb is already in its
/// argument list, so these show the combinations worth knowing about instead.
fn examples(table: Table, verb: &str) -> Option<String> {
    let plural = table.group();
    let filter = table.example_filter();
    let lines: Vec<String> = match verb {
        "select" => vec![
            format!("ceres {plural} select"),
            format!("ceres {plural} select {filter}"),
            format!("ceres {plural} select --limit 20 --order id:desc"),
            format!("ceres {plural} select --output rows.csv"),
        ],
        "follow" => vec![
            format!("ceres {plural} follow"),
            format!("ceres {plural} follow {filter}"),
        ],
        "count" => vec![
            format!("ceres {plural} count"),
            format!("ceres {plural} count {filter}"),
        ],
        "any" => vec![
            format!("ceres {plural} any {filter}"),
            format!("ceres {plural} any {filter} && echo found"),
        ],
        "create" => vec![format!("ceres {plural} create {}", table.example_create())],
        "update" => vec![
            format!(
                "ceres {plural} update {filter} --assign '{}'",
                table.example_assign()
            ),
            format!(
                "ceres {plural} update {filter} --assign '{}' --no-confirm",
                table.example_assign()
            ),
        ],
        "delete" => vec![
            format!("ceres {plural} delete {filter}"),
            format!("ceres {plural} delete {filter} --no-confirm"),
        ],
        "load" => vec![
            format!("ceres {plural} load rows.jsonl"),
            format!("ceres {plural} load rows.csv --on-conflict update"),
        ],
        _ => return None,
    };

    let mut rendered = String::from("Examples:\n");
    for line in lines {
        rendered.push_str("  ");
        rendered.push_str(&line);
        rendered.push('\n');
    }

    Some(rendered)
}

/// Build one verb of a table's command group.
fn verb(table: Table, verb: &'static str, plural: &str, singular: &str) -> Command {
    let mut command = Command::new(verb);
    if let Some(examples) = examples(table, verb) {
        command = command.after_help(examples);
    }

    match verb {
        "select" => command
            .about(format!("Retrieve {plural}"))
            .arg(field_positional())
            .args(row_arguments())
            .args(filter_arguments(table)),
        "follow" => command
            .about(format!("Follow new {plural} as they arrive"))
            .arg(field_positional())
            .args(row_arguments())
            .args(filter_arguments(table)),
        "count" => command
            .about(format!("Count {plural}"))
            .arg(output())
            .args(filter_arguments(table)),
        "any" => command
            .about(format!(
                "Check whether any {plural} match, reporting through the exit status"
            ))
            .arg(output())
            .args(filter_arguments(table)),
        "create" => command
            .about(format!("Create a {singular}"))
            .args(row_arguments())
            .args(create_arguments(table)),
        "update" => command
            .about(format!("Update {plural}, reporting how many changed"))
            .arg(
                Arg::new("assign")
                    .long("assign")
                    .required(true)
                    .value_name("OBJECT")
                    .help("Values to assign, as a JSON or YAML object."),
            )
            .args(write_arguments("updated"))
            .args(row_arguments())
            .args(filter_arguments(table)),
        "delete" => command
            .about(format!("Delete {plural}, reporting how many were removed"))
            .args(write_arguments("deleted"))
            .args(row_arguments())
            .args(filter_arguments(table)),
        "load" => command
            .about(format!("Load {plural} from a file, reporting how many"))
            .arg(
                Arg::new("path")
                    .required(true)
                    .value_name("PATH")
                    .help(format!("The file to read {plural} from.")),
            )
            .arg(
                Arg::new("data_format")
                    .long("data-format")
                    .value_name("FORMAT")
                    .value_parser(["json", "csv"])
                    .help("The file's shape. Inferred from its extension when unset."),
            )
            .arg(
                Arg::new("on_conflict")
                    .long("on-conflict")
                    .value_name("MODE")
                    .value_parser(["error", "ignore", "update"])
                    .default_value("error")
                    .help("What to do about a row whose key already exists."),
            ),
        _ => unreachable!("every declared verb is built above"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_group_declares_its_verbs() {
        for table in Table::all() {
            let command = group(table);
            let declared: Vec<_> = command
                .get_subcommands()
                .map(|verb| verb.get_name())
                .collect();

            // Only the record tables components fill can be followed, and every other
            // verb belongs to every group.
            let expected: Vec<_> = VERBS
                .iter()
                .filter(|verb| **verb != "follow" || table.follows())
                .copied()
                .collect();
            assert_eq!(declared, expected, "{}", table.group());
        }
    }

    #[test]
    fn a_boolean_key_declares_both_of_its_spellings() {
        // A boolean filter is a `--key` and `--no-key` pair in the surface the Python
        // models generated, so a script passing either half keeps working. Dropping the
        // negated half is the easy mistake, and it is silent.
        let workspaces = Table::Entity(EntityTable::Workspaces);
        let select = group(workspaces);
        let select = select.find_subcommand("select").unwrap();
        let longs: Vec<_> = select
            .get_arguments()
            .filter_map(|arg| arg.get_long())
            .collect();

        for key in workspaces.keys() {
            if key.arity != Arity::Flag {
                continue;
            }

            let name = long(key.key);
            assert!(longs.contains(&name.as_str()), "--{name} is missing");
            let negated = format!("no-{name}");
            assert!(longs.contains(&negated.as_str()), "--{negated} is missing");
        }

        // The computed predicates are the ones with no column behind them, and they are
        // booleans like any other.
        for key in ["placed-on-engine", "owned", "show-when-logged-out"] {
            assert!(longs.contains(&key), "--{key} is missing");
            let negated = format!("no-{key}");
            assert!(longs.contains(&negated.as_str()), "--{negated} is missing");
        }
    }

    #[test]
    fn a_create_names_columns_rather_than_filter_keys() {
        // A user's password is a column no filter exposes, so a create surface built
        // from the filter keys would leave no way to set one.
        let users = Table::Entity(EntityTable::Users);
        let create = group(users);
        let create = create.find_subcommand("create").unwrap();
        let longs: Vec<_> = create
            .get_arguments()
            .filter_map(|arg| arg.get_long())
            .collect();

        assert!(longs.contains(&"password"));
        assert!(longs.contains(&"username"));
        assert!(longs.contains(&"email"));
        // A filter's operations name no column, so a create does not take them.
        assert!(!longs.contains(&"email-contains"));
    }

    #[test]
    fn the_surface_parses_what_the_python_commands_took() {
        let variables = group(Table::Entity(EntityTable::Variables));

        // A repeated value key folds into a set, which is how an `IN` is written.
        let matches = variables
            .clone()
            .try_get_matches_from(["variables", "select", "--name", "speed", "--name", "rate"])
            .unwrap();
        let select = matches.subcommand_matches("select").unwrap();
        let names: Vec<_> = select.get_many::<String>("name").unwrap().collect();
        assert_eq!(names, ["speed", "rate"]);

        // A boolean takes no value of its own and the last spelling wins.
        let matches = variables
            .clone()
            .try_get_matches_from(["variables", "select", "--internal", "--no-internal"])
            .unwrap();
        let select = matches.subcommand_matches("select").unwrap();
        assert!(!select.get_flag("internal"));
        assert!(select.get_flag("no-internal"));

        // An update without assignments is an argument error rather than a delegation.
        assert!(
            variables
                .clone()
                .try_get_matches_from(["variables", "update", "--name", "speed"])
                .is_err()
        );
    }
}
