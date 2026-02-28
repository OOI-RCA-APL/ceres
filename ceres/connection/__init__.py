import asyncio
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Self,
    TypedDict,
    Unpack,
    cast,
    overload,
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
from ceres.data import DataObject, Name, PositiveTimeDelta, ToBytes, WithDefaults
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
from ceres.message import (
    BoundMessageManager,
    Message,
    MessageContent,
    MessageDirection,
    MessageFilter,
    MessageFilterArgs,
)
from ceres.schedule import IntervalSchedule, Schedule
from ceres.tasklet import Tasklet
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.component import ComponentSystem
else:
    ComponentSystem = object

__all__ = (
    "Connection",
    "ConnectionField",
    "ConnectionDefaults",
    # .source
    "ConnectionInactive",
    "ConnectionLost",
    "Source",
    "ConnectFailed",
    "ConnectTimeout",
    "TCPSource",
    "UNIXSocketSource",
    # .splitter
    "Splitter",
    "SplitByChunk",
    "SplitByDelay",
    "SplitByLine",
    "SplitByRegex",
    "Unsplit",
)


class ConnectionException(Exception):
    pass


class ConnectionInactive(ConnectionException):
    pass


class ConnectionLost(ConnectionException):
    pass


class Buffering(DataObject, slots=True):
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


class ConnectionField(BoundField["Connection"]):
    __slots__ = ()

    @dataclass(slots=True)
    class Marker(BoundField.Marker):
        pass

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
                assigned: Any = kwargs.pop(field)  # type: ignore
                if defaults is None:
                    defaults = {}

                defaults[field] = assigned

        if defaults:
            kwargs["defaults"] = defaults

        super().__init__(default, **cast("ConnectionFieldArgs", kwargs))


