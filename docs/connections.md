# Connections

Connections provide managed, persistent byte streams between components and remote instruments or services. They handle connecting, disconnecting, reconnecting, buffering, and splitting incoming data into discrete messages.

## Overview

A connection wraps a transport _source_ (TCP socket, Unix socket, etc.) and a _splitter_ strategy that determines how the raw byte stream is divided into messages. Connections run as background tasks within their owning component, automatically reconnecting on failure.

Connections can be declared in two ways: in the component's `ceres.yaml` configuration, or statically in the component class itself.

## Configuring connections in YAML

The most common approach is to declare connections in `ceres.yaml`.

```yaml
components:
  - name: driver
    class: my_project.Driver
    connections:
      - name: primary
        source:
          class: ceres.connection.TCPSource
          arguments:
            host: 10.180.80.170
            port: 2101
        splitter:
          class: ceres.connection.SplitByLine
```

This creates a connection named `primary` on the `@driver` component. The connection connects to the specified host and port, splits incoming bytes on newlines, and stores each chunk as a `Message` in the database.

### Connection as a field argument

Connections can also be passed as component arguments. This is useful when the component declares a `Connection` field.

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

## Sources

Sources are transport adapters that establish the underlying byte stream.

### `TCPSource`

Connect to a remote host over TCP.

```yaml
source:
  class: ceres.connection.TCPSource
  arguments:
    host: 10.180.80.170
    port: 2101
```

### `UNIXSocketSource`

Connect to a Unix domain socket.

```yaml
source:
  class: ceres.connection.UNIXSocketSource
  arguments:
    path: /tmp/my-socket.sock
```

## Splitters

Splitters determine how the raw byte stream is divided into discrete messages. Each resulting chunk becomes a `Message` record.

### `SplitByLine`

Split on a line delimiter (default: `\n`).

```yaml
splitter:
  class: ceres.connection.SplitByLine
```

### `SplitByRegex`

Split on a regular expression match.

```yaml
splitter:
  class: ceres.connection.SplitByRegex
  arguments:
    pattern: '\r\n'
```

### `SplitByDelay`

Group bytes that arrive within a time window into a single message. Useful for instruments that send multi-part responses without a clear delimiter.

```yaml
splitter:
  class: ceres.connection.SplitByDelay
  arguments:
    delay: 0.1
```

### `SplitByChunk`

Treat each received chunk as a separate message, with no reassembly.

```yaml
splitter:
  class: ceres.connection.SplitByChunk
```

### `Unsplit`

Do not split at all. Drain the entire buffer as a single message each time.

```yaml
splitter:
  class: ceres.connection.Unsplit
```

## Connection options

Full connection configuration options in `ceres.yaml`:

```yaml
connections:
  - name: primary
    source:
      class: ceres.connection.TCPSource
      arguments:
        host: localhost
        port: 4000
    splitter:
      class: ceres.connection.SplitByLine
    suffix: "\n"                        # Append to outgoing messages.
    buffer_size: 1MB                    # Max buffer size before overflow.
    buffer_drop: 100KB                  # Drop threshold on overflow.
    connect_timeout: 5s                 # Timeout for initial connection.
    receive_timeout: 10s                # Timeout waiting for data.
    reconnect_schedule: "interval: 5s"  # Schedule for reconnection attempts.
```

## Sending data

Components can send data through their connections.

```python
await self.system.connections["primary"].send(b"COMMAND\n")
```

If a `suffix` is configured on the connection, it is appended automatically unless `suffixed=False` is passed.

## Listening to messages

Use `@listener` with `reference` to react to messages from a connection. See [Components -- Event listeners](components.md#event-listeners).

```python
from ceres import Component, Connection, Ref, listener
from ceres.event import MessageReceivedEvent


class Driver(Component):
    connection: Ref[Connection]

    @listener(reference="connection")
    async def on__message(self, event: MessageReceivedEvent) -> None:
        raw = event.message.data
        self.log.info(f"Received {len(raw)} bytes")
```

## Connectivity state

Connections track their state as a `Connectivity` value: `DISCONNECTED`, `CONNECTING`, or `CONNECTED`. Components can check this at any time.

```python
connectivity = self.system.connections["primary"].connectivity
```

Connection state changes emit `ConnectedEvent`, `DisconnectedEvent`, and `ConnectionLostEvent`.

## Sieves

Sieves are data parsers that process messages from connections and produce structured _particles_. They can be configured in YAML or declared as methods on a component.

### Method sieves

The simplest approach is to use the `@sieve` decorator on a component method. The method receives each message from a named connection and returns a parsed particle (or `None` to skip).

```python
from ceres import Component, Connection, Ref, sieve
from ceres.particle import RegexParticle


class Driver(Component):
    connection: Ref[Connection]

    @sieve(connection="connection", stored=True)
    async def parse(self, message: Message) -> SensorParticle | None:
        ...
```

### YAML sieves

Sieves can also be configured in `ceres.yaml` using a sieve class.

```yaml
sieves:
  - name: parser
    type: class
    class: my_project.MySieve
    stored: true
    retries: 3
    retry_delay: 5s
```

### Particles

Particles are structured data records extracted from raw messages. Ceres provides several particle base classes for common patterns:

- `RegexParticle` -- Parse text messages with a regex pattern.
- `GroupedRegexParticle` -- Map regex capture groups directly to data fields.
- `BinaryParticle` -- Unpack fixed-layout binary data.

Parsed particles can be stored in the database (when `stored: true`) and queried later through the CLI or API.
