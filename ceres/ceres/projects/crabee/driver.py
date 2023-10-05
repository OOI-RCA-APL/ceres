import asyncio
import traceback
from datetime import timedelta
from typing import AsyncIterable

from pydantic import Field
from typing_extensions import Self, override

from ceres import (
    Connection,
    ImmutableDataObject,
    Level,
    Message,
    MessageOrder,
    Parser,
    Ref,
    utc,
)
from ceres.component import on, query, routine
from ceres.data import DateTime, TimeDelta
from ceres.directory import Directory
from ceres.events import ConnectFailedEvent, ConnectionLostEvent, MessageReceivedEvent
from ceres.exceptions import ParseException
from ceres.roles.interface import Interface
from ceres.stream import WriteStream
from ceres.threading import spawn
from ceres.ui import Carousel, Chart, Column, Display, PaletteColor, Row, Sizing, State, Value


class CrabeeParticle(ImmutableDataObject):
    source: Message
    temperature_1: float
    temperature_2: float
    temperature_3: float

    pressure: float
    humidity: float

    pitch: float
    roll: float

    leak_1: bool
    leak_2: bool

    @classmethod
    def parse(cls, message: Message) -> Self:
        parser = Parser(message.content)

        parser.eat(b"Temp1=")
        temperature_1 = parser.eat_float()
        parser.try_eat_space()
        parser.eat(b"Temp2=")
        temperature_2 = parser.eat_float()
        parser.try_eat_space()
        parser.eat(b"Temp3=")
        temperature_3 = parser.eat_float()
        parser.try_eat_space()

        parser.eat(b"Pres=")
        pressure = parser.eat_float()
        parser.try_eat_space()
        parser.eat(b"Hum=")
        humidity = parser.eat_float()
        parser.try_eat_space()

        parser.eat(b"Pitch=")
        pitch = parser.eat_float()
        parser.try_eat_space()
        parser.eat(b"Roll=")
        roll = parser.eat_float()
        parser.try_eat_space()

        parser.eat(b"Leak1=")
        leak_1 = bool(parser.eat_int())
        parser.try_eat_space()
        parser.eat(b"Leak2=")
        leak_2 = bool(parser.eat_int())
        parser.try_eat_space()

        return cls(
            source=message,
            temperature_1=temperature_1,
            temperature_2=temperature_2,
            temperature_3=temperature_3,
            pressure=pressure,
            humidity=humidity,
            pitch=pitch,
            roll=roll,
            leak_1=leak_1,
            leak_2=leak_2,
        )


class Check(ImmutableDataObject):
    min: float | None = None
    max: float | None = None


class Checks(ImmutableDataObject):
    temperature_1: Check | None = None
    temperature_2: Check | None = None
    temperature_3: Check | None = None
    pressure: Check | None = None
    humidity: Check | None = None
    pitch: Check | None = None
    roll: Check | None = None
    leak_1: Check | None = None
    leak_2: Check | None = None


