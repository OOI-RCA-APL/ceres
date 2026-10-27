# Components

Components are the core building blocks of Ceres. They are async Python objects that do concurrent work and can be organized into hierarchies.

## Configuration

A component's configuration is defined by the typed attributes in its class. All components are Pydantic dataclasses, so attributes are per-instance and can be passed via the constructor or, more commonly, through the `arguments` section of `ceres.yaml`.

### Example

```python
from datetime import timedelta
from random import randint

from ceres import Component, routine, sleep
from ceres.data import TimeDelta


class Random(Component):
    low: int
    high: int
    interval: TimeDelta = timedelta(seconds=1)

    @routine
    async def print_random(self) -> None:
        while True:
            self.system.log.info(randint(self.low, self.high))
            await sleep(self.interval)
```

```yaml
# ceres.yaml
components:
  - name: random
    class: random.Random
    arguments:
      low: 50
      high: 100
      interval: 0.5s
```

```sh
$ ceres run random
[2025-01-15 11:00:12.287] [INFO] [@random] 70
[2025-01-15 11:00:12.789] [INFO] [@random] 94
[2025-01-15 11:00:13.293] [INFO] [@random] 50
```

Multiple instances of the same class can be declared with different arguments.

```yaml
components:
  - name: random-a
    class: random.Random
    arguments:
      low: 50
      high: 100
      interval: 0.5s
  - name: random-b
    class: random.Random
    arguments:
      low: -10
      high: 10
      interval: 1s
```

## Mounts

A `Mount` is a directory a component reads or writes. Each of its methods mirrors its `pathlib.Path` namesake, joining with `/` never leaves the directory, and `parent` stops at it. `AsyncMount` offers the same methods as coroutines, which run the filesystem call off the event loop. Either converts to the other at the same place, `AsyncMount(mount)`.

A component declares a mount with `Mount.Field`, and the console's "Files" page then lists it for anyone who may view the component (see [Files](deployment.md#files)). The annotation picks the value type, and `AsyncMount.Field` is the same declaration.

```python
from ceres import AsyncMount, Bound, Component, Mount


class Recorder(Component):
    output: Bound[AsyncMount] = Mount.Field(..., title="Recordings")
    calibration: Bound[Mount] = Mount.Field("./calibration", writable=False)
    scratch: Bound[Mount] = Mount.Field()

    async def save(self, name: str, data: bytes) -> None:
        await (self.output / name).write_bytes(data)
```

```yaml
components:
  - name: recorder
    class: recorder.Recorder
    arguments:
      output: ./data
```

- `Mount.Field(...)` makes the field required. A path default, such as `"./calibration"`, resolves the same way a configured path does, and `Mount.Field()` with no path gives the component a temporary directory, removed once nothing refers to it. `Mount.Field(default=None)` makes the mount optional, its annotation `Bound[Mount | None]`.
- A relative path in `ceres.yaml` resolves against the directory holding that file, wherever the engine runs from. One given in code, such as `Mount("./data")`, resolves against the current directory, as `Path` does.
- `title` names the mount in the console, the field name in title case otherwise, and `name` lists it under another name than the field's. Two fields of one component never share a name.
- `writable=False` makes the component's own writes raise `PermissionError`, and the console offers the mount for viewing only. Configuration cannot make such a field writable.
- `access` lowers what the console may do with the mount, `"view"` to browse and download only, `"none"` to hide it. Configuration may lower it further with a mapping, `output: {path: ./data, access: view}`. The console grants the least of this, `server.files.access`, and the caller's permission on the component.

### Layouts

A mount with a `layout` keeps its files in dated folders below its root. `dated(when)` returns the mount for the folder holding `when`, creating the folders, and `periods(after, before)` walks the folders that exist for a span, oldest first. Without a layout, `dated` returns the mount itself and `periods` yields it.

```python
from datetime import UTC, datetime

from ceres import Bound, Component, Mount, PathTemplate


class Photographer(Component):
    stills: Bound[Mount] = Mount.Field(..., layout="{year}/{month}/{day}", zone="local")
    file_name: PathTemplate = PathTemplate.Field(
        "still_{datetime}_{sequence}.jpg", atoms=["sequence"]
    )

    def keep(self, image: bytes, sequence: int) -> None:
        now = datetime.now(UTC)
        name = self.stills.render(self.file_name, now, {"sequence": sequence})
        (self.stills.dated(now) / name).write_bytes(image)
```

