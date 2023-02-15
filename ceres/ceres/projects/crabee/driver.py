import asyncio
import traceback
from datetime import datetime, timedelta
from typing import AsyncIterable

from pydantic import Field
from typing_extensions import Self

from ... import (
    Alert,
    AlertLevel,
    Component,
    Connection,
    ImmutableDataObject,
    Message,
    MessageOrder,
    MessageQuery,
    ParseException,
    Parser,
    Stream,
    display,
    on,
    routine,
    spawn,
    subscription,
    utc,
)
from ...console import ChartDisplay, ConsoleColor, StateDisplay, ValueDisplay
from ...events import ConnectFailedEvent, ConnectionLostEvent, MessageReceivedEvent
from ...layout import Layout, LayoutColumn, LayoutDisplay, LayoutRow


class DataMessage(ImmutableDataObject):
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
    def parse(cls, source: Message) -> Self:
        parser = Parser(source.content)

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
            source=source,
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


class CrabeeDriver(Component):
    class Parameters(Component.Parameters):
        checks: Checks = Field(default_factory=Checks)

    class References(Component.References):
        connection: Connection

    parameters: Parameters
    references: References

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__last_data_message_received: DataMessage | None = None
        self.__data_message_stream: Stream[DataMessage] = Stream()

    @routine
    async def __fetch_last_data_message(self) -> None:
        if messages := await self.environment.get_messages(
            MessageQuery(
                source=self.references.connection.address,
                order=MessageOrder.NEW_TO_OLD,
                limit=1,
            )
        ):
            try:
                self.__last_data_message_received = DataMessage.parse(messages[0])
            except ParseException:
                pass

    @on(ConnectionLostEvent, "connection")
    def __on_connection_lost(self, event: ConnectionLostEvent) -> None:
        self.emit_alert(
            Alert(
                level=AlertLevel.ERROR,
                code="connection/connection-lost",
            )
        )

    @on(ConnectFailedEvent, "connection")
    def __on_connect_failed(self, event: ConnectFailedEvent) -> None:
        self.emit_alert(
            Alert(
                level=AlertLevel.ERROR,
                code="connection/connect-failed",
            )
        )

    def __check_data_message(self, message: DataMessage) -> None:
        for name in self.parameters.checks.__fields__.keys():
            validator = getattr(self.parameters.checks, name, None)
            if not isinstance(validator, Check):
                continue

            value: int | float | bool | None = getattr(message, name, None)
            if value is None:
                continue

            if (validator.min is not None and value < validator.min) or (
                validator.max is not None and value > validator.max
            ):
                self.emit_alert(
                    Alert(
                        level=AlertLevel.ERROR,
                        code="data/range-exceeded",
                        info={
                            "field": name,
                            "value": value,
                            "range": {
                                "min": validator.min,
                                "max": validator.max,
                            },
                        },
                    )
                )

    @on(MessageReceivedEvent, "connection")
    def __on_message_received(self, event: MessageReceivedEvent) -> None:
        try:
            message = DataMessage.parse(event.message)
            self.__data_message_stream.put(message)
            self.__last_data_message_received = message
            self.logger.info(message)
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

            exists = self.paths.data.exists(file)
            with self.paths.data.open(file, "a") as stream:
                if not exists:
                    stream.write(",".join(info.keys()))
                    stream.write("\n")

                stream.write(",".join(str(value) for value in info.values()))
                stream.write("\n")

        except ParseException:
            self.emit_alert(
                Alert(
                    level=AlertLevel.ERROR,
                    code="data/unparseable-message",
                )
            )
            traceback.print_exc()
            return

    @subscription("data-messages")
    async def subscribe_data_messages(self) -> AsyncIterable[DataMessage]:
        if self.__last_data_message_received:
            yield self.__last_data_message_received
        async for message in self.__data_message_stream:
            yield message

    @classmethod
    def get_layout(cls) -> Layout:
        result = Layout(
            LayoutColumn(
                [
                    LayoutRow(
                        [
                            LayoutDisplay("temperature-1"),
                            LayoutDisplay("temperature-2"),
                            LayoutDisplay("temperature-3"),
                        ]
                    ),
                    LayoutRow(
                        [
                            LayoutDisplay("pressure"),
                            LayoutDisplay("pitch"),
                            LayoutDisplay("roll"),
                        ],
                    ),
                    LayoutRow(
                        [
                            LayoutDisplay("humidity"),
                            LayoutDisplay("leak-1"),
                            LayoutDisplay("leak-1"),
                        ],
                    ),
                    LayoutDisplay("temperature-history"),
                    LayoutDisplay("pressure-history"),
                    LayoutDisplay("humidity-history"),
                    LayoutDisplay("incline-history"),
                ]
            )
        )

        return result

    @display("temperature-1")
    async def display_temperature_1(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.temperature_1, unit="°C")

    @display("temperature-2")
    async def display_temperature_2(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.temperature_2, unit="°C")

    @display("temperature-3")
    async def display_temperature_3(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.temperature_3, unit="°C")

    @display("pressure")
    async def display_pressure(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.pressure, unit="mbars")

    @display("humidity")
    async def display_humidity(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.humidity, unit="%")

    @display("pitch")
    async def display_pitch(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.pitch, unit="°")

    @display("roll")
    async def display_roll(self) -> AsyncIterable[ValueDisplay]:
        async for message in self.subscribe_data_messages():
            yield ValueDisplay(value=message.roll, unit="°")

    @display("leak-1")
    async def display_leak_1(self) -> AsyncIterable[StateDisplay]:
        async for message in self.subscribe_data_messages():
            yield self.__display_leak(message.leak_1)

    @display("leak-2")
    async def display_leak_2(self) -> AsyncIterable[StateDisplay]:
        async for message in self.subscribe_data_messages():
            yield self.__display_leak(message.leak_2)

    @display("temperature-history")
    async def display_temperature_history(self) -> AsyncIterable[ChartDisplay]:
        while True:
            messages = await self.__get_data_message_history(cutoff=utc() - timedelta(hours=1))

            yield ChartDisplay(
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

    @display("pressure-history")
    async def display_pressure_history(self) -> AsyncIterable[ChartDisplay]:
        while True:
            messages = await self.__get_data_message_history(cutoff=utc() - timedelta(hours=1))

            yield ChartDisplay(
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

    @display("humidity-history")
    async def display_humidity_history(self) -> AsyncIterable[ChartDisplay]:
        while True:
            messages = await self.__get_data_message_history(cutoff=utc() - timedelta(hours=1))

            yield ChartDisplay(
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

    @display("incline-history")
    async def display_incline_history(self) -> AsyncIterable[ChartDisplay]:
        while True:
            messages = await self.__get_data_message_history(cutoff=utc() - timedelta(hours=1))

            yield ChartDisplay(
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

    async def __get_data_message_history(self, *, cutoff: datetime) -> list[DataMessage]:
        parsed: list[DataMessage] = []
        messages = reversed(
            await self.environment.get_messages(
                MessageQuery(
                    after=cutoff,
                    order=MessageOrder.NEW_TO_OLD,
                )
            )
        )

        def parse() -> None:
            for message in messages:
                try:
                    parsed.append(DataMessage.parse(message))
                except ParseException:
                    continue

        await spawn(parse)
        return parsed

    def __display_leak(self, leak: bool) -> StateDisplay:
        return StateDisplay(
            value=leak,
            options=[
                StateDisplay.Option(
                    value=False,
                    label="None",
                    color=ConsoleColor.POSITIVE,
                    description="No leak is currently being detected.",
                ),
                StateDisplay.Option(
                    value=True,
                    label="Leaking",
                    color=ConsoleColor.NEGATIVE,
                    description="A leak has been detected and is ongoing.",
                ),
            ],
        )
