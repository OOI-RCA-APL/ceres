from __future__ import annotations

import asyncio
import re
import traceback
from abc import abstractmethod
from datetime import datetime, timedelta
from re import Pattern, RegexFlag
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Iterable,
    Literal,
    Protocol,
    Self,
    TypeAlias,
    override,
    runtime_checkable,
)

from pydantic import BeforeValidator, ByteSize, Field, TypeAdapter, model_validator
from pydantic.types import NonNegativeInt, PositiveInt

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseComponentTaskManager
from ceres._internal.util import UNIX
from ceres.address import Address
from ceres.connectivity import Connectivity
from ceres.data import (
    ImmutableDataObject,
    Name,
    NonEmptyStr,
    PositiveTimeDelta,
    StrEnum,
    ValidatedDataclass,
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
    DisconnectedEvent,
    DisconnectingEvent,
    IdleTimeoutEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    ReconnectScheduledEvent,
)
from ceres.loaded import Loaded
from ceres.message import Message, MessageContent, MessageDirection
from ceres.schedule import IntervalSchedule
from ceres.tasklet import Tasklet
from ceres.timing import utc

if TYPE_CHECKING:
    from anyio.abc import SocketStream

    from ceres.component import ComponentSystem
    from ceres.config import ConnectionConfig
else:
    ConnectionConfig = object


with lazy_imports(__name__):
    import anyio


class ConnectionException(Exception):
    pass


class ConnectionInactive(ConnectionException):
    pass


class ConnectionLost(ConnectionException):
    pass


class DisconnectVerifyType(StrEnum):
    RECONNECT = "reconnect"


class DisconnectVerifyByReconnect(ImmutableDataObject):
    type: Literal[DisconnectVerifyType.RECONNECT] = DisconnectVerifyType.RECONNECT
    interval: PositiveTimeDelta = timedelta(seconds=5)
    count: PositiveInt = 1


DisconnectVerify: TypeAlias = DisconnectVerifyByReconnect


class DisconnectOn(ImmutableDataObject):
    idle: PositiveTimeDelta
    verify: DisconnectVerify | None = None


class ReconnectOn(ImmutableDataObject):
    schedule: IntervalSchedule = Field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )


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


_VALID_REGEX_FLAGS_CHARACTERS = set(member for member in RegexFlag.__members__ if len(member) == 1)


def __pre_validate_regex_flags(value: object) -> object:
    if isinstance(value, str):
        value = value.upper()
        try:
            return RegexFlag[value]
        except KeyError:
            pass

        summed = RegexFlag.NOFLAG
        for character in value:
            try:
                summed |= RegexFlag[character]
            except KeyError:
                raise ValueError(
                    f"invalid regex flag character '{character}', must be one of: {_VALID_REGEX_FLAGS_CHARACTERS}"
                )

        return summed

    return value


RegexFlags = Annotated[RegexFlag, BeforeValidator(__pre_validate_regex_flags)]

Split: TypeAlias = int | tuple[int, int]


class Splitter(Protocol):
    @abstractmethod
    def split(self, data: bytes | bytearray) -> Iterable[Split]: ...


class LineSplitter(Splitter):
    REGEX: ClassVar = re.compile(rb"[\n\r]+", re.MULTILINE)

    @override
    def split(self, data: bytes | bytearray) -> Iterable[Split]:
        for match in self.REGEX.finditer(data):
            yield match.end()


class RegexSplitterMode(StrEnum):
    PREFIX = "prefix"
    SUFFIX = "suffix"


RegexSplitterModeRaw: TypeAlias = Literal["prefix", "suffix"]
RegexSplitterModeInput: TypeAlias = RegexSplitterMode | RegexSplitterModeRaw


class RegexSplitter(Splitter):
    def __init__(
        self,
        pattern: bytes | Pattern[bytes],
        flags: RegexFlags = RegexFlag.MULTILINE | RegexFlag.DOTALL,
        mode: RegexSplitterModeInput = RegexSplitterMode.SUFFIX,
    ) -> None:
        if isinstance(pattern, bytes):
            pattern = re.compile(pattern, flags)

        self.pattern = pattern
        self.mode = RegexSplitterMode(mode)

    @override
    def split(self, data: bytes | bytearray) -> Iterable[Split]:
        for match in self.pattern.finditer(data):
            match self.mode:
                case RegexSplitterMode.SUFFIX:
                    yield match.start()
                case RegexSplitterMode.PREFIX:
                    yield match.end()


@runtime_checkable
class Source(Protocol):
    @property
    def label(self) -> str: ...

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def send(self, data: bytes) -> bytes | None: ...
    async def receive(self, count: int) -> bytes | None: ...


