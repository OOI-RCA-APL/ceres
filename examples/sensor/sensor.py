from datetime import timedelta
from typing import Literal, override

from ceres import (
    Bound,
    Component,
    Connection,
    Message,
    ParseFailed,
    ParticleData,
    RegexParticle,
    SplitByLine,
    TCPClient,
    TCPServer,
    sieve,
)
from ceres.concurrency import sleep
from ceres.data import Number, TimeDelta


class SensorParticleData(ParticleData):
    temperature: Number  # Degrees Celsius
    pressure: Number  # Kilopascals
    humidity: Number  # Percentage


class SensorParticle(RegexParticle[SensorParticleData]):
    type: Literal["sensor/data"] = "sensor/data"

    __regex__ = (
        rb"Temperature:\s*?(?P<temperature>-?\d+\.\d+)[,\s]+?"
        rb"Pressure:\s*?(?P<pressure>\d+\.\d+)[,\s]+?"
        rb"Humidity:\s*?(?P<humidity>\d+\.\d+)[,\s]*?"
        rb"[\r\n]+"
    )
    """
    Matches sensor data in the following format.

    ```
    Temperature: 23.5, Pressure: 101.3, Humidity: 45.2
    Temperature: -5.0, Pressure: 99.8, Humidity: 30.0
    Temperature: 0.0, Pressure: 100.0, Humidity: 50.0
    ```
    """


class SensorDriver(Component):
    """
    Example sensor driver that reads temperature, pressure, and humidity data from a connection.

    See `SensorParticleData` for the expected data format.
    """

    connection: Bound[Connection] | None = Connection.Field(
        splitter=SplitByLine(),
        suffix=b"\n",
        receive_timeout=30,
    )

    @sieve(connection)
    async def sieve(self, message: Message) -> SensorParticle | None:
        try:
            return SensorParticle.parse(message)
        except ParseFailed as exception:
            self.system.log.warning(exception)
            return None


class SensorSimulator(TCPServer):
    """
    Simulated sensor server that sends periodic data.
    """

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
