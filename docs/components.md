# Components

Components are the core build blocks of Ceres. They are general purpose Python objects which do asyncronous work, and can be organized into logical hierarchies.

## Configuration

A component's configuration is defined by the typed attributes in its class. All components are `dataclasses`, so attributes are per-instance, and can be passed via the component's constructor, or more commonly, through the component's `arguments` configuration in `ceres.yaml`.

### Example

```python
# ../examples/random/random.py

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
            # Print a random integer within the configured range.
            self.system.log.info(randint(self.low, self.high))
            # Wait the configured interval.
            await sleep(self.interval.total_seconds())


# This section is only included for example.
if __name__ == "__main__":

    async def main() -> None:
        component = Random(low=1, high=100)
        await component.system.run()

    # Logs a random number between 1 and 100 every second until cancelled.
    asyncio.run(main())
```

```
$ python ./random.py
[2023-11-14 10:17:02.963] [INFO] [@] 19
[2023-11-14 10:17:03.968] [INFO] [@] 54
[2023-11-14 10:17:04.972] [INFO] [@] 99
...
```

If we want to run this component using the Ceres engine, we can define its configuration in `ceres.yaml`.

```yaml
# ../examples/random/ceres.yaml

components:
  - name: random
    class: random.Random
    arguments:
      low: 50
      high: 100
      interval: 0.5s
```

Then run it using the `ceres run` command.

```sh
$ ceres run random
...
[2023-11-14 11:00:12.287] [INFO] [@random] 70
[2023-11-14 11:00:12.789] [INFO] [@random] 94
[2023-11-14 11:00:13.293] [INFO] [@random] 50
[2023-11-14 11:00:13.797] [INFO] [@random] 86
[2023-11-14 11:00:14.301] [INFO] [@random] 82
```

If we need multiple instances of our `Random` class, you can simply add another component to `ceres.yaml`.

```yaml
# ../examples/random/ceres.yaml

components:
  - name: random
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

```sh
$ ceres run all
[2023-11-14 11:15:51.877] [INFO] [@random] [event] [started] {}
[2023-11-14 11:15:51.879] [INFO] [@random] [event] [routine-started] {"routine":"routine__print_random"}
[2023-11-14 11:15:51.881] [INFO] [@random] 94
[2023-11-14 11:15:51.888] [INFO] [@random-b] [event] [started] {}
[2023-11-14 11:15:51.891] [INFO] [@random-b] [event] [routine-started] {"routine":"routine__print_random"}
[2023-11-14 11:15:51.894] [INFO] [@random-b] -8
[2023-11-14 11:15:52.384] [INFO] [@random] 56
[2023-11-14 11:15:52.886] [INFO] [@random] 65
```

## Component Trees

While components can be configured and run on their own, they are usually grouped together in hierarchies, similar to directories in your filesystem. These hierarchies are called _component trees_.

Each component is conceptually a _node_, having an arbitrary number of _child_ components, and _at most_ one _parent_ component. Components _must_ have a unique `name` within their parent. This ensures each component is uniquely _addressable_ within its tree.

### Example

```yaml
components:
  - name: random
    # The "class" is omitted here, and defaults to `Component`.
    components:
      - name: a
        class: random.Random
        arguments:
          low: 50
          high: 100
          interval: 0.5s
      - name: b
        class: random.Random
        arguments:
          low: 50
          high: 100
          interval: 0.5s
