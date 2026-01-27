from __future__ import annotations

import asyncio
import traceback
from datetime import timedelta
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Self,
    TypedDict,
    Unpack,
    cast,
    override,
)

from pydantic import ByteSize, Field, TypeAdapter, model_validator

from ceres._internal.manager import BaseComponentTaskManager
from ceres.address import Address
from ceres.channel import Channel
from ceres.component import BoundField, BoundFieldArgs
from ceres.connection.buffer import Buffer as Buffer
from ceres.connection.buffer import Chunk as Chunk
from ceres.connection.source import ConnectFailed as ConnectFailed
from ceres.connection.source import ConnectTimeout as ConnectTimeout
from ceres.connection.source import Source as Source
from ceres.connection.source import TCPSource as TCPSource
from ceres.connection.source import UNIXSocketSource as UNIXSocketSource
from ceres.connection.splitter import SplitByChunk as SplitByChunk
from ceres.connection.splitter import SplitByDelay as SplitByDelay
from ceres.connection.splitter import SplitByLine as SplitByLine
from ceres.connection.splitter import SplitByRegex as SplitByRegex
from ceres.connection.splitter import Splitter as Splitter
from ceres.connection.splitter import Unsplit as Unsplit
from ceres.connectivity import Connectivity
from ceres.data import (
    ImmutableDataObject,
    Name,
    PositiveTimeDelta,
    ToBytes,
    ValidatedDataclass,
    WithDefaults,
    to_bytes,
)
from ceres.event import (
    BufferOverflowEvent,
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectingEvent,
    ConnectionAddedEvent,
    ConnectionLostEvent,
    ConnectionRemovedEvent,
    ConnectionStartedEvent,
    ConnectionStoppedEvent,
    ConnectTimeoutEvent,
    DisconnectedEvent,
    DisconnectingEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    ReceiveTimeoutEvent,
    ReconnectScheduledEvent,
)
from ceres.loaded import Loaded
from ceres.message import BoundMessageManager, Message, MessageContent, MessageDirection
from ceres.schedule import IntervalSchedule, Schedule
from ceres.tasklet import Tasklet
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.component import ComponentSystem


class ConnectionException(Exception):
    pass


class ConnectionInactive(ConnectionException):
    pass


class ConnectionLost(ConnectionException):
    pass


class Buffering(ImmutableDataObject):
    read: ByteSize = Field(default=TypeAdapter(ByteSize).validate_python("1 KB"), gt=0)
    limit: ByteSize = Field(default=TypeAdapter(ByteSize).validate_python("100 KB"), gt=0)
    drop: ByteSize = Field(default=TypeAdapter(ByteSize).validate_python("10 KB"), gt=0)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.read > self.limit:
            raise ValueError(f"`read` ({self.read}) cannot be greater than `limit` ({self.limit})")
        if self.drop > self.limit:
            raise ValueError(f"`drop` ({self.drop}) cannot be greater than `limit` ({self.limit})")

        return self


class ConnectionDefaults(TypedDict, total=False):
    name: Name
    source: Loaded[Source]
    splitter: Loaded[Splitter] | None
    suffix: bytes | None
    buffering: Buffering

    connect_timeout: PositiveTimeDelta | float | str | None
    receive_timeout: PositiveTimeDelta | float | str | None
    reconnect_schedule: Schedule | str | None


class ConnectionFieldArgs(BoundFieldArgs, ConnectionDefaults, total=False):
    defaults: ConnectionDefaults | None


class ConnectionField[T: Connection | None](BoundField[T]):
    __slots__ = ()

    def __init__(
        self,
        default: Any = ...,
        **kwargs: Unpack[ConnectionFieldArgs],
    ):
        defaults: ConnectionDefaults | None = kwargs.get("defaults")
        if defaults is not None:
            kwargs["defaults"] = defaults = {**defaults}

        for field in Connection.__pydantic_fields__:
            if field in kwargs:
                assigned = kwargs.pop(field)  # type: ignore
                if defaults is None:
                    defaults = {}

                defaults[field] = assigned

        if defaults:
            kwargs["defaults"] = defaults

        super().__init__(default, **cast("ConnectionFieldArgs", kwargs))


