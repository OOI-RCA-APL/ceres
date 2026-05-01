# Configuration

All project configuration lives in `ceres.yaml` (or `ceres.yml` / `ceres.json`) at the root of your project directory. This page documents every section and option.

## Top-Level Structure

```yaml
service:      # Background service settings.
server:       # HTTP API and web console.
database:     # Data persistence.
console:      # Web console customization.
logging:      # Log levels and storage.
components:   # Component tree definition.
```

All sections are optional. A minimal configuration only needs `components`.

## `service`

Configure the background service identity. Used by `ceres service start`.

```yaml
service:
  name: my-project         # Service name (used in systemd/launchd).
  user: ceres              # OS user the service runs as.
  stdout: ./local/out.log  # Redirect stdout to file.
  stderr: ./local/err.log  # Redirect stderr to file.
```

## `server`

Enable the HTTP API and web console by specifying a port.

```yaml
server:
  host: 0.0.0.0    # Bind address (default: 0.0.0.0).
  port: 8080        # HTTP port. Omit to disable the server entirely.
```

### Authentication

```yaml
server:
  port: 8080
  authentication:
    secret: my-secret-key  # JWT signing secret.
    duration: 30m          # Token lifetime.
```

### SSL/TLS

```yaml
server:
  port: 8443
  ssl:
    key: ./certs/server.key
    cert: ./certs/server.crt
```

### CORS

```yaml
server:
  port: 8080
  cors:
    enabled: true
    allow-origins: ["*"]
    allow-methods: ["*"]
    allow-headers: ["*"]
    allow-credentials: false
```

### Compression

Response compression is enabled by default when the server is active.

```yaml
server:
  port: 8080
  compression:
    enabled: true        # Default: true.
    min-size: 500        # Minimum response size to compress.
    zstd: true           # Enable Zstandard.
    brotli: true         # Enable Brotli.
    gzip: true           # Enable gzip.
```

## `database`

Configure data persistence. Ceres supports SQLite and PostgreSQL.

### SQLite

```yaml
database:
  type: sqlite
  path: ./local/database.sqlite  # Created automatically.
```

SQLite is the default and is suitable for single-process deployments. If `database` is omitted entirely, a temporary in-memory database is used.

### PostgreSQL

```yaml
database:
  type: postgres
  host: localhost
  port: 5432
  database: ceres
  user: postgres
  password: secret
```

### Password Hashing

Configure the algorithm used for user password hashing.

```yaml
database:
  type: sqlite
  path: ./local/database.sqlite
  hashing:
    type: argon2          # Or "bcrypt".
    time-cost: 3
    memory-cost: 65536
```

## `console`

Customize the web console appearance.

```yaml
console:
  title: My Dashboard              # Browser tab title.
  favicon: ./assets/favicon.png    # Custom favicon image.
  dashboard: ["@sensor", "@motor"] # Components shown on the dashboard.
```

## `logging`

Control what gets printed to stdout and what gets stored in the database.

```yaml
logging:
  output: info       # Minimum level for stdout (debug, info, warning, error, critical).
  store: debug       # Minimum level for database storage.
  events: true       # Log component events. Can be a boolean or a level.
  messages: false    # Log raw connection data.
  particles: false   # Log parsed particles.
  alerts: false      # Log alerts.
```

Per-component logging overrides can be set in each component's configuration.

## `components`

The component tree. Each entry declares a component instance.

```yaml
components:
  - name: my-component
    class: my_project.MyComponent
    arguments:
      param1: value1
      param2: 42
```

### Component Options

| Field         | Description                                                |
| ------------- | ---------------------------------------------------------- |
| `name`        | Unique name within the parent. Becomes part of the address.|
| `class`       | Python import path to the component class. Defaults to `Component` if omitted. |
| `arguments`   | Constructor keyword arguments, validated against the class's type hints. |
| `enabled`     | Whether the component auto-starts. Default: `false`.       |
| `logging`     | Per-component logging overrides.                           |
| `connections` | List of connection configurations. See below.              |
| `sieves`      | List of sieve (data parser) configurations.                |
| `jobs`        | List of scheduled job configurations. See below.           |
| `pruners`     | List of record pruner configurations. See below.           |
| `components`  | Nested child components.                                   |

### Connections

```yaml
connections:
  - name: primary
    source:
      class: ceres.connection.TCPSource
      arguments:
        host: 10.180.80.170
        port: 2101
    splitter:
      class: ceres.connection.SplitByLine
    suffix: "\n"
    buffer-size: 1MB
    buffer-drop: 100KB
    connect-timeout: 5s
    receive-timeout: 10s
    reconnect-schedule: "interval: 5s"
```

See [Connections](connections.md) for details on sources, splitters, and options.

### Jobs

Jobs invoke component actions on a schedule.

```yaml
jobs:
  - name: daily-report
    action: generate_report    # Name of an @action method on the component.
    arguments:
      format: csv
    schedule: "cron: 0 9 * * *"  # Every day at 09:00 UTC.
    retries: 2
    retry-delay: 10s
```

Schedule expressions:

- Cron syntax: `"cron: 0 */6 * * *"`
- Interval: `"interval: 30s"`, `"interval: 5m"`
- Shorthand: `"daily"`, `"hourly"`

### Pruners

Pruners periodically delete old records from the database.

```yaml
pruners:
  - name: clean-old-messages
    prunes: message          # One of: message, particle, alert, log-entry.
    schedule: "0 0 * * *"
    filter:
      max-age: 30d           # Delete records older than 30 days.
```

## Duration Values

Many configuration fields accept duration strings. Supported formats:

- `5s`, `30s`: Seconds.
- `5m`, `30m`: Minutes.
- `1h`, `2h`: Hours.
- `1d`, `7d`: Days.
- `0.5s`, `1.5m`: Fractional values.

## Size Values

Buffer sizes accept human-readable strings:

- `1KB`, `100KB`: Kilobytes.
- `1MB`, `10MB`: Megabytes.