```yaml
components:
  - name: photographer
    class: photographer.Photographer
    arguments:
      stills: {path: ./stills, layout: "{year}/{month}", zone: utc}
```

- A layout names time from the year down: `{year}` or `{yy}`, then `{month}`, `{m}`, `{mon}`, `{month_name}`, or `{doy}`, then `{day}` or `{d}`, `{hour}` or `{h}`, `{minute}`, and `{second}`. `{date}`, `{time}`, and `{datetime}` count as their parts. It may also use `{component}`, `{mount}`, `{project}`, and `{host}`. The engine refuses any other atom, since `periods` could not read the time back from the folder name.
- `zone` decides which day a time falls on, `utc` when omitted, `local` for the server's time zone, or an IANA name such as `America/Los_Angeles`.
- Configuration replaces each key it gives, and `layout: null` turns the layout off. A key left out keeps the field's.
- The console's "Files" page shows a "Today" button on a mount with a layout, which opens the folder holding the current time.

### File Name Templates

`PathTemplate` is the grammar a layout uses, for any file name a component writes. `PathTemplate.Field` declares one as a field, so configuration can change it, and refuses a bad template when the class is created or the configuration loads. `atoms` names the atoms the component supplies itself. `mount.render(template, when, values)` renders it in the mount's zone with the mount's names, and the dictionary supplies the rest.

| Atoms | Render 2026-10-27 13:45:09 UTC as |
| --- | --- |
| `{year}` `{month}` `{day}` `{hour}` `{minute}` `{second}` | `2026` `10` `27` `13` `45` `09` |
| `{date}` `{time}` `{datetime}` | `20261027` `134509` `20261027T134509` |
| `{week}` `{doy}` `{epoch}` `{zone}` | `44` `300` `1793108709` `UTC` |
| `{yy}` `{m}` `{d}` `{h}` | `26` `10` `27` `13` |
| `{mon}` `{month_name}` `{wd}` `{weekday}` | `Oct` `October` `Tue` `Tuesday` |
| `{component}` `{mount}` `{connection}` `{project}` `{host}` | Names the component supplies, `{host}` this machine's name by default |

- Long time atoms are zero padded to a fixed width, so names sort by time. Short ones read as people write them.
- `{zone}` and `%Z` render `UTC` at a zero offset and the offset otherwise, `-0700` in Los Angeles summer time, since zone abbreviations differ between platforms.
- `{time:%j}` renders a `strftime` pattern limited to `%Y %y %m %d %H %I %p %M %S %j %b %B %a %A %G %V %u %w %z %Z %%`, in English on every platform. `{{` and `}}` write a brace.
- A template renders a relative path. The engine refuses an unknown atom, an absolute path, an empty, `.`, or `..` segment, a character Windows cannot hold in a file name, and a name Windows reserves, such as `CON`. A name atom rendering a separator fails when it renders.

## Component Trees

Components can be organized into hierarchies called _component trees_. Each component is a node with an arbitrary number of children and at most one parent. Component names must be unique within their parent.

```yaml
components:
  - name: sensors
    components:
      - name: temperature
        class: drivers.TemperatureSensor
        arguments: { ... }
      - name: pressure
        class: drivers.PressureSensor
        arguments: { ... }
```

The nested components above have addresses `@sensors.temperature` and `@sensors.pressure`.

In most deployments, components are declared directly at the top level of `ceres.yaml`. Nesting is available when logical grouping is useful, but it is not required.

### Addresses

A component's address describes its position in the tree. `@` is the absolute-address anchor, similar to a leading `/` in a file path: it prefixes every address and is not itself the address of any component. Top-level components have addresses like `@a`, and nested addresses separate levels with `.`. For example, `@a.b.c` refers to component `c`, child of `@a.b`, child of `@a`. `@` is also the base of selectors that span every component (`@:all`). If you want a shared root that all your components live under, declare an ordinary component and nest everything else beneath it.

### Lifecycle Rules

**Starting and stopping.** A child component can only run if all of its ancestors are running. Starting a component implicitly starts its ancestors. Stopping a component stops all of its descendants.

**Enabling and disabling.** Enabling a component makes it start automatically when its parent starts. All components are disabled by default.

**Database inheritance.** Components inherit the database of their parent (or the engine, for root-level components). All data in a component tree goes to the same database.

## Routines

Routines are async methods that execute concurrently when a component starts and are cancelled when it stops. Define them with the `@routine` decorator.