class Connection(DataObject, Tasklet, slots=True):
    name: Name | None = None
    source: Loaded[Source]
    splitter: Loaded[Splitter] | None = None
    suffix: MessageContent | None = None

    buffering: Annotated[Buffering, WithDefaults(Buffering())] = field(default_factory=Buffering)
    connect_timeout: PositiveTimeDelta | None = None
    receive_timeout: PositiveTimeDelta | None = None
    reconnect_schedule: Schedule | None = field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )

    _connectivity: Connectivity = field(init=False)
    _buffer: Buffer = field(init=False)
    _system: ComponentSystem | None = field(init=False)
    _channel: Channel[Message] = field(init=False)

    Field = ConnectionField
    Defaults = ConnectionDefaults

    def __post_init__(self) -> None:
        self._connectivity = Connectivity.DISCONNECTED
        self._buffer = Buffer()
        self._system = None
        self._channel = Channel()

    @property
    def label(self) -> str:
        return self.source.label

    @property
    def __system__(self) -> ComponentSystem:
        from ceres.component import Component

        if self._system is None:
            self._system = Component().system

        return self._system

    @__system__.setter
    def __system__(self, system: ComponentSystem | None) -> None:
        self._system = system

    @property
    def buffer(self) -> bytes:
        return bytes(self._buffer)

    @property
    def connectivity(self) -> Connectivity:
        return self._connectivity

    @property
    def connected(self) -> bool:
        return self._connectivity == Connectivity.CONNECTED

    @property
    def messages(self) -> BoundMessageManager:
        def filtering():
            if self.name is None:
                return MessageFilter(address=self.__system__.address)

            return MessageFilter(address=self.__system__.address, connection=self.name)

        return BoundMessageManager(self.__system__, filtering)

    async def connect(self) -> bool:
        if self._connectivity == Connectivity.CONNECTED:
            return True

        self.__system__.events.emit(ConnectingEvent, connection=self.name)

        self._connectivity = Connectivity.CONNECTING

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
                    self.__system__.events.emit(
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
            self._connectivity = Connectivity.CONNECTED
            self.__system__.events.emit(ConnectedEvent, connection=self.name)
        else:
            self._connectivity = Connectivity.DISCONNECTED
            self.__system__.events.emit(ConnectFailedEvent, connection=self.name, message=error)

        return self.connected

    async def send(self, data: ToBytes) -> Message:
        """
        Send raw bytes through the connection, returning the sent message if successful.

        Note, there is no guarantee the returned message is actually recieved on the remote end,
        only that the message was transmitted.
        """
        if not self.connected:
            raise ConnectionInactive()

        data = bytes(data)
        if self.suffix and not data.endswith(self.suffix):
            data += self.suffix

        try:
            sent = await self.source.send(data)
        except Exception:
            sent = None

        if sent is None and self.connected:
            self.__system__.events.emit(ConnectionLostEvent, connection=self.name)
            await self.disconnect()
            raise ConnectionLost()

        message = Message(
            address=Address.ROOT if self.__system__ is None else self.__system__.address,
            connection=self.name,
            direction=Message.Direction.SEND,
            content=data,
        )

        self.__system__.store(message)
        self._channel.put(message)
        self.__system__.events.emit(MessageSentEvent, message=message)

        return message

    @overload
    async def receive[T](
        self,
        *,
        where: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T],
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T: ...

    @overload
    async def receive(
        self,
        *,
        where: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: ... = ...,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message: ...

    async def receive[T](
        self,
        *,
        where: Callable[[Message], bool] | None = None,
        timeout: float | timedelta | None = None,
        default: T | Callable[[], T] = ...,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | T:
        received = self._channel.read()

        if isinstance(timeout, timedelta):
            timeout = timeout.total_seconds()

        if kwargs:
            from ceres.message import MessageFilter

            query = MessageFilter.model_validate(kwargs)
        else:
            query = None

        def fail() -> T:
            if default is ...:
                raise TimeoutError()
            if callable(default):
                return cast("Callable[[], T]", default)()
            return default

        try:
            async with asyncio.timeout(timeout):
                async for message in received:
                    if where is not None:
                        if not where(message):
                            return fail()
                    if query is not None:
                        if not query.matches(message):
                            return fail()

                    return message
        except TimeoutError:
            pass

        return fail()

    async def disconnect(self) -> None:
        if self._connectivity == Connectivity.DISCONNECTED:
            return

        self.__system__.events.emit(DisconnectingEvent, connection=self.name)

        try:
            await self.source.disconnect()
        finally:
            self._buffer.clear()
            self._connectivity = Connectivity.DISCONNECTED
            self.__system__.events.emit(DisconnectedEvent, connection=self.name)

    @override
    async def __run__(self) -> None:
        self.__system__.events.emit(ConnectionStartedEvent, connection=self.name)

        initialized = False

        try:
            while True:
                reconnect_trigger = (
                    self.reconnect_schedule.create_trigger()
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

                        self.__system__.events.emit(
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
                                self.__system__.events.emit(
                                    ReceiveTimeoutEvent,
                                    connection=self.name,
                                    timeout=timeout,
                                )
                            received = None
                    except Exception:
                        self.__system__.log.error(traceback.format_exc())

                        received = None

                    # Yield to event loop.
                    await asyncio.sleep(0)

                    # If `receive` returns `None`, an empty `bytes`, or throws an exception, the
                    # connection is considered lost.
                    if not received:
                        if self.connected:
                            self.__system__.events.emit(ConnectionLostEvent)

                            await self.disconnect()

                        break

                    # Keep local reference to the buffer for performance.
                    buffer = self._buffer
                    # Append received data to the buffer.
                    buffer.push(received, utc())

                    # Drop data from the buffer if it exceeds the buffer size limit.
                    dropped = buffer.pop_to_size(self.buffering.limit, self.buffering.drop)
                    if dropped is not None:
                        self.__system__.events.emit(
                            BufferOverflowEvent,
                            size=ByteSize(buffer.size),
                            limit=self.buffering.limit,
                            dropped=ByteSize(len(dropped.data)),
                        )

                    address = Address.ROOT if self.__system__ is None else self.__system__.address
                    for chunk in buffer.drain(self.splitter, linearize=True):
                        message = Message(
                            address=address,
                            connection=self.name,
                            timestamp=chunk.timestamp,
                            direction=MessageDirection.RECEIVE,
                            content=chunk.data,
                        )

                        self.__system__.store(message)
                        self._channel.put(message)
                        self.__system__.events.emit(MessageReceivedEvent, message=message)
        finally:
            await self.disconnect()
            self.__system__.events.emit(ConnectionStoppedEvent, connection=self.name)

    @override
    async def __stop__(self) -> None:
        await self.disconnect()


class ComponentConnectionManager(BaseComponentTaskManager[Connection]):
    __slots__ = ()

    @override
    def add(self, connection: Connection) -> None:
        connection.__system__ = self.__system__
        super().add(connection)
        if connection.name is not None:
            self.__system__.events.emit(ConnectionAddedEvent, connection=connection.name)

    @override
    async def remove(self, name: Name) -> Connection | None:
        connection = await super().remove(name)
        if connection is not None:
            self.__system__.events.emit(ConnectionRemovedEvent, connection=name)
            connection.__system__ = None

        return connection

    @override
    async def process(self, connection: Connection) -> None:
        await connection.run()