class Connection(ValidatedDataclass, Tasklet):
    name: Name | None = None
    source: Loaded[Source]
    splitter: Loaded[Splitter] | None = None
    suffix: MessageContent | None = None

    buffering: Annotated[Buffering, WithDefaults(Buffering())] = Field(default_factory=Buffering)
    connect_timeout: PositiveTimeDelta | None = None
    receive_timeout: PositiveTimeDelta | None = None
    reconnect_schedule: Schedule | None = Field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )

    Field: ClassVar[type[ConnectionField]] = ConnectionField
    Defaults: ClassVar[type[ConnectionDefaults]] = ConnectionDefaults

    @override
    def __post_init__(self) -> None:
        self.__connectivity = Connectivity.DISCONNECTED
        self.__buffer = Buffer()
        self.__system: ComponentSystem | None = None
        self.__channel: Channel[Message] = Channel()

    @property
    def label(self) -> str:
        return self.source.label

    @property
    def system(self) -> ComponentSystem:
        from ceres.component import Component

        if self.__system is None:
            self.__system = Component().system

        return self.__system

    @system.setter
    def system(self, system: ComponentSystem | None) -> None:
        self.__system = system

    @property
    def buffer(self) -> bytes:
        return bytes(self.__buffer)

    @property
    def connectivity(self) -> Connectivity:
        return self.__connectivity

    @property
    def connected(self) -> bool:
        return self.__connectivity == Connectivity.CONNECTED

    @property
    def messages(self) -> BoundMessageManager:
        return self.system.messages

    async def connect(self) -> bool:
        if self.__connectivity == Connectivity.CONNECTED:
            return True

        self.system.events.emit(ConnectingEvent, connection=self.name)

        self.__connectivity = Connectivity.CONNECTING

        error: str | None = None

        try:
            connect_timeout = self.connect_timeout
            try:
                async with asyncio.timeout(
                    connect_timeout.total_seconds() if connect_timeout is not None else None
                ):
                    connected = await self.source.connect()
            except TimeoutError:
                if connect_timeout is not None:
                    self.system.events.emit(
                        ConnectTimeoutEvent,
                        connection=self.name,
                        timeout=connect_timeout,
                    )
                connected = False
        except Exception as exception:
            connected = False
            if text := str(exception).strip():
                error = text

        if connected:
            self.__connectivity = Connectivity.CONNECTED
            self.system.events.emit(ConnectedEvent, connection=self.name)
        else:
            self.__connectivity = Connectivity.DISCONNECTED
            self.system.events.emit(ConnectFailedEvent, connection=self.name, message=error)

        return self.connected

    async def send(self, data: ToBytes) -> Message:
        """
        Send raw bytes through the connection, returning the sent message if successful.

        Note, there is no guarantee the returned message is actually recieved on the remote end,
        only that the message was transmitted.
        """
        if not self.connected:
            raise ConnectionInactive()

        data = to_bytes(data, "latin-1")
        if self.suffix and not data.endswith(self.suffix):
            data += self.suffix

        try:
            sent = await self.source.send(data)
        except Exception:
            sent = None

        if sent is None and self.connected:
            self.system.events.emit(ConnectionLostEvent, connection=self.name)
            await self.disconnect()
            raise ConnectionLost()

        message = Message(
            address=Address.ROOT if self.system is None else self.system.address,
            connection=self.name,
            direction=Message.Direction.SEND,
            content=data,
        )

        self.system.store(message)
        self.__channel.put(message)
        self.system.events.emit(MessageSentEvent, message=message)

        return message

    async def disconnect(self) -> None:
        if self.__connectivity == Connectivity.DISCONNECTED:
            return

        self.system.events.emit(DisconnectingEvent, connection=self.name)

        try:
            await self.source.disconnect()
        finally:
            self.__buffer.clear()
            self.__connectivity = Connectivity.DISCONNECTED
            self.system.events.emit(DisconnectedEvent, connection=self.name)

    @override
    async def __run__(self) -> None:
        self.system.events.emit(ConnectionStartedEvent, connection=self.name)

        initialized = False

        try:
            while True:
                reconnect_trigger = (
                    self.reconnect_schedule.as_trigger()
                    if self.reconnect_schedule is not None
                    else None
                )

                while True:
                    if initialized:
                        if reconnect_trigger is None:
                            break

                        next = reconnect_trigger.get_next_fire_time()
                        if next is None:
                            break

                        delay = next - utc()

                        self.system.events.emit(
                            ReconnectScheduledEvent,
                            connection=self.name,
                            delay=delay,
                        )

                        await asyncio.sleep(delay.total_seconds())

                    # Yield to event loop.
                    await asyncio.sleep(0)

                    connected = await self.connect()
                    initialized = True
                    if connected:
                        break

                while self.connected:
                    received: bytes | None = None

                    try:
                        timeout = self.receive_timeout
                        try:
                            async with asyncio.timeout(
                                timeout.total_seconds() if timeout is not None else None
                            ):
                                received = await self.source.receive(self.buffering.read)
                        except TimeoutError:
                            if timeout is not None:
                                self.system.events.emit(
                                    ReceiveTimeoutEvent,
                                    connection=self.name,
                                    timeout=timeout,
                                )
                            received = None
                    except Exception:
                        self.system.log.error(traceback.format_exc())

                        received = None

                    # Yield to event loop.
                    await asyncio.sleep(0)

                    # If `receive` returns `None`, an empty `bytes`, or throws an exception, the
                    # connection is considered lost.
                    if not received:
                        if self.connected:
                            self.system.events.emit(ConnectionLostEvent)

                            await self.disconnect()

                        break

                    # Keep local reference to the buffer for performance.
                    buffer = self.__buffer
                    # Append received data to the buffer.
                    buffer.push(received, utc())

                    # Drop data from the buffer if it exceeds the buffer size limit.
                    dropped = buffer.pop_to_size(self.buffering.limit, self.buffering.drop)
                    if dropped is not None:
                        self.system.events.emit(
                            BufferOverflowEvent,
                            size=ByteSize(buffer.size),
                            limit=self.buffering.limit,
                            dropped=ByteSize(len(dropped.data)),
                        )

                    address = Address.ROOT if self.system is None else self.system.address
                    for chunk in buffer.drain(self.splitter, linearize=True):
                        message = Message(
                            address=address,
                            connection=self.name,
                            timestamp=chunk.timestamp,
                            direction=MessageDirection.RECEIVE,
                            content=chunk.data,
                        )

                        self.system.store(message)
                        self.__channel.put(message)
                        self.system.events.emit(MessageReceivedEvent, message=message)
        finally:
            await self.disconnect()
            self.system.events.emit(ConnectionStoppedEvent, connection=self.name)

    @override
    async def __stop__(self) -> None:
        await self.disconnect()


class ComponentConnectionManager(BaseComponentTaskManager[Connection]):
    @override
    def add(self, connection: Connection) -> None:
        connection.system = self.__system__
        super().add(connection)
        if connection.name is not None:
            self.__system__.events.emit(ConnectionAddedEvent, connection=connection.name)

    @override
    async def remove(self, name: Name) -> Connection | None:
        connection = await super().remove(name)
        if connection is not None:
            self.__system__.events.emit(ConnectionRemovedEvent, connection=name)
            connection.system = None

        return connection

    @override
    async def process(self, connection: Connection) -> None:
        await connection.run()