```python
from ceres import Component, routine, sleep


class Example(Component):
    @routine
    async def do_work(self) -> None:
        while True:
            self.system.log.info("Working...")
            await sleep(1)
```

Use Ceres's `sleep` rather than `asyncio.sleep`. It takes seconds, a `timedelta`, or `...`
to sleep until the routine is cancelled, which is how a routine waits for events rather
than polling.

### Restart Policies

By default, routines run once. If they complete or crash, they are not restarted. You can change this behavior.

```python
@routine(restart="always", restart_delay=5)
async def resilient(self) -> None:
    ...
```

Restart options:

- `"never"` (default): Do not restart.
- `"always"`: Restart on completion or exception.
- `"on-completed"`: Restart only if the routine returns normally.
- `"on-exception"`: Restart only if the routine raises an exception.

`restart_delay` is how long to wait before restarting, as seconds or a duration, and
defaults to one second.

## Queries and Actions

Queries and actions are RPC-style methods exposed through the HTTP API and web console. Use `@query` for read-only operations and `@action` for operations with side effects.

```python
from ceres import Component, action, query


class Sensor(Component):
    last_reading: float = 0.0

    @query
    async def get_reading(self) -> dict:
        return {"value": self.last_reading}

    @action
    async def calibrate(self, offset: float) -> dict:
        self.last_reading += offset
        return {"calibrated": True}
```

Both decorators accept a `permit` parameter controlling who can call them. It takes `"public"` or a `ComponentAccessLevel`, checked against the caller's effective access on the component.

- `"public"`: Anyone can call, including unauthenticated requests.
- `"view"` (default for queries): Requires `VIEW` access or higher.
- `"operate"` (default for actions): Requires `OPERATE` access or higher.
- `"manage"`: Requires `MANAGE` access.
- `"deny"`: Nobody can call it over the API.

`@query` also takes `poll`, how often the console refreshes the value, defaulting to five
seconds. Both decorators take `media` to declare a response content type.

The method's docstring documents it in the console. Its prose shows above the arguments, rendered
as Markdown and cut to a few lines with a "Show more". The text it gives each argument shows
under that argument's field, and what it says about the return value and the exceptions raised
shows beside the result. Both Google sections and Sphinx fields are read:

```python
@action
async def move(self, x: float, y: float = 0.0) -> bool:
    """Move the stage to a position.

    Args:
        x: Where to go along x, in millimetres.
        y: Where to go along y.

    Returns:
        Whether the stage arrived.

    Raises:
        ValueError: If the position is out of range.
    """
```

```python
@action
async def move(self, x: float, y: float = 0.0) -> bool:
    """Move the stage to a position.

    :param x: Where to go along x, in millimetres.
    :param y: Where to go along y.
    :returns: Whether the stage arrived.
    :raises ValueError: If the position is out of range.
    """
```

Only arguments in the signature are documented, and types written in the docstring are ignored in
favour of the signature's. An argument declaring its own `Field(description=...)` keeps it.

## Events

All components emit events. Events are objects with a `type`, `address`, and `timestamp` that propagate up through the component tree. This means parent components automatically receive events from their children.

### Standard Events

Ceres emits these events automatically:

**Lifecycle events:** `StartedEvent`, `StoppedEvent`, `EnabledEvent`, `DisabledEvent`, `AttachedEvent`, `DetachedEvent`

**Routine events:** `RoutineStartedEvent`, `RoutineCompletedEvent`, `RoutineExceptionEvent`, `RoutineRestartedEvent`

**Job events:** `JobStartedEvent`, `JobCompletedEvent`, `JobExceptionEvent`, `JobRetryEvent`

**Procedure events:** `ProcedureCalledEvent`, `ProcedureCompletedEvent`, `ProcedureCancelledEvent`, `ProcedureExceptionEvent`. A procedure returning a `StreamingOutput` ends its call when the output first closes, completed when the stream ran out, an exception when reading it raised, and cancelled when it closed early. A returned `FileOutput` completes the call at once.

**Stream events:** `StreamLostEvent`, `StreamReconnectScheduledEvent`, `StreamReconnectedEvent`, `StreamEndedEvent`, emitted by `rtsp()` streams on the component whose procedure returned them, or on the `component=` they were given.

**Message events:** `MessageReceivedEvent`, `MessageSentEvent`

**Other events:** `AlertEvent`, `LogEvent`, `ConnectedEvent`, `DisconnectedEvent`, `ConnectionLostEvent`

### Custom Events

Create custom events by subclassing `Event`.