```

These components are bound to addresses `@random.a` and `@random.b` respectively.

```sh
ceres run random.a   # Run `@random.a` and its parent component `@random`.
ceres run random.b   # Run `@random.b` and its parent component `@random`.
ceres run random:all # Run all components in the `@random` unit.
ceres run all        # Run all components in the project, which in this case is the same as `@random:all`.
```

### Addresses

A component's `address` describes its position in the tree, and is computed automatically from the component's `name` and the names of its ancestors. In this way, component addresses are similar to file system paths, but refer to the location of a component in a tree rather than a file.

A component with no parent is the _root_ component, and has the address `@`. Other addresses are relative to the root component, and defined by descending component names with `.` as a separator. For example, the address `@a.b.c` refers to a component named `c`, which is a child of `@a.b`, which is a child of `@a`, which is ultimately a child of the root component `@`.

### Hierarchy Implications

Any components _above_ a component (including its parent, grandparent, and so on) are called its _ancestors_. Any components _below_ a component are its _descendants_, or _subcomponents_.

#### Starting & Stopping

A child component can only be running if its parent component, and consequently all of its ancestor components, are running. For convenience, starting a given component will implicitly start all ancestors. For example, starting the component at `@a.b` will also start components `@a` and `@`.

Conversely, when a given component is stopped, all its subcomponents are too.

#### Enabling & Disabling

_Enabling_ a component means it will start automatically when its parent component, or containing engine if it's the root component, starts. All components are _disabled_ by default.

#### Database Inheritance

Components inherit the `database` object of their parent, or containing engine if it's the root component, meaning component trees implicitly store all associated data in the same place. If a component has no parent and is not the root component of an engine, a temporary one is created for it automatically.

#### Configuration

Components in the base `components` list of `ceres.yaml` are implicit _children_ of the root component. The purpose of the Ceres engine itself is to manage the component tree you define in `ceres.yaml`.

## Routines

Components can declare one or more _routines_, which are async methods that execute concurrently when a component is started, and are cancelled when it is stopped.

_Routines are defined using the `@routine` decorator._

```python
# ../examples/csv-generator/generator.py

import csv
from asyncio import sleep
from pathlib import Path
from random import choice

from ceres import Component, routine


class CSVNameGenerator(Component):
    output: Path

    @routine
    async def routine__startup(self) -> None:
        """
        This routine will run once on startup.
        """
        self.log.info(f"Starting up. Writing to '{self.output}'...")

    @routine(restart="always", restart_delay=5)
    async def routine__write(self) -> None:
        """
        This routine will run on startup and execute forever, restarting if it crashes for any
        reason.
        """
        while True:
            self.output.parent.mkdir(parents=True, exist_ok=True)

            exists = self.output.exists()
            with self.output.open("a+") as stream:
                writer = csv.writer(stream)
                if not exists:
                    writer.writerow(["first", "last"])

                first, last = (
                    self.__get_random_first_name(),
                    self.__get_random_last_name(),
                )

                row = [first, last]
                writer.writerow(row)
                self.log.info(row)

            await sleep(1)

    @routine
    async def routine__log_file_size(self) -> None:
        """
        This routine will also run on startup and execute forever, but will not restart if an
        exception is thrown.
        """
        while True:
            if self.output.exists():
                size = self.output.stat().st_size
                self.log.info(f"'{self.output}' is now {size} bytes.")
            else:
                self.log.info(f"'{self.output}' has not been created yet.")

            await sleep(5)

    def __get_random_first_name(self) -> str:
        return choice(["Alice", "Bob", "Charlie", "Diane"])

    def __get_random_last_name(self) -> str:
        return choice(["Montgomery", "Gonzalez", "Dunsworth", "Paris"])
```

```yaml
# ../examples/csv-generator/ceres.yaml

components:
  - name: generator
    class: generator.RandomCSVNameGenerator
    arguments:
      output: ./local/output.csv