class Connection(ValidatedDataclass, Tasklet):
    name: Name | None = None
    source: Loaded[Source]
    split: Loaded[Splitter] | None = None
    suffix: bytes | None = None

    buffering: Buffering = Field(default_factory=Buffering)
    disconnect_on: DisconnectOn | None = None
    reconnect_on: ReconnectOn = Field(default_factory=ReconnectOn)

    auto_eof: bool = Field(default=True, validation_alias="auto-eof")
    """
    If `True`, ensure an EOF is sent before disconnect, provided one has not already been sent.
    """

    @property
    def label(self) -> str:
        return self.source.label

    @property
    def system(self) -> ComponentSystem | None:
        return self.__system

    @system.setter
    def system(self, system: ComponentSystem | None) -> None:
        self.__system = system

    @override
    def __post_init__(self) -> None:
        self.__connectivity = Connectivity.DISCONNECTED
        self.__buffer = bytearray()
        self.__system: ComponentSystem | None = None

    @property
    def buffer(self) -> memoryview:
        return memoryview(self.__buffer).toreadonly()

    @property
    def connectivity(self) -> Connectivity:
        return self.__connectivity

    @property
    def connected(self) -> bool:
        return self.__connectivity == Connectivity.CONNECTED

    async def connect(self) -> bool:
        if self.__connectivity == Connectivity.CONNECTED:
            return True

        if self.system is not None:
            self.system.events.emit(ConnectingEvent, connection=self.name)

        self.__connectivity = Connectivity.CONNECTING

        reason: str | None = None

        try:
            connected = await self.source.connect()
        except Exception as exception:
            connected = False
            if text := str(exception).strip():
                reason = text

        if connected:
            self.__connectivity = Connectivity.CONNECTED
            if self.system is not None:
                self.system.events.emit(ConnectedEvent, connection=self.name)
        else:
            self.__connectivity = Connectivity.DISCONNECTED
            if self.system is not None:
                self.system.events.emit(ConnectFailedEvent, connection=self.name, reason=reason)

        return self.connected

    async def send(self, data: MessageContent) -> Message:
        """
        Send raw bytes through the connection, returning the sent message if successful.

        Note, there is no guarantee the returned message is actually recieved on the remote end,
        only that the message was transmitted.
        """
        if not self.connected:
            raise ConnectionInactive()

        if self.suffix and not data.endswith(self.suffix):
            data += self.suffix

        try:
            sent = await self.source.send(data)
        except Exception:
            sent = None

        if sent is None and self.connected:
            if self.system is not None:
                self.system.events.emit(ConnectionLostEvent, connection=self.name)
            await self.disconnect()
            raise ConnectionLost()

        message = Message(
            address=Address.ROOT if self.system is None else self.system.address,
            direction=Message.Direction.SEND,
            content=data,
        )

        if self.system is not None:
            self.system.store(message)
            self.system.events.emit(MessageSentEvent, message=message)

        return message

    async def disconnect(self) -> None:
        if self.__connectivity == Connectivity.DISCONNECTED:
            return

        if self.system is not None:
            self.system.events.emit(DisconnectingEvent, connection=self.name)

        try:
            await self.source.disconnect()
        finally:
            self.__connectivity = Connectivity.DISCONNECTED
            if self.system is not None:
                self.system.events.emit(DisconnectedEvent, connection=self.name)

    @override
    async def __run__(self) -> None:
        if self.system is not None:
            self.system.events.emit(ConnectionStartedEvent, connection=self.name)

        initialized = False

        try:
            while True:
                trigger = self.reconnect_on.schedule.as_trigger()

                while True:
                    if initialized:
                        next = trigger.get_next_fire_time()
                        if next is None:
                            break

                        delay = next - utc()

                        if self.system is not None:
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
                    timeout = (
                        self.disconnect_on.idle
                        if self.disconnect_on is not None and self.disconnect_on.idle is not None
                        else None
                    )

                    try:
                        with anyio.move_on_after(
                            timeout.total_seconds() if timeout is not None else None
                        ) as scope:
                            received = await self.source.receive(self.buffering.read)

                        if scope.cancel_called and timeout is not None:
                            if self.system is not None:
                                self.system.events.emit(
                                    IdleTimeoutEvent,
                                    connection=self.name,
                                    timeout=timeout,
                                )
                    except Exception:
                        if self.system is not None:
                            self.system.log.error(traceback.format_exc())

                        received = None

                    # Yield to event loop.
                    await asyncio.sleep(0)

                    # If `receive` returns `None`, an empty `bytes`, or throws an exception, the
                    # connection is considered lost.
                    if not received:
                        if self.connected:
                            if self.system is not None:
                                self.system.events.emit(ConnectionLostEvent)

                            await self.disconnect()

                        break

                    # Keep local reference to the buffer for performance.
                    buffer = self.__buffer
                    # Append received data to the buffer.
                    buffer.extend(received)

                    # Drop data from the buffer if it exceeds the buffer size limit.
                    excess = len(buffer) - self.buffering.limit
                    if excess > 0:
                        # Figure out how many times when need to drop `drop` bytes from the beginning
                        # of the buffer to get below `limit`.
                        drops = excess // self.buffering.drop
                        # If there is a remainder, we need to drop one more time.
                        if excess % self.buffering.drop != 0:
                            drops += 1

                        dropped = drops * self.buffering.drop
                        size = len(buffer)
                        del buffer[:dropped]

                        if self.system is not None:
                            self.system.events.emit(
                                BufferOverflowEvent,
                                size=ByteSize(size),
                                limit=self.buffering.limit,
                                dropped=ByteSize(dropped),
                            )

                    # Find all matches in the buffer.
                    if self.split is None:
                        entries = [len(buffer)]
                    else:
                        entries = self.split.split(buffer)

                    def compute_ranges() -> Iterable[tuple[int, int]]:
                        last = 0
                        for entry in entries:
                            if isinstance(entry, int):
                                start = last
                                end = entry
                            elif isinstance(entry, tuple):
                                start, end = entry
                                if start > last:
                                    yield (last, start)
                            else:
                                continue

                            if start > end:
                                continue

                            yield (start, end)
                            last = end

                    address = Address.ROOT if self.system is None else self.system.address
                    end = 0
                    last: datetime | None = None

                    for start, end in compute_ranges():
                        timestamp = utc()
                        if last is not None and timestamp <= last:
                            timestamp = last + timedelta(microseconds=1)

                        content = bytes(buffer[start:end])
                        message = Message(
                            address=address,
                            timestamp=timestamp,
                            direction=MessageDirection.RECEIVE,
                            content=content,
                        )

                        last = timestamp

                        if self.system is not None:
                            self.system.store(message)
                            self.system.events.emit(MessageReceivedEvent, message=message)

                    # If any matches were found, drop all bytes up to the end of the last match.
                    del buffer[:end]
        finally:
            await self.disconnect()
            if self.system is not None:
                self.system.events.emit(ConnectionStoppedEvent, connection=self.name)

    @override
    async def __stop__(self) -> None:
        pass


