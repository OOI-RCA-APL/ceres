# Getting Started

This guide walks through creating a Ceres project from scratch, running it, and managing it with the CLI.

## Project Setup

Create a new directory with a `ceres.yaml` configuration file.

```sh
mkdir my-project && cd my-project
uv init
uv add git+ssh://git@github.com/OOI-RCA-APL/ceres.git
source .venv/bin/activate
```

## Writing a Component

Create a Python file with a simple component. Components are async Python classes that inherit from `Component`. Their attributes are typed fields that can be set through configuration.

```python
# counter.py
from asyncio import sleep

from ceres import Component, routine


class Counter(Component):
    initial: int
    delta: int = 1

    @routine
    async def count(self) -> None:
        count = self.initial
        while True:
            self.system.log.info(count)
            await sleep(1)
            count += self.delta
```

The `@routine` decorator marks an async method as a background task. Routines start when the component starts and are cancelled when it stops.

## Configuring the Project

Create a `ceres.yaml` file that declares a database and your components.

```yaml
# ceres.yaml
database:
  type: sqlite
  path: ./local/database.sqlite

components:
  - name: counter-a
    class: counter.Counter
    arguments:
      initial: 5
  - name: counter-b
    class: counter.Counter
    arguments:
      initial: 100
      delta: -5
```

The `class` field is a Python import path. The `arguments` are passed to the component's constructor and validated against its type hints.

## Running

Start the engine in the foreground with all components.

```sh
ceres run all
```

You should see output like this:

```
[2025-01-15 10:00:01.123] [INFO] [@counter-a] 5
[2025-01-15 10:00:01.125] [INFO] [@counter-b] 100
[2025-01-15 10:00:02.124] [INFO] [@counter-a] 6
[2025-01-15 10:00:02.126] [INFO] [@counter-b] 95
```

Press `Ctrl+C` to stop.

## Using the CLI

With the engine running in one terminal, open another terminal in the same directory and activate the virtual environment. The CLI communicates with the running engine over a Unix socket.

### Checking Status

```
$ ceres status

 Engine
╭──────────────────────────────┬─────────┬──────╮
│ Configuration                │ Running │ Port │
├──────────────────────────────┼─────────┼──────┤
│ /path/to/ceres.yaml          │ Yes     │ --   │
╰──────────────────────────────┴─────────┴──────╯

 Components
╭────────────┬─────────┬─────────╮
│ Address    │ Running │ Enabled │
├────────────┼─────────┼─────────┤
│ @          │ Yes     │ No      │
│ @counter-a │ Yes     │ No      │
│ @counter-b │ Yes     │ No      │
╰────────────┴─────────┴─────────╯
```

### Starting and Stopping Components

```sh
ceres stop counter-a        # Stop a specific component.
ceres start counter-a       # Start it again.
ceres stop all              # Stop everything.
```

The `@` prefix on addresses is optional in CLI commands.

### Enabling and Disabling

Enabling a component makes it start automatically when the engine starts, without needing `ceres run all`.

```sh
ceres enable all            # Enable all components.
ceres disable counter-b     # Disable one component.
```

The `up` and `down` commands combine start/enable and stop/disable.

```sh
ceres up all                # Enable and start all components.
ceres down counter-b        # Disable and stop one component.
```

## Running as a Service

Instead of running in the foreground, you can run Ceres as a background service that persists after logout and survives reboots.

```sh
ceres service start         # Install and start the service.
ceres status                # Verify it's running.
ceres service stop          # Stop and remove the service.
```

On Linux, this creates a SystemD user service. On macOS, it creates a LaunchD agent. See [Deployment](deployment.md) for production setup details.

## Adding a Web Console

Add a `server` section to `ceres.yaml` to enable the HTTP API and web console.

```yaml
server:
  port: 8080
```

Restart the engine, then open [http://localhost:8080](http://localhost:8080) in a browser. The console provides a dashboard for monitoring component state, viewing logs, messages, and alerts, and controlling components.

## Validating Configuration

Before running, you can check your `ceres.yaml` for errors.

```sh
ceres check
```

## Watch Mode

During development, use `--watch` to automatically restart the engine when Python files or configuration change.

```sh
ceres run all --watch
```

## Next Steps

- [Writing a Driver](writing-a-driver.md): Build an instrument driver with connections and data parsing.
- [Components](components.md): Learn about routines, events, listeners, and records.
- [Connections](connections.md): Connection sources, splitters, and buffers.
- [Configuration](configuration.md): Full `ceres.yaml` reference.
- [CLI](cli.md): Complete CLI reference.
