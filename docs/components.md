# Components

Components are the core building blocks of Ceres. They are async Python objects that do concurrent work and can be organized into hierarchies.

## Configuration

A component's configuration is defined by the typed attributes in its class. All components are Pydantic dataclasses, so attributes are per-instance and can be passed via the constructor or, more commonly, through the `arguments` section of `ceres.yaml`.

### Example

```python
import asyncio
from asyncio import sleep
from datetime import timedelta
from random import randint

from ceres import Component, routine
from ceres.data import TimeDelta


class Random(Component):
    low: int
    high: int
    interval: TimeDelta = timedelta(seconds=1)

    @routine
    async def routine__print_random(self) -> None:
        while True:
            self.system.log.info(randint(self.low, self.high))
            await sleep(self.interval.total_seconds())
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
from ceres import Component, routine


class Example(Component):
    @routine
    async def routine__do_work(self) -> None:
        while True:
            self.system.log.info("Working...")
            await sleep(1)
```

### Restart Policies

By default, routines run once. If they complete or crash, they are not restarted. You can change this behavior.

```python
@routine(restart="always", restart_delay=5)
async def routine__resilient(self) -> None:
    ...
```

Restart options:

- `"never"` (default): Do not restart.
- `"always"`: Restart on completion or exception.
- `"on-completed"`: Restart only if the routine returns normally.
- `"on-exception"`: Restart only if the routine raises an exception.

`restart_delay` specifies seconds to wait before restarting.

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

## Events

All components emit events. Events are objects with a `type`, `address`, and `timestamp` that propagate up through the component tree. This means parent components automatically receive events from their children.

### Standard Events

Ceres emits these events automatically:

**Lifecycle events:** `StartedEvent`, `StoppedEvent`, `EnabledEvent`, `DisabledEvent`, `AttachedEvent`, `DetachedEvent`

**Routine events:** `RoutineStartedEvent`, `RoutineCompletedEvent`, `RoutineExceptionEvent`, `RoutineRestartedEvent`

**Job events:** `JobStartedEvent`, `JobCompletedEvent`, `JobExceptionEvent`, `JobRetryEvent`

**Procedure events:** `ProcedureCalledEvent`, `ProcedureCompletedEvent`, `ProcedureExceptionEvent`

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

Emit events with `self.emit()`.

```python
self.emit(CountEvent, count=42)
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
from ceres import Level

self.alert(Level.ERROR, "sensor/timeout", {"message": "No data received in 30 seconds."})
self.alert(Level.INFO, "sensor/recovered", {"message": "Connection restored."})
```

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

Components log messages through `self.system.log` (or the shorthand `self.log`), which mirrors Python's `logging.Logger` interface. Log entries are printed to stdout and persisted in the database.

```python
self.log.debug("Debugging info.")
self.log.info("Normal operation.")
self.log.warning("Something might be wrong.")
self.log.error("Something failed.")
self.log.critical("System is in a bad state.")
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