class CrabeeDriver(Interface):
    output: Directory
    connection: Ref[Connection]
    checks: Checks = Field(default_factory=Checks)

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__last_data_message_received: CrabeeParticle | None = None
        self.__data_message_stream: WriteStream[CrabeeParticle] = WriteStream()

    @routine
    async def routine__fetch_last_data_message(self) -> None:
        if messages := await self.connection.get_messages(
            order=MessageOrder.NEW_TO_OLD,
            limit=1,
        ):
            try:
                self.__last_data_message_received = CrabeeParticle.parse(messages[0])
            except ParseException:
                pass

    @on(reference="connection", event=ConnectionLostEvent)
    def on__connection_lost(self) -> None:
        self.alert(Level.ERROR, "connection/connection-lost")

    @on(reference="connection", event=ConnectFailedEvent)
    def on__connect_failed(self) -> None:
        self.alert(Level.ERROR, "connection/connect-failed")

    def __check_data_message(self, message: CrabeeParticle) -> None:
        for name in self.checks.model_fields.keys():
            validator = getattr(self.checks, name, None)
            if not isinstance(validator, Check):
                continue

            value: int | float | bool | None = getattr(message, name, None)
            if value is None:
                continue

            if (validator.min is not None and value < validator.min) or (
                validator.max is not None and value > validator.max
            ):
                self.alert(
                    Level.ERROR,
                    "data/range-exceeded",
                    {
                        "field": name,
                        "value": value,
                        "range": {
                            "min": validator.min,
                            "max": validator.max,
                        },
                    },
                )

    @on(reference="connection")
    def on__message_received(self, event: MessageReceivedEvent) -> None:
        try:
            message = CrabeeParticle.parse(event.message)
            self.__data_message_stream.put(message)
            self.__last_data_message_received = message
            self.__check_data_message(message)

            file = message.source.timestamp.strftime("%Y/%m/%y-%m-%d.csv")
            info = {
                "timestamp": message.source.timestamp.isoformat(),
                "temperature_1": message.temperature_1,
                "temperature_2": message.temperature_2,
                "temperature_3": message.temperature_3,
                "pressure": message.pressure,
                "humidity": message.humidity,
                "pitch": message.pitch,
                "roll": message.roll,
                "leak_1": int(message.leak_1),
                "leak_2": int(message.leak_2),
            }

            exists = self.output.exists(file)
            with self.output.open(file, "a") as stream:
                if not exists:
                    stream.write(",".join(info.keys()))
                    stream.write("\n")

                stream.write(",".join(str(value) for value in info.values()))
                stream.write("\n")

        except ParseException:
            self.alert(Level.ERROR, "data/unparseable-message")
            traceback.print_exc()
            return

    async def _get_data_messages(self) -> AsyncIterable[CrabeeParticle]:
        if self.__last_data_message_received:
            yield self.__last_data_message_received
        async for message in self.__data_message_stream:
            yield message

    @override
    @query
    async def render(self) -> Column:
        return Column(
            children=[
                Row(
                    sizing=Sizing.GROW,
                    children=[
                        Display(title="Temperature 1", source=self.render_temperature_1),
                        Display(title="Temperature 2", source=self.render_temperature_2),
                        Display(title="Temperature 3", source=self.render_temperature_3),
                    ],
                ),
                Row(
                    sizing=Sizing.GROW,
                    children=[
                        Display(title="Pressure", source=self.render_pressure),
                        Display(title="Pitch", source=self.render_pitch),
                        Display(title="Roll", source=self.render_roll),
                    ],
                ),
                Row(
                    sizing=Sizing.GROW,
                    children=[
                        Display(title="Humidity", source=self.render_humidity),
                        Display(title="Leak 1", source=self.render_leak_1),
                        Display(title="Leak 2", source=self.render_leak_2),
                    ],
                ),
                Carousel(
                    height=300,
                    children=[
                        Display(
                            title="Temperature History",
                            source=self.render_temperature_history,
                        ),
                        Display(title="Pressure History", source=self.render_pressure_history),
                        Display(title="Humidity History", source=self.render_humidity_history),
                        Display(title="Incline History", source=self.render_incline_history),
                    ],
                ),
            ]
        )

    @query
    async def render_temperature_1(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.temperature_1, unit="°C")

    @query
    async def render_temperature_2(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.temperature_2, unit="°C")

    @query
    async def render_temperature_3(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.temperature_3, unit="°C")

    @query
    async def render_pressure(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.pressure, unit="mbars")

    @query
    async def render_humidity(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.humidity, unit="%")

    @query
    async def render_pitch(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.pitch, unit="°")

    @query
    async def render_roll(self) -> AsyncIterable[Value]:
        async for message in self._get_data_messages():
            yield Value(value=message.roll, unit="°")

    @query
    async def render_leak_1(self) -> AsyncIterable[State]:
        async for message in self._get_data_messages():
            yield self.__display_leak(message.leak_1)

    @query
    async def render_leak_2(self) -> AsyncIterable[State]:
        async for message in self._get_data_messages():
            yield self.__display_leak(message.leak_2)

    @query
    async def render_temperature_history(
        self,
        start: DateTime | None = None,
        duration: TimeDelta = timedelta(hours=1),
    ) -> AsyncIterable[Chart]:
        while True:
            messages = await self.__get_particles(start, duration)

            yield Chart(
                value={
                    "legend": {"show": True},
                    "tooltip": {"trigger": "axis"},
                    "dataZoom": [{"type": "inside"}],
                    "xAxis": {
                        "name": "Time",
                        "type": "time",
                    },
                    "yAxis": {
                        "name": "Temperature (Degrees Celcius)",
                    },
                    "series": [
                        {
                            "name": "Temperature 1",
                            "data": [
                                [message.source.timestamp.isoformat(), message.temperature_1]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                        {
                            "name": "Temperature 2",
                            "data": [
                                [message.source.timestamp.isoformat(), message.temperature_2]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                        {
                            "name": "Temperature 3",
                            "data": [
                                [message.source.timestamp.isoformat(), message.temperature_3]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                    ],
                },
                height=250,
            )

            await asyncio.sleep(10)

    @query
    async def render_pressure_history(
        self,
        start: DateTime | None = None,
        duration: TimeDelta = timedelta(hours=1),
    ) -> AsyncIterable[Chart]:
        while True:
            messages = await self.__get_particles(start, duration)

            yield Chart(
                value={
                    "legend": {"show": True},
                    "tooltip": {"trigger": "axis"},
                    "dataZoom": [{"type": "inside"}],
                    "xAxis": {
                        "name": "Time",
                        "type": "time",
                    },
                    "yAxis": {
                        "name": "Pressure (Millibars)",
                    },
                    "series": [
                        {
                            "name": "Pressure",
                            "data": [
                                [message.source.timestamp.isoformat(), message.pressure]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                    ],
                },
                height=250,
            )

            await asyncio.sleep(10)

    @query
    async def render_humidity_history(
        self,
        start: DateTime | None = None,
        duration: TimeDelta = timedelta(hours=1),
    ) -> AsyncIterable[Chart]:
        while True:
            messages = await self.__get_particles(start, duration)

            yield Chart(
                value={
                    "legend": {"show": True},
                    "tooltip": {"trigger": "axis"},
                    "dataZoom": [{"type": "inside"}],
                    "xAxis": {
                        "name": "Time",
                        "type": "time",
                        "axisLabel": {
                            "hideOverlap": True,
                        },
                    },
                    "yAxis": {
                        "name": "%",
                    },
                    "series": [
                        {
                            "name": "Humidity",
                            "data": [
                                [message.source.timestamp.isoformat(), message.humidity]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                    ],
                },
                height=250,
            )

            await asyncio.sleep(10)

    @query
    async def render_incline_history(
        self,
        start: DateTime | None = None,
        duration: TimeDelta = timedelta(hours=1),
    ) -> AsyncIterable[Chart]:
        while True:
            messages = await self.__get_particles(start, duration)

            yield Chart(
                value={
                    "legend": {"show": True},
                    "tooltip": {"trigger": "axis"},
                    "dataZoom": [{"type": "inside"}],
                    "xAxis": {
                        "name": "Time",
                        "type": "time",
                    },
                    "yAxis": {
                        "name": "Angle (Degrees)",
                    },
                    "series": [
                        {
                            "name": "Pitch",
                            "data": [
                                [message.source.timestamp.isoformat(), message.pitch]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                        {
                            "name": "Roll",
                            "data": [
                                [message.source.timestamp.isoformat(), message.roll]
                                for message in messages
                            ],
                            "type": "line",
                            "showSymbol": False,
                        },
                    ],
                },
                height=250,
            )

            await asyncio.sleep(30)

    async def __get_particles(
        self,
        start: DateTime | None,
        duration: TimeDelta,
    ) -> list[CrabeeParticle]:
        now = utc()
        if start is None:
            start = now - duration

        end = start + duration

        particles: list[CrabeeParticle] = []
        messages = reversed(
            await self.connection.get_messages(
                after=start,
                before=end,
                order=MessageOrder.NEW_TO_OLD,
            )
        )

        def parse() -> None:
            for message in messages:
                try:
                    particles.append(CrabeeParticle.parse(message))
                except ParseException:
                    continue

        await spawn(parse)
        return particles

    def __display_leak(self, leak: bool) -> State:
        return State(
            value=leak,
            options=[
                State.Option(
                    value=False,
                    label="None",
                    color=PaletteColor.POSITIVE,
                    description="No leak is currently being detected.",
                ),
                State.Option(
                    value=True,
                    label="Leaking",
                    color=PaletteColor.NEGATIVE,
                    description="A leak has been detected and is ongoing.",
                ),
            ],
        )