class ComponentConnectionManager(BaseComponentTaskManager[Connection]):
    @override
    def add(self, connection: Connection) -> None:
        super().add(connection)
        connection.system = self.__system__
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


class ConnectFailed(Exception):
    pass


class ConnectTimeout(asyncio.TimeoutError):
    pass


class AnyIOSource(ValidatedDataclass, Source):
    timeout: PositiveTimeDelta = timedelta(seconds=5)

    @override
    def __post_init__(self) -> None:
        self._stream: SocketStream | None = None

    @abstractmethod
    async def _create_stream(self) -> SocketStream: ...

    @override
    async def connect(self) -> bool:
        if self._stream is not None:
            return True

        try:
            self._stream = await asyncio.wait_for(
                self._create_stream(),
                self.timeout.total_seconds(),
            )
        except TimeoutError:
            raise ConnectTimeout(
                f"Connection attempt timed out after {util.encode_td(self.timeout, decimals=2)}."
            )
        except Exception as exception:
            raise ConnectFailed(f"Connection attempt failed. {exception}") from exception

        return True

    @override
    async def disconnect(self) -> None:
        if self._stream is None:
            return

        try:
            await self._stream.aclose()
        except Exception:
            pass

        self._stream = None

    @override
    async def send(self, data: bytes) -> bytes | None:
        if self._stream is None:
            return None

        try:
            await self._stream.send(data)
        except Exception:
            return None

        return data

    @override
    async def receive(self, count: int) -> bytes | None:
        if self._stream is None:
            return None

        try:
            return await self._stream.receive(count) or None
        except Exception:
            return None


class TCPSource(AnyIOSource):
    host: NonEmptyStr
    port: NonNegativeInt

    @property
    @override
    def label(self) -> str:
        return f"{self.host}:{self.port}"

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_tcp(self.host, self.port)


class UNIXSocketSource(AnyIOSource):
    socket: NonEmptyStr

    @model_validator(mode="before")
    @classmethod
    def _validate_os(cls, value: Any) -> Any:
        if not UNIX:
            raise ValueError(f"`{cls}` is not supported on the current operating system.")

        return value

    @property
    @override
    def label(self) -> str:
        return self.socket

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_unix(self.socket)
