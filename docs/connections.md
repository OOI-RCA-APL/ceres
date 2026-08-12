# Connections

A connection is a managed byte stream between a component and a remote instrument or service. It connects, reconnects, buffers, and splits the incoming stream into discrete messages, all as a background task owned by its component.

A connection is a `Source` (the transport) plus a `Splitter` (where to cut the stream). Each cut becomes a `Message` record.

## Declaring A Connection

Connections are declared in `ceres.yaml` under the owning component.

```yaml
components:
  - name: driver
    class: my_project.Driver
    connections:
      - name: primary
        arguments:
          source:
            class: ceres.connection.TCPSource
            arguments:
              host: 192.0.2.10
              port: 2101
          splitter:
            class: ceres.connection.SplitByLine
```

Everything except `name` and `class` goes under `arguments`. A connection entry accepts exactly three keys, `name`, `class`, and `arguments`, and anything else fails to load. `class` defaults to `Connection` itself and is only needed for a subclass.

This gives `@driver` a connection called `primary` that splits on newlines and stores each line as a `Message`.

### As A Component Argument

When a component declares a `Connection` field, the connection can be passed as an argument instead.

```yaml
components:
  - name: driver
    class: my_project.Driver
    arguments:
      connection:
        source:
          class: ceres.connection.TCPSource
          arguments:
            host: localhost
            port: 4000
```

### In The Class

A connection can also be declared statically, which is the right place for anything inherent to the instrument rather than to the deployment.

```python
from ceres import Bound, Component, Connection, SplitByLine


class Driver(Component):
    connection: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
    )
```

## Sources

### `TCPSource`

```yaml
source:
  class: ceres.connection.TCPSource
  arguments:
    host: 192.0.2.10
    port: 2101
```

### `UNIXSocketSource`

```yaml
source:
  class: ceres.connection.UNIXSocketSource
  arguments:
    path: /tmp/my-socket.sock
```

## Splitters

| Splitter | Cuts the stream |
| --- | --- |
| `SplitByLine` | On a line delimiter, `\n` unless told otherwise. |
| `SplitByRegex` | On a regular expression match. |
| `SplitByDelay` | On a pause, grouping whatever arrived inside the window. |
| `SplitByChunk` | Not at all, each received chunk is one message. |
| `Unsplit` | Not at all, the whole buffer drains as one message. |

`SplitByDelay` is the one to reach for with an instrument that answers in several packets and marks no boundary.

```yaml
splitter:
  class: ceres.connection.SplitByRegex
  arguments:
    pattern: '\r\n'
```

## Connection Options

Every option below is an entry under `arguments`.

| Option | Default | Meaning |
| --- | --- | --- |
| `source` | required | The transport. |
| `splitter` | none | Where to cut the stream. Unsplit when omitted. |
| `suffix` | none | Appended to outgoing messages. |
| `buffer-read-size` | `1024` | Bytes read from the transport at a time. |
| `buffer-size` | `16384` | Buffer ceiling before an overflow is declared. |
| `buffer-drop` | `1024` | Bytes discarded when the buffer overflows. |
| `connect-timeout` | none | Gives up on a connection attempt after this long. |
| `receive-timeout` | none | Declares the link dead after this long without data. |
| `reconnect-schedule` | | When to retry after a drop. |

A schedule is written as a bare duration, a bare crontab expression, or a mapping naming its type.

```yaml
reconnect-schedule: 5s

reconnect-schedule: "*/5 * * * *"

reconnect-schedule:
  type: interval
  interval: 5s
  multiplier: 2
  max: 5m
```

The mapping form is what buys backoff. [Configuration](reference/configuration.md#intervalschedule) lists every key each schedule type takes.

Durations and sizes are written the way they read, `5s`, `10m`, `1MB`, `100KB`.

## Sending

```python
connection = self.system.connections.get("primary")
await connection.send(b"COMMAND\n")
```

`get` returns `None` when no connection has that name, so there is nothing to catch and nothing to subscript. A configured `suffix` is appended for you unless you pass `suffixed=False`.

## Reacting To Messages

```python
from ceres import Component, Connection, Ref, listener
from ceres.event import MessageReceivedEvent


class Driver(Component):
    connection: Ref[Connection]

    @listener(reference="connection")
    async def on_message(self, event: MessageReceivedEvent) -> None:
        self.system.log.info(f"Received {len(event.message.data)} bytes")
```

See [Components](components.md#event-listeners) for the other ways a listener can be pointed at events.

## Connectivity

A connection is `DISCONNECTED`, `CONNECTING`, or `CONNECTED`.

```python
connectivity = self.system.connections.get("primary").connectivity
```

Transitions emit `ConnectedEvent`, `DisconnectedEvent`, and `ConnectionLostEvent`, so a component can react rather than poll.

## Sieves

A sieve turns messages into structured _particles_. The method form is the one to reach for first, taking each message from a connection and returning a particle, or `None` to skip it.

```python
from ceres import Bound, Component, Connection, Message, SplitByLine, sieve


class Driver(Component):
    connection: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
    )

    @sieve(connection)
    async def parse(self, message: Message) -> SensorParticle | None:
        ...
```

`@sieve` also takes `stored`, `retries`, `retry_delay`, and message filters like `prefix`, `suffix`, and `contains`, so a component with several message shapes can route each to its own method.

A sieve can instead name a class in `ceres.yaml`.

```yaml
sieves:
  - name: parser
    type: class
    class: my_project.MySieve
    stored: true
    retries: 3
    retry-delay: 5s
```

### Particles

| Base class | For |
| --- | --- |
| `RegexParticle` | Text matched by a pattern. |
| `GroupedRegexParticle` | Capture groups mapped straight onto fields. |
| `BinaryParticle` | Fixed-layout binary frames. |
| `BinaryRegexParticle` | A binary frame located by a pattern. |

Stored particles are queryable from the CLI and the API. [Writing a Driver](writing-a-driver.md) puts a connection, a sieve, and a particle together on a real instrument.

### Declaring Particles For Charts

A component's `__particles__` class property lists the particle types it can emit. The console's chart and value pickers read it to offer types and fields without a live sample to inspect. Only particle classes with a literal `type` discriminator appear in the pickers.

By default, `__particles__` is derived from `@sieve`-decorated method return annotations, so a driver that already declares its particles through a sieve needs no further action. Assign a literal tuple to declare particle types a sieve does not name, for example when a component emits particles outside a sieve.

```python
class Driver(Component):
    __particles__ = (SensorParticle, OtherParticle)
```

Annotate a data field with `Unit()` to record the unit its values are measured in. The unit is published in the field's JSON schema, and the pickers show it beside the field's type.

```python
class SensorData(ParticleData):
    temperature: Annotated[float, Unit("degC")]
```