```

```sh
$ ceres run all
...
[2023-11-14 13:49:07.886] [INFO] [@generator] 'output.csv' is now 186 bytes.
[2023-11-14 13:49:07.908] [INFO] [@generator] ['Bob', 'Paris']
[2023-11-14 13:49:08.911] [INFO] [@generator] ['Diane', 'Montgomery']
[2023-11-14 13:49:09.915] [INFO] [@generator] ['Charlie', 'Montgomery']
[2023-11-14 13:49:10.918] [INFO] [@generator] ['Diane', 'Paris']
[2023-11-14 13:49:11.921] [INFO] [@generator] ['Alice', 'Paris']
[2023-11-14 13:49:12.890] [INFO] [@generator] 'output.csv' is now 253 bytes.
[2023-11-14 13:49:12.924] [INFO] [@generator] ['Charlie', 'Dunsworth']
[2023-11-14 13:49:13.928] [INFO] [@generator] ['Diane', 'Gonzalez']
[2023-11-14 13:49:14.933] [INFO] [@generator] ['Alice', 'Paris']
[2023-11-14 13:49:15.937] [INFO] [@generator] ['Diane', 'Dunsworth']
[2023-11-14 13:49:16.942] [INFO] [@generator] ['Diane', 'Montgomery']
...
```

_You can view generated names in `./local/output.csv`._

## Events

All components emit _events_. Events are simple objects with a `type`, `address` and `timestamp` that can be listened for and reacted to by other components. The component `emit` method is used to emit events by passing the event class and its constructor's keyword arguments. Emitted events are assigned the `address` of the component that emitted them.

When an event is emitted, it's propagated up the component tree through all the component's ancestors. Functionally, this means components inherit the events of their subcomponents, though the `address` of the emitted event is still the address of the component that originally emitted it.

All events are subclasses of `Event`. Custom events can be created by inheriting this class and assigning a new `type`, however custom events are not always necessary. Components emit many standard events automatically, all of which can be listened for by other components.

#### Standard Events

- `LifecycleEvent`: Events relating to component lifecycles.
  - `AddedEvent`: A component was added to the component tree.
  - `StartedEvent`: A component was started.
  - `StoppingEvent`: A component is stopping.
  - `StoppedEvent`: A component just stopped.
  - `RemovedEvent`: A component was removed from the component tree.
  - `EnabledEvent`: A component was enabled.
  - `DisabledEvent`: A component was disabled.
- `RoutineEvent`: Events relating to component routines. All subtypes include the name of the related routine.
  - `RoutineStartedEvent`: A routine was started.
  - `RoutineStoppedEvent`: A routine exited for any reason.
  - `RoutineCancelledEvent`: A routine was cancelled early.
  - `RoutineCompletedEvent`: A routine exited without an exception.
  - `RoutineExceptionEvent`: A routine exited with an exception.
- `JobEvent`: Events relating to component jobs. All subtypes include the name of the related job.
  - `JobAddedEvent`: A component scheduled a job.
  - `JobRemovedEvent`: A component unscheduled a job.
  - `JobStartedEvent`: A job is was started.
  - `JobStoppedEvent`: A job is exited for any reason.
  - `JobCancelledEvent`: A job was cancelled early.
  - `JobCompletedEvent`: A job exited without an exception.
  - `JobExceptionEvent`: A job exited with an exception.
  - `JobRetryPendingEvent`: A job was scheduled to be retried.
  - `JobRetryEvent`: A job is being retried.
- `ProcedureEvent`: Events related to calls of component queries and actions. All subtypes include the name of the related procedure.
  - `ProcedureCalledEvent`: A component procedure was called.
  - `ProcedureCancelledEvent`: A component procedure call was cancelled early.
  - `ProcedureCompletedEvent`: A component procedure call exited without an exception.
  - `ProcedureExceptionEvent`: A component procedure call exited with an exception.
- `MessageEvent`: A connection component sent/received a message. All subtypes include the emitted `message` object.
  - `MessageReceivedEvent`: A connection component _received_ a message.
  - `MessageSentEvent`: A connection component _sent_ a message.
- `AlertEvent`: A component emitted an alert. Includes the emitted `alert` object.
- `LogEvent`: A component emitted a log entry. Includes the emitted `entry` object.

#### Event Listeners

Components can register _event listeners_ using the `@listener` decorator. Event listeners can be used to process a component's own events or the events of other components. Events will only be processed by a component while the component is running.

###### `@listener` Decorator Parameters

- `event`: An event class to listen for. If `event` is not passed as an argument, the event type is determined by the type annotation of the `event` parameter in the listening method.
- `reference`: An optional name of the reference to listen for events from. _For example, if you have a reference to a connection component like `connection: Ref[Connection]` you can listen to its events using `@listener(reference="connection)"`._
- `address`: An optional address selector or selectors to listen for events from. _For example, to listen to events from a component at the address `@connection`, use `@listener(address="@connection")`, or if you'd like to listen to the events of every component in the tree, use `@listener(address="all")`._
- `local`: Whether to listen for events emitted by the component itself. This will default to `True` if neither `reference` or `address` are specified, and `False` otherwise.

_Event listener methods are executed asyncronously, separate from the original call to `emit`. Components maintain separate event queues for each event listener they have registered, and process them at their own pace. Calling `emit` only distributes the event to those queues, and as a result, listeners are isolated, and will never crash code that emits events._

#### Example

```python
from asyncio import sleep
from datetime import datetime
from typing import Literal

from ceres import Component, Event, Ref, routine, listener


class CountEvent(Event):
    type: Literal["count"] = "count"
    count: int


class EventEmitterExample(Component):
    @routine
    async def routine__emit_count_events(self) -> None:
        """
        Emit a `CountEvent` every second.
        """
        count = 0

        while True:
            event = self.emit(CountEvent, count=count)
            assert isinstance(event, CountEvent)
            assert type == "count"
            assert isinstance(event.timestamp, datetime)

            await sleep(1)
            count += 1

    # Omitting any arguments to `@listener` is the same as setting `local=True`, and will listen for
    # events on this component itself. The event type the listened for is inferred from the type
    # annotation of `event`.
    @listener
    async def on__local_count_event(self, event: CountEvent) -> None:
        """
        Handle `CountEvent`s emitted by this component.
        """
        self.log.info(f"Local count event at {event.address}. Count is {event.count}.")


class EventListenerExample(Component):
    emitter: Ref[EventEmitterExample]

    @listener(reference="emitter")
    async def on__emitter_count_event(self, event: CountEvent) -> None:
        """
        Handle `CountEvent`s emitted by `emitter`.
        """
        self.log.info(f"External count event at {event.address}. Count is {event.count}.")

    @listener(address="all")
    async def on__global_event(self, event: Event) -> None:
        """
        Handle all events in the component tree.
        """
        self.log.info(f"Received global event at {event.address} of type {type(event)}.")
```

```yaml
components:
  - name: emitter
    class: events.EventEmitterExample
  - name: listener
    class: events.EventListenerExample
    arguments:
      emitter: "@emitter" # Pass a reference to the `emitter` component.
```

## Records

Components own three types of _record_ data which are persisted in the project database. These record types are _messages_, _alerts_ and _log entries_.

_Records are usually written to the database asyncronously in buffered batches, so they may not be immediately available after being emitted._

### Messages

Messages are a record of data sent or received by a `Connection` component.

| Field       | Python Type              | Description                                                                                 |
| ----------- | ------------------------ | ------------------------------------------------------------------------------------------- |
| `id`        | `UUID`                   | An autogenerated UUID primary key.                                                          |
| `address`   | `ceres.Address`          | The address of the component that sent or received the message.                             |
| `timestamp` | `datetime`               | The timestamp at which the message was sent or received. Defaults to the current timestamp. |
| `direction` | `ceres.MessageDirection` | Either "send" or "receive" depending on if the component sent or received a message.        |
| `content`   | `ceres.MessageContent`   | The raw bytes of the original message.                                                      |

#### Creation

To persist messages for a component, the component should emit a `MessageSentEvent` or `MessageReceivedEvent` event, passing a `Message` instance as the `message` argument.

```python
from ceres import Message, MessageDirection
from ceres.event import MessageReceivedEvent, MessageSentEvent

# In a component...

self.emit(
    MessageSentEvent,
    message=Message(address=self.address, direction=MessageDirection.SEND, content=b"SEND\n")
)
self.emit(
    MessageReceivedEvent,
    message=Message(address=self.address, direction=MessageDirection.RECEIVE, content=b"RECEIVE\n")
)
```

#### Retrieval

Messages can be retrieved using `system.messages.where()` and `system.messages.select()`.

```python
from asyncio import sleep

from ceres import Connection, Component, MessageOrder, Ref, routine

class Driver(Component)
    connection: Ref[Connection]

    @routine
    async def routine__log_connection_messages(self) -> None:
        while True:
            # Get the latest 10 messages sent or received by the connection component.
            latest = await self.connection.system.where(order="timestamp:desc").limit(10)
            self.log.info(latest)

            # Alternatively, you can pass the address of `@connection`.
            latest = await self.system.messages.where(
                address="@connection",
                order="timestamp:desc",
            ).limit(10)
            self.log.info(latest)

            # Get the oldest message sent or received by the connection component.
            oldest = await self.connection.system.messages.select().first()
            self.log.info(oldest)

            await sleep(5)
```

### Alerts

Alerts are records of notable events, usually errors, which have occurred. Any component can emit alerts using its `alert` method.

_Do note that emitting an alert doesn't actually send it anywhere, it will just be stored in the database. To send alerts out as notifications, use a `Dispatcher`._

| Field       | Python Type      | Description                                                                      |
| ----------- | ---------------- | -------------------------------------------------------------------------------- |
| `id`        | `UUID`           | An autogenerated UUID primary key.                                               |
| `address`   | `ceres.Address`  | The address of the component that emitted the alert.                             |
| `timestamp` | `datetime`       | The timestamp at which the alert was created. Defaults to the current timestamp. |
| `level`     | `ceres.Level`    | A level specifying the severity of the alert.                                    |
| `type`      | `str`            | An arbitrary string which can be used to retrieve alerts of a particular type.   |
| `data`      | `dict[str, Any]` | A JSON serializable dictionary with arbitrary values.                            |

#### Creation

To emit alerts for a component, the component should call the `alert` method, passing a `level`, `code` and `info` dictionary for additional information if needed.

```python
from ceres import Level

# In a component...

self.alert(Level.ERROR, "airlock/jammed", {"message": "The airlock is jammed.", "pressure": 200})
self.alert(Level.INFO, "airlock/recovered", {"message": "Oh, nevermind. We're good.", "pressure": 1000})
```

#### Retrieval

Alerts can be retrieved using `system.alerts.where()` and `system.alerts.select()`.

```python
from asyncio import sleep

from ceres import AlertOrder, Component, routine

class Example(Component)
    @routine
    async def routine__log_alerts(self) -> None:
        while True:
            # Get the latest 10 alerts emitted by this component.
            latest = await self.system.alerts.where(order="timestamp:desc").limit(10)

            # Get the latest 10 alerts from the component `@other`.
            latest = await self.system.alerts.where(
                address="@other",
                order="timestamp:desc"
            ).limit(10)

            # Get the oldest alert emitted by any component in the tree.
            oldest = await self.root.alerts.where(address="all").first()
            await sleep(5)
```

### Log Entries

Components can log arbitrary messages to for monitoring purposes. These log entries are written to standard out by default, and persisted in the component's `database` for later analysis.

| Field       | Python Type     | Description                                                                     |
| ----------- | --------------- | ------------------------------------------------------------------------------- |
| `id`        | `UUID`          | An autogenerated UUID primary key.                                              |
| `address`   | `ceres.Address` | The address of the component that created the log entry.                        |
| `timestamp` | `datetime`      | The timestamp at which the entry was logged. Defaults to the current timestamp. |
| `level`     | `ceres.Level`   | A level specifying the severity of the log entry.                               |
| `content`   | `str`           | An arbitrary string message.                                                    |

#### Creation

Components can log messages through `system.log`, which mirrors Python's built-in `Logger` class.

```python
from asyncio import sleep

from ceres import Component, Level, LogEntry, routine

class Example(Component):
    @routine
    def routine__log_stuff(self) -> None:
        i = 0

        while True:
            self.log.info("Log test {} started.", i)

            self.log.debug("We're debugging. No worries.")
            self.log.info("Wait, I have some information.")
            self.log.warning("Something might be wrong.")
            self.log.error("Something has gone very wrong.")
            self.log.critical("Everything's going to explode.")

            entry = self.log.info("Log test {} ended.", i)

            assert isinstance(entry, LogEntry)
            assert entry.level == Level.INFO
            assert entry.address == self.address

            i += 1
            await self.sleep(1)
```

#### Retrieval

Log entries can be retrieved using `system.log.where()` and `system.logs.select()`.

```python
from asyncio import sleep

from ceres import Address, Connection, Component, Ref, routine

class Example(Component)
    @routine
    async def routine__get_log_entry_counts(self) -> None:
        while True:
            # Get the latest 10 alerts emitted by this component.
            latest = await self.logs.where(order="timestamp:desc").limit(10)

            # Get the latest 10 log entries from the component `@other`.
            latest = await self.logs.where(address="@other", order="timestamp:desc").limit(10)

            # Get the oldest log entry emitted by any component in the tree.
            oldest = await self.root.logs.select().first()
            await sleep(5)
```
