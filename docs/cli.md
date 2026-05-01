# CLI Reference

The `ceres` command-line interface manages Ceres projects. All commands operate on the project in the current directory (or the path specified with `--config`).

## Global Options

| Option             | Description                                          |
| ------------------ | ---------------------------------------------------- |
| `--config PATH`    | Use a specific configuration file instead of auto-detecting. |
| `--color/--no-color` | Force or disable colored output.                   |
| `--version`, `-v`  | Show the Ceres version and exit.                     |

Configuration auto-detection searches the current directory for `ceres.yaml`, `ceres.yml`, or `ceres.json`.

## Running

### `ceres run [ADDRESSES] [--watch]`

Start the engine in the foreground.

- `ADDRESSES` (optional): Component addresses to start on launch. Use `all` to start everything.
- `--watch`: Restart automatically when Python files or configuration change.

```sh
ceres run all              # Start all components.
ceres run sensor pressure  # Start specific components.
ceres run all --watch      # Start with hot-reload.
```

Without addresses, the engine starts but no components are started unless they are enabled.

### `ceres check`

Validate the project configuration without starting the engine. Exits with code 0 if valid, 1 if there are errors.

```sh
ceres check
```

### `ceres reload`

Apply configuration changes to a running engine. The engine re-reads `ceres.yaml` from disk and reconciles the running component tree with the new configuration, creating, updating, or removing components as needed.

```sh
ceres reload
```

## Component Control

These commands require a running engine. They communicate with it over a Unix socket.

### `ceres start ADDRESS [ADDRESS ...]`

Start components. Starting a component implicitly starts its ancestors.

### `ceres stop ADDRESS [ADDRESS ...]`

Stop components. Stopping a component also stops its descendants.

### `ceres enable ADDRESS [ADDRESS ...]`

Enable components so they start automatically when the engine starts. This persists across restarts. If the engine is not running, the enable state is written directly to the database.

### `ceres disable ADDRESS [ADDRESS ...]`

Disable components. If the engine is not running, the disable state is written directly to the database.

### `ceres up ADDRESS [ADDRESS ...]`

Start and enable components in one command.

### `ceres down ADDRESS [ADDRESS ...]`

Stop and disable components in one command.

### `ceres status [ADDRESS ...]`

Show the state of the engine and its components. If no addresses are given, shows all components.

```
$ ceres status

 Engine
╭──────────────────────────────┬─────────┬──────╮
│ Configuration                │ Running │ Port │
├──────────────────────────────┼─────────┼──────┤
│ /path/to/ceres.yaml          │ Yes     │ 8080 │
╰──────────────────────────────┴─────────┴──────╯

 Components
╭───────────┬─────────┬─────────╮
│ Address   │ Running │ Enabled │
├───────────┼─────────┼─────────┤
│ @         │ Yes     │ No      │
│ @sensor   │ Yes     │ Yes     │
│ @pressure │ No      │ No      │
╰───────────┴─────────┴─────────╯
```

### Address Selectors

Most component commands accept address selectors.

- `all`: All components in the tree.
- `sensor`: The component at `@sensor` (the `@` prefix is optional).
- `@sensors.temperature`: A nested component by full address.

## Service Management

Manage Ceres as a background service that persists after logout and survives reboots.

### `ceres service start`

Generate a service definition, install it, and start the service. On Linux, this creates a SystemD user service. On macOS, it creates a LaunchD agent.

### `ceres service stop`

Stop the service and remove the service definition file.

### `ceres service status`

Show whether the service is running, the service name, user, and file location.

### `ceres service generate [PATH]`

Write the service definition file to `PATH` or stdout. Useful for reviewing or customizing the generated file.

## Database Management

### `ceres database init`

Create database tables and indexes. Shows the pending DDL statements and prompts for confirmation before executing.

### `ceres database ddl`

Print the DDL statements that `init` would execute, without running them.

### `ceres database shell`

Open an interactive database shell (`psql` for PostgreSQL, `sqlite3` for SQLite).

### `ceres database clear`

Truncate all tables. Prompts for confirmation. Schema is preserved.

## Data Queries

Ceres provides standard CRUD commands for each data entity. The general pattern is:

```sh
ceres <entity> <operation> [FILTERS] [OPTIONS]
```

### Entities

`logs`, `alerts`, `messages`, `particles`, `users`, `settings`, `variables`, `workspaces`, `workspace-memberships`

### Operations

| Operation | Description                                          |
| --------- | ---------------------------------------------------- |
| `select`  | Retrieve matching entities.                          |
| `count`   | Count matching entities.                             |
| `any`     | Exit 0 if any match, 1 otherwise.                   |
| `create`  | Create a new entity.                                 |
| `update`  | Update matching entities.                            |
| `delete`  | Delete matching entities.                            |
| `load`    | Bulk-load from a JSON or CSV file.                   |
| `follow`  | Stream new entities in real-time (logs, alerts, messages, particles only). |

### Common Options

| Option                   | Description                                   |
| ------------------------ | --------------------------------------------- |
| `--output FILE`          | Write results to a file.                      |
| `--data-format json/csv` | Output format (inferred from file extension). |
| `--field NAME[:ALIAS]`   | Select and optionally rename fields.          |
| `--confirm`              | Prompt before update/delete (default: true).  |

### Examples

```sh
ceres logs select --field address --field content         # Show log addresses and content.
ceres alerts count                                        # Count all alerts.
ceres messages select --output data.csv                   # Export messages as CSV.
ceres logs follow                                         # Stream new log entries in real-time.
ceres users create                                        # Create a user (interactive prompts).
ceres settings load settings.json --on-conflict update    # Bulk-load settings, updating conflicts.
```

## Web Console

### `ceres console open`

Open the web console in the default browser.

### `ceres console url`

Print the console URL to stdout.

## Other Commands

### `ceres generate openapi [--output FILE] [--format yaml|json]`

Generate the OpenAPI schema for the Ceres REST API.
