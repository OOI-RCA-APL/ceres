# Deployment

This guide covers deploying Ceres as a production service on Linux or macOS.

## Overview

A typical production Ceres deployment runs on a physical Linux server with:

- A `ceres.yaml` defining component drivers that connect to instruments over TCP.
- A PostgreSQL (or SQLite) database for persistence.
- A SystemD user service keeping the engine running across reboots.
- An HTTP server providing the web console and REST API.

## Prerequisites

On the deployment server, you need:

- Python 3.14+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- PostgreSQL (if using PostgreSQL instead of SQLite)

## Project Setup

Create a project directory, initialize it, and install Ceres.

```sh
mkdir /opt/my-project && cd /opt/my-project
uv init
uv add ceres --index https://ooi-rca-apl.github.io/ceres/simple/
```

Create your `ceres.yaml`. A production configuration typically looks like this:

```yaml
service:
  name: my-project

server:
  port: 8080
  authentication:
    secret: <generate-a-random-secret>
    duration: 30m

database:
  type: sqlite
  path: ./local/database.sqlite

logging:
  output: info
  store: debug
  events: true

components:
  - name: sensor-a
    class: my_project.SensorDriver
    arguments:
      host: 10.180.80.170
      port: 2101
      output: ./local/data/sensor-a/
  - name: sensor-b
    class: my_project.SensorDriver
    arguments:
      host: 10.180.80.171
      port: 2101
      output: ./local/data/sensor-b/
```

## Validating Configuration

Before starting the service, validate your configuration.

```sh
ceres check
```

## Database Migrations

The `ceres/database/migrations/` directory is the source of truth for the database schema. Every schema change ships as a migration file named `<id>-<name>.sql`, or `<id>-<name>.sqlite.sql` / `<id>-<name>.postgres.sql` when the SQL differs by backend, rather than as a standalone schema definition.

If you are using PostgreSQL, apply pending migrations to create or update the schema.

```sh
ceres database migrate
```

This shows the pending migrations and prompts for confirmation before applying them. SQLite databases are created and migrated automatically.

Show every known migration alongside its applied or pending status.

```sh
ceres database migrations
```

On startup, the engine refuses to run if the schema does not match what the running version of Ceres expects: migrations are pending, or the database has migration IDs the running version does not recognize (for example, after a downgrade). Run `ceres database migrate` to apply pending migrations. An unknown migration ID means the database was already migrated by a newer version of Ceres.

## Starting the Service

### Using `ceres service`

The simplest approach is to use the built-in service management.

```sh
ceres service start
```

This generates a service definition, installs it, and starts the service.

**Linux:** Creates a SystemD user service at `~/.config/systemd/user/ceres-<name>.service`. Runs `loginctl enable-linger` automatically so the service persists after logout.

**macOS:** Creates a LaunchD agent at `~/Library/LaunchAgents/com.ceres.<name>.plist`.

Check the service status.

```sh
ceres service status
```

Stop and remove the service.

```sh
ceres service stop
```

### Reviewing the Service File

To inspect or customize the generated service file before installing it:

```sh
ceres service generate               # Print to stdout.
ceres service generate ./my.service  # Write to file.
```

## Managing Components

Once the service is running, manage components from any terminal.

```sh
ceres status                 # Show engine and component states.
ceres up all                 # Enable and start all components.
ceres down sensor-a          # Disable and stop a specific component.
ceres enable sensor-b        # Auto-start on next engine restart.
```

## Applying Configuration Changes

After editing `ceres.yaml`, apply changes without restarting the service.

```sh
ceres reload
```

The engine reconciles the running component tree with the new configuration, creating, updating, or removing components as needed. Running components that were not changed continue without interruption.

## Monitoring

### Web Console

If `server.port` is configured, the web console is available at `http://<host>:<port>`. It provides a dashboard for monitoring component state, viewing logs, messages, alerts, and controlling components.

```sh
ceres console open    # Open in browser.
ceres console url     # Print the URL.
```

### CLI Queries

Stream logs, alerts, or messages in real-time from the command line.

```sh
ceres logs follow                           # Stream all log entries.
ceres alerts follow                         # Stream alerts.
ceres messages select --field data --output messages.csv  # Export messages.
```

### REST API

The HTTP API provides programmatic access to the same data. Generate the OpenAPI schema for reference.

```sh
ceres generate openapi --output openapi.yaml
```

The interactive API docs are available at `http://<host>:<port>/api/docs` when the server is running.

## Upgrading Ceres

To upgrade to a new version:

```sh
cd /opt/my-project
uv add ceres==<new-version> --index https://ooi-rca-apl.github.io/ceres/simple/
ceres service stop
ceres service start
```

If there are database schema changes, run `ceres database migrate` after upgrading and before starting the service.

## Logging

### Stdout/Stderr Redirection

Configure log file paths in the `service` section.

```yaml
service:
  name: my-project
  stdout: ./local/stdout.log
  stderr: ./local/stderr.log
```

### Log Levels

The `logging` section controls what is printed and what is stored.

```yaml
logging:
  output: info       # Minimum level for stdout.
  store: debug       # Minimum level for database storage.
  events: true       # Log component lifecycle events.
```

Per-component overrides are available. See [Configuration: Logging](configuration.md#logging).

## Database Maintenance

### Pruners

Configure automatic record cleanup in `ceres.yaml` to prevent unbounded database growth.

```yaml
components:
  - name: sensor
    class: my_project.SensorDriver
    pruners:
      - name: clean-messages
        prunes: message
        schedule: "0 0 * * *"
        filter:
          max-age: 30d
      - name: clean-logs
        prunes: log-entry
        schedule: "0 0 * * *"
        filter:
          max-age: 7d
```

### Manual Cleanup

Clear all data (preserving schema) if needed.

```sh
ceres database clear
```

### Database Shell

Open an interactive shell for ad-hoc queries.

```sh
ceres database shell
```
