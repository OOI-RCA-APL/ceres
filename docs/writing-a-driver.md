# Writing an Instrument Driver

This guide walks through building a complete instrument driver that connects to a sensor over TCP, parses incoming data into structured records, and stores them in the database.

## The Problem

You have a sensor that sends readings over a TCP connection. Each reading is a line of text like:

```
Temperature: 23.5, Pressure: 101.3, Humidity: 45.2
```

You want to connect to the sensor, parse each line into structured data, and store it for later analysis.

## Project Setup

```sh
mkdir sensor-driver && cd sensor-driver
uv init
uv add ceres --index https://ooi-rca-apl.github.io/ceres/simple/
source .venv/bin/activate
```

## Defining the Data Format

First, define the structure of a parsed reading using `ParticleData`. This is a Pydantic dataclass whose fields correspond to the values you want to extract.

```python
# sensor.py
from ceres import ParticleData
from ceres.data import Number


class SensorParticleData(ParticleData):
    temperature: Number
    pressure: Number
    humidity: Number
```

## Parsing with GroupedRegexParticle

Next, define a `GroupedRegexParticle` subclass that knows how to extract `SensorParticleData` from raw bytes. The `regex` class attribute is a compiled regex pattern with named groups matching the `ParticleData` fields.

```python
from re import compile
from typing import Literal

from ceres import GroupedRegexParticle


class SensorParticle(GroupedRegexParticle[SensorParticleData]):
    type: Literal["sensor/data"] = "sensor/data"

    regex = compile(
        rb"Temperature:\s*?(?P<temperature>-?\d+\.\d+)[,\s]+?"
        rb"Pressure:\s*?(?P<pressure>\d+\.\d+)[,\s]+?"
        rb"Humidity:\s*?(?P<humidity>\d+\.\d+)[,\s]*?"
        rb"[\r\n]+"
    )
```

The `type` field is a discriminator string used to identify this particle type in the database and API.

Named capture groups in the regex (`?P<temperature>`, etc.) are automatically matched to the `ParticleData` fields and coerced to the declared types.

## Writing the Driver Component

The driver is a `Component` with a connection and a sieve that parses messages into particles.

```python
from ceres import Bound, Component, Connection, Message, ParseFailed, SplitByLine, sieve


class SensorDriver(Component):
    connection: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
        suffix=b"\n",
        receive_timeout=30,
    )

    @sieve(connection)
    async def sieve(self, message: Message) -> SensorParticle | None:
        try:
            return SensorParticle.from_message(message)
        except ParseFailed as exception:
            self.system.log.warning(exception)
            return None
```

There is a lot happening here, so let's break it down:

- `Connection.Field(...)` declares a connection with default settings. The connection's transport source (TCP host/port) is configured in `ceres.yaml`, not in code, so the same driver class can be reused for different instruments.
- `SplitByLine()` tells the connection to split incoming bytes on newlines.
- `suffix=b"\n"` appends a newline to outgoing messages.
- `receive_timeout=30` disconnects if no data is received for 30 seconds.
- The `@sieve(connection)` decorator registers the method as a data parser for the named connection. Each message received on that connection is passed through this method.
- Returning a particle stores it in the database. Returning `None` skips the message.
- `ParseFailed` is raised by `from_message()` when the regex does not match.

## Configuration

```yaml
# ceres.yaml
database:
  type: sqlite
  path: ./local/database.sqlite

server:
  port: 8080

logging:
  output: info
  events: true

components:
  - name: driver
    class: sensor.SensorDriver
    arguments:
      connection:
        source:
          class: ceres.connection.TCPSource
          arguments:
            host: localhost
            port: 4000
```

The connection's TCP source is configured in YAML. This separates the driver logic (how to parse data) from the deployment details (where the instrument is). You can point the same driver at different hosts by changing the config.

## Writing a Simulator

For testing, you can write a simulator that mimics the sensor. Ceres provides `TCPServer` for this.

```python
from datetime import timedelta
from typing import override

from ceres import TCPClient, TCPServer
from ceres.concurrency import sleep
from ceres.data import TimeDelta


class SensorSimulator(TCPServer):
    interval: TimeDelta = timedelta(seconds=1)

    @override
    async def handle(self, client: TCPClient) -> None:
        import random

        temperature = 20.0
        pressure = 1000.0
        humidity = 50.0

        while True:
            temperature = round(temperature + random.uniform(-1, 1), 1)
            pressure = round(pressure + random.uniform(-1, 1) + 1000, 1)
            humidity = round(humidity + random.uniform(-1, 1), 1)
            data = f"Temperature: {temperature}, Pressure: {pressure}, Humidity: {humidity}\n"
            await client.send(data.encode())
            await sleep(self.interval)
```

Add it to `ceres.yaml`:

```yaml
components:
  - name: driver
    class: sensor.SensorDriver
    arguments:
      connection:
        source:
          class: ceres.connection.TCPSource
          arguments:
            host: localhost
            port: 4000
  - name: simulator
    class: sensor.SensorSimulator
    arguments:
      port: 4000
      interval: 1s
```

## Running

```sh
ceres run all
```

The simulator starts serving on port 4000, the driver connects and begins parsing data. You should see log output like:

```
[2026-05-01 12:00:00.100] [INFO] [@driver] [event]
{"address":"@driver","type":"started","level":"info",...}
[2026-05-01 12:00:00.101] [INFO] [@simulator] [event]
{"address":"@simulator","type":"started","level":"info",...}
[2026-05-01 12:00:00.102] [INFO] [@driver] [event]
{"address":"@driver","type":"connected","level":"info","connection":"connection",...}
```

Open the web console at [http://localhost:8080](http://localhost:8080) to view parsed particles, raw messages, and logs.

## Querying Parsed Data

From the CLI:

```sh
ceres particles select                    # Show all parsed particles.
ceres particles select --output data.csv  # Export as CSV.
ceres particles follow                    # Stream new particles in real-time.
```

From within a component:

```python
latest = await self.system.particles.where(order="timestamp:desc").limit(10)
```

## Binary Protocols

For instruments that send binary data instead of text, use `BinaryParticle` or `BinaryRegexParticle` instead of `RegexParticle`. These use `struct.unpack()` to extract fields from fixed-layout binary frames.

## Production Patterns

In production deployments like [ceres-rca](https://github.com/OOI-RCA-APL/ceres-rca), drivers typically:

- Write raw data to daily log files organized by date.
- Validate instrument timestamps against system time.
- Emit alerts on connection loss or timestamp drift.
- Use listeners to react to message and particle events for post-processing.
- Configure pruners to clean up old records on a schedule.

See the [ceres-rca](https://github.com/OOI-RCA-APL/ceres-rca) repository for real-world examples of oceanographic instrument drivers.

## Complete Source

The complete sensor example is available in the Ceres repository at `examples/sensor/`.
