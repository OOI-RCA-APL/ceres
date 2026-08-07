# Getting Started

Build a Ceres project from nothing, run it, and drive it from the CLI. Everything on this page is a real transcript.

## Create The Project

```sh
mkdir my-project && cd my-project
uv init
uv add ceres-engine
source .venv/bin/activate
```

## Write A Component

A component is an async Python class. Its annotated attributes are configuration fields, and its `@routine` methods are background tasks that start with the component and are cancelled when it stops.

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

## Configure The Project

`ceres.yaml` declares the database and the component tree.

```yaml
# ceres.yaml
database:
  type: sqlite
  path: ./database.sqlite

logging:
  events: false

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

`class` is a Python import path. `arguments` are passed to the component and validated against its annotations, so a typo or a wrong type fails at load rather than at run.

The database path is relative to the configuration file, and Ceres will not create directories along the way. Point it at a file in a directory that already exists.

`logging.events` is off here only to keep the output short. Left on, every lifecycle event is logged as JSON beside your own log lines, which is useful once you are debugging and noisy while you are reading.

Check it before running anything:

```sh
ceres check
```

```
All checks passed.
```

## Run It

```sh
ceres run all
```

```
[2026-08-06 16:53:11.156] [INFO] [~] Loading configuration from '/path/to/ceres.yaml'.
[2026-08-06 16:53:11.160] [INFO] [~] Database appears empty, running migrations.
[2026-08-06 16:53:11.178] [INFO] [~] Database migrated successfully.
[2026-08-06 16:53:11.179] [INFO] [@counter-a] 5
[2026-08-06 16:53:11.180] [INFO] [@counter-b] 100
[2026-08-06 16:53:12.181] [INFO] [@counter-a] 6
[2026-08-06 16:53:12.181] [INFO] [@counter-b] 95
```

Migrations run on their own the first time, because the database is empty. Press `Ctrl+C` to stop.

## Drive It From Another Terminal

Leave the engine running and open a second terminal in the same directory, with the virtual environment activated. A running engine writes a small file into the project holding a loopback port and a token, and the CLI reads that file and speaks HTTP to it. That is why the CLI has to run inside the project, and why nothing on the network can reach it.

```sh
ceres status
```

```
Engine
╭─────────────────────┬─────────┬─────────────────┬─────────────────╮
│ Configuration       │ Running │ Web Server Port │ CLI Server Port │
├─────────────────────┼─────────┼─────────────────┼─────────────────┤
│ /path/to/ceres.yaml │ Yes     │ (Disabled)      │ 50558           │
╰─────────────────────┴─────────┴─────────────────┴─────────────────╯
Components
╭────────────┬─────────┬─────────╮
│ Address    │ Enabled │ Running │
├────────────┼─────────┼─────────┤
│ @counter-a │ No      │ Yes     │
│ @counter-b │ No      │ Yes     │
╰────────────┴─────────┴─────────╯
```

"Web Server Port" is `(Disabled)` until you add a `server` section. "CLI Server Port" is the loopback port that file names.

### Starting And Stopping

```sh
ceres stop counter-a        # Stop one component.
ceres start counter-a       # Start it again.
ceres stop all              # Stop everything.
```

The `@` prefix on an address is optional on the command line.

### Enabling And Disabling

Running and enabled are separate. Running is now, enabled is whether the engine starts it next time, which is why both columns exist above.

```sh
ceres enable all            # Start these automatically from now on.
ceres disable counter-b
```

`up` and `down` do both halves at once.

```sh
ceres up all                # Enable and start.
ceres down counter-b        # Disable and stop.
```

## Run It As A Service

```sh
ceres service start         # Write the service file and start it.
ceres status
ceres service stop          # Stop it and remove the file.
```

On Linux this is a SystemD user service, on macOS a LaunchD agent. [Deployment](deployment.md) covers the production shape.

## Add The Web Console

```yaml
server:
  port: 8080
```

Restart the engine and open [http://localhost:8080](http://localhost:8080). The console shows component state, logs, messages, and alerts, and can start and stop components. The same data is available over [the HTTP API](reference/http-api.md).

## Watch Mode

```sh
ceres run all --watch
```

Restarts the engine when Python files or the configuration change. For development only.

## Next

- [Components](components.md): routines, events, listeners, and records.
- [Connections](connections.md): reaching instruments and parsing what they send.
- [Writing a Driver](writing-a-driver.md): the two put together, end to end.
- [Configuration](reference/configuration.md): every `ceres.yaml` key.
- [CLI](reference/cli.md): every command and option.