```python
from typing import Literal

from ceres import Event


class CountEvent(Event):
    type: Literal["count"] = "count"
    count: int
```

Emit events through the system's event manager, which fills in the emitting component's address.

```python
self.system.events.emit(CountEvent, count=42)
```

### Event Listeners

Use `@listener` to react to events. By default, a listener only receives events from its own component.

```python
from ceres import Component, listener, routine
from ceres.event import StartedEvent


class Example(Component):
    @listener
    async def on_started(self, event: StartedEvent) -> None:
        self.system.log.info("Component started.")
```

#### Listening to other components

Use `reference` to listen to events from a referenced component.

```python
from ceres import Component, Connection, Ref, listener
from ceres.event import MessageReceivedEvent


class Driver(Component):
    connection: Ref[Connection]

    @listener(reference="connection")
    async def on_message(self, event: MessageReceivedEvent) -> None:
        self.system.log.info(f"Received: {event.message.data}")
```

Use `address` to listen to events from any component in the tree.

```python
@listener(address="all")
async def on_any_event(self, event: Event) -> None:
    self.system.log.info(f"Event from {event.address}: {event.type}")
```

#### Listener parameters

- `event`: Event class to listen for. If omitted, inferred from the method's type hint.
- `reference`: Name of a `Ref` field to listen to.
- `address`: Address selector for cross-component listening.
- `local`: Listen for events from this component. Defaults to `True` when neither `reference` nor `address` is set.

Event listeners execute asynchronously in their own task, separate from the code that emits the event. Each listener maintains its own queue, so a slow or crashing listener does not affect other listeners or the emitting code.

## Records

Components own three types of persistent records stored in the database: messages, alerts, and log entries. Records are written asynchronously in buffered batches, so they may not be immediately available after being created.

### Messages

Messages are records of data sent or received by a connection. They are created automatically when a connection receives or sends data.

| Field       | Type               | Description                                          |
| ----------- | ------------------ | ---------------------------------------------------- |
| `id`        | `UUID`             | Auto-generated primary key.                          |
| `address`   | `Address`          | Address of the component that owns the connection.   |
| `timestamp` | `datetime`         | When the message was sent or received.               |
| `direction` | `MessageDirection` | `"send"` or `"receive"`.                             |
| `data`      | `bytes`            | The raw bytes of the message.                        |

### Alerts

Alerts are records of notable events, usually errors. Any component can emit alerts.

```python
self.system.alert.error("sensor/timeout", {"message": "No data received in 30 seconds."})
self.system.alert.info("sensor/recovered", {"message": "Connection restored."})
```

There is one shortcut per level, and `self.system.alert.emit(...)` takes the level as an argument when it is decided at run time.

| Field       | Type      | Description                                |
| ----------- | --------- | ------------------------------------------ |
| `id`        | `UUID`    | Auto-generated primary key.                |
| `address`   | `Address` | Address of the emitting component.         |
| `timestamp` | `datetime`| When the alert was created.                |
| `level`     | `Level`   | Severity (DEBUG, INFO, WARNING, ERROR, CRITICAL). |
| `type`      | `str`     | Arbitrary string for categorization.       |
| `data`      | `dict`    | JSON-serializable context.                 |

Emitting an alert stores it in the database but does not send it anywhere. To dispatch alerts as notifications (e.g., email), configure a `Dispatcher`.

### Log Entries

Components log through `self.system.log`, which mirrors Python's `logging.Logger`. Entries are printed to stdout and persisted in the database.

```python
self.system.log.debug("Debugging info.")
self.system.log.info("Normal operation.")
self.system.log.warning("Something might be wrong.")
self.system.log.error("Something failed.")
self.system.log.critical("System is in a bad state.")
```

| Field       | Type      | Description                            |
| ----------- | --------- | -------------------------------------- |
| `id`        | `UUID`    | Auto-generated primary key.            |
| `address`   | `Address` | Address of the logging component.      |
| `timestamp` | `datetime`| When the entry was logged.             |
| `level`     | `Level`   | Severity level.                        |
| `content`   | `str`     | The log message.                       |

### Querying Records

Records can be queried programmatically from within a component.

```python
latest_messages = await self.system.messages.where(order="timestamp:desc").limit(10)
alert_count = await self.system.alerts.where(level="error").count()
recent_logs = await self.system.logs.where(order="timestamp:desc").limit(50)
```

Records can also be queried from the CLI. See the [CLI reference](reference/cli.md).
