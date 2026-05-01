"""Minimal sensor driver example.

This is the simplest possible Ceres driver: one connection, one particle type,
one sieve. It connects to a TCP sensor, parses each line into structured data,
and stores it in the database. See the writing-a-driver doc for a walkthrough.
"""

from datetime import timedelta
from re import compile
from typing import Literal, override

from ceres import (
    Bound,
    Component,
    Connection,
    GroupedRegexParticle,
    Message,
    ParseFailed,
    ParticleData,
    SplitByLine,
    TCPClient,
    TCPServer,
    sieve,
)
from ceres.concurrency import sleep
from ceres.data import Number, TimeDelta


# ParticleData defines the structured fields parsed from each sensor reading.
# The Number type accepts any numeric value and stores it as a Decimal.
class SensorParticleData(ParticleData):
    temperature: Number  # Degrees Celsius
    pressure: Number  # Kilopascals
    humidity: Number  # Percentage


# GroupedRegexParticle maps named capture groups in the regex directly to
# ParticleData fields. The type literal identifies this particle in the
# database and API.
class SensorParticle(GroupedRegexParticle[SensorParticleData]):
    type: Literal["sensor/data"] = "sensor/data"

    # Matches lines like: Temperature: 23.5, Pressure: 101.3, Humidity: 45.2
    regex = compile(
        rb"Temperature:\s*?(?P<temperature>-?\d+\.\d+)[,\s]+?"
        rb"Pressure:\s*?(?P<pressure>\d+\.\d+)[,\s]+?"
        rb"Humidity:\s*?(?P<humidity>\d+\.\d+)[,\s]*?"
        rb"[\r\n]+"
    )


class SensorDriver(Component):
    # Connection.Field declares a managed connection. The transport source
    # (host/port) is configured in ceres.yaml, not in code.
    # SplitByLine splits incoming bytes on newlines into discrete messages.
    # suffix appends a newline to outgoing sends.
    # receive_timeout disconnects if no data arrives within 30 seconds.
    connection: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
        suffix=b"\n",
        receive_timeout=30,
    )

    # @sieve(connection) registers this method as a parser for messages from
    # the named connection. Returning a particle stores it in the database.
    # Returning None skips the message.
    @sieve(connection)
    async def sieve(self, message: Message) -> SensorParticle | None:
        try:
            return SensorParticle.from_message(message)
        except ParseFailed as exception:
            self.system.log.warning(exception)
            return None


class SensorSimulator(TCPServer):
    """TCP server that sends simulated sensor readings at a fixed interval."""

    interval: TimeDelta = timedelta(seconds=1)

    @override
    async def handle(self, client: TCPClient) -> None:
        import random

        temperature = 20
        pressure = 1000
        humidity = 50

        while True:
            temperature = round(temperature + random.uniform(-1, 1), 1)
            pressure = round(pressure + random.uniform(-1, 1) + 1000, 1)
            humidity = round(humidity + random.uniform(-1, 1), 1)
            data = f"Temperature: {temperature}, Pressure: {pressure}, Humidity: {humidity}\n"
            await client.send(data.encode())
            await sleep(self.interval)
