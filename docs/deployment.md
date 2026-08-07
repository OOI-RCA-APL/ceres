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

Paths are relative to the configuration file, and Ceres creates none of the directories along them. Create `local/` before the first run, or the engine stops on a database it cannot open.

## Validating Configuration

Before starting the service, validate your configuration.

```sh
ceres check
```

## Database Migrations

The `ceres/database/migrations/` directory is the source of truth for the database schema. Every schema change ships as a migration file named `<id>-<name>.sql`, or `<id>-<name>.sqlite.sql` / `<id>-<name>.postgres.sql` when the SQL differs by backend, rather than as a standalone schema definition.

Whether the engine migrates on its own depends on whether the database is empty, not on which backend it is. An empty database has every migration applied at startup, on SQLite and PostgreSQL alike. A database with data in it is only checked, never migrated, so an upgrade that ships a migration is a deliberate step.

```sh
ceres database migrate
```

This lists the pending migrations and asks before applying them.

Show every known migration alongside its applied or pending status.

```sh
ceres database migrations
```

On startup a non-empty database has to already match what the running version of Ceres expects, and the engine refuses to start otherwise. Pending migrations mean you need `ceres database migrate`. A migration ID the running version does not recognize means the database was migrated by a newer version of Ceres than the one you are starting, which is what a downgrade looks like.

## Starting the Service

### Using `ceres service`

The simplest approach is to use the built-in service management.

```sh
ceres service start
```

This generates a service definition, installs it, and starts the service.

The service is named `ceres-<hash>`, where the hash is derived from the project directory, so several projects on one machine never collide. Set `service.name` in `ceres.yaml` to choose the name yourself.

**Linux:** a SystemD user service at `~/.config/systemd/user/ceres-<hash>.service`. `loginctl enable-linger` runs automatically, so the service survives logout.

**macOS:** a LaunchD agent at `~/Library/LaunchAgents/ceres-<hash>.plist`.

`ceres service status` prints the name and the exact path, which is quicker than working out the hash.

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

A running server serves its own OpenAPI document at `http://<host>:<port>/api/openapi.json`, and `/api` redirects there. Point any OpenAPI client at it, or read [the HTTP API reference](reference/http-api.md).

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

Per-component overrides are available. See [Configuration](reference/configuration.md#logging).

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
