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
uv add ceres-engine
```

Create your `ceres.yaml`. A production configuration typically looks like this:

```yaml
service:
  name: my-project

server:
  http:
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
      host: 192.0.2.10
      port: 2101
      output: ./local/data/sensor-a/
  - name: sensor-b
    class: my_project.SensorDriver
    arguments:
      host: 192.0.2.11
      port: 2101
      output: ./local/data/sensor-b/
```

Paths are relative to the configuration file. A writable database creates the
directories leading to its file, so `./local/database.sqlite` works on a fresh project.
Other paths, like a driver's output directory, are the driver's own to create.

### Environment Files

Every `ceres` command reads a `.env` file from the project directory into its
environment before doing anything else, and the engine and its components inherit the
result. Variables already set in the real environment win over the file. The background
service runs from the project directory, so the file applies there the same way.

Use it for values your drivers read from the environment, and keep it out of version
control when it carries credentials.

### The `.ceres` Directory

Ceres keeps state that belongs to one machine in a `.ceres` directory next to
`ceres.yaml`: the address the running engine's CLI server listens on, and the HTTPS
certificate and key that `ceres generate certificate` writes. The directory carries its
own `.gitignore`, so nothing in it reaches version control. Leave it out of copies of the
project to other machines too.

## Validating Configuration

Before starting the service, validate your configuration.

```sh
ceres check
```

## Database Migrations

The `rust/ceres-database/migrations/` directory is the source of truth for the database schema. Every schema change ships as a migration file named `<id>-<name>.sql`, or `<id>-<name>.sqlite.sql` / `<id>-<name>.postgres.sql` when the SQL differs by backend, rather than as a standalone schema definition.

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

With a `server.https` listener the web console is available at `https://<host>:<port>`, and with only a `server.http` listener at `http://<host>:<port>`. It provides a dashboard for monitoring component state, viewing logs, messages, alerts, and controlling components.

```sh
ceres console open    # Open in browser.
ceres console url     # Print the URL.
```

### HTTPS

With a `server.https` listener the console is served over TLS, and browsers negotiate HTTP/2, which multiplexes every console request over one connection. Over plain HTTP browsers cap a page at about six connections per host, and each live video widget holds one, so a dashboard with several videos stalls. HTTPS lifts that limit.

An empty `server.https` section listens on port 443 with the certificate and key in the project's `.ceres/tls` directory. Generate them once from the project directory:

```sh
ceres generate certificate
```

```text
Wrote the certificate to .ceres/tls/server.crt.
Wrote the key to .ceres/tls/server.key.
Names: localhost, 127.0.0.1, ::1, sensor-host, 192.0.2.5
Expires: 2029-01-07 (825 days)
SHA-256 fingerprint: F7:65:82:76:E8:92:6A:D7:2B:21:F2:63:DD:72:1A:52:AC:E7:B3:12:A7:B4:FC:49:81:F9:2D:6B:13:2B:08:D0
```

The certificate is self-signed with an ECDSA P-256 key, and names localhost, the loopback addresses, the machine's hostname, and every address of its network interfaces other than loopback and link-local ones. Add names clients reach the server by, like a DNS alias or a NAT address, with `--ip` and `--dns`, both repeatable. `--days` sets how long it stays valid. The key file is readable by its owner alone. An existing certificate or key is only replaced with `--force`, so regenerate before the old one expires:

```sh
ceres generate certificate --dns sensors.example.org --force
```

Browsers warn about a self-signed certificate until it is accepted. Compare the fingerprint the browser shows with the one printed above before accepting it.

Set `server.http.redirect` to keep the old `http://` bookmarks working after a move to HTTPS. The `server.http` listener then answers every request with a temporary redirect to the same path and query on the HTTPS listener. Its port defaults to 80, and is typically the port the server served plain HTTP on before.

```yaml
server:
  https: {}
  http:
    redirect: true
```

To serve a certificate from elsewhere, like one a certificate authority issued, name its files with `cert` and `key`, plus `key-password` for an encrypted key. Relative paths resolve against the project directory. `ceres generate certificate` writes to the configured paths too.

```yaml
server:
  https:
    cert: /etc/ceres/server.crt
    key: /etc/ceres/server.key
```

`ceres check` and engine startup fail when the certificate or key cannot be loaded, and name `ceres generate certificate` when the default files are missing. Both also warn once fewer than 30 days remain before the certificate expires, `ceres check` on its output and startup in the engine log.

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
uv add ceres-engine==<new-version>
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
