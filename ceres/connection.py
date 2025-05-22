from __future__ import annotations

import asyncio
import re
import traceback
from abc import abstractmethod
from dataclasses import field
from datetime import timedelta
from functools import cached_property
from re import Match, Pattern, RegexFlag
from typing import Annotated, Any, Literal, Self, override

from pydantic import BeforeValidator, ByteSize, Field, TypeAdapter, model_validator
from pydantic.types import NonNegativeInt

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.util import UNIX
from ceres.component import Component, action, routine
from ceres.connectivity import Connectivity
from ceres.data import ImmutableDataObject, NonEmptyStr, PositiveTimeDelta, StrEnum
from ceres.event import (
    BufferOverflowEvent,
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectingEvent,
    ConnectionLostEvent,
    DisconnectedEvent,
    DisconnectingEvent,
    DisconnectUnverifiedEvent,
    DisconnectVerifiedEvent,
    DisconnectVerifyStartedEvent,
    IdleTimeoutEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    ReconnectScheduledEvent,
)
from ceres.message import Message, MessageContent, MessageDirection
from ceres.schedule import IntervalSchedule
from ceres.timing import utc

with lazy_imports(__name__):
    import anyio
    from anyio.abc import SocketStream


class ConnectionException(Exception):
    pass


class ConnectionInactive(ConnectionException):
    pass


class ConnectionLost(ConnectionException):
    pass


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


class Connection(Component):
    separator: bytes
    regex: bytes | None = None
    regex_flags: RegexFlags = RegexFlag.MULTILINE | RegexFlag.DOTALL
    buffering: Buffering = field(default_factory=Buffering)
    reconnect_on: ReconnectOn = field(default_factory=ReconnectOn)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.regex is None:
            return self

        try:
            re.compile(self.regex, self.regex_flags)
        except re.error as exception:
            raise ValueError(f"invalid `regex` or `regex_flags`: {exception}")

        return self

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__connectivity = Connectivity.DISCONNECTED
        self.__buffer = bytearray()

    @property
    def buffer(self) -> memoryview:
        return memoryview(self.__buffer).toreadonly()

    @cached_property
    def __regex_pattern(self) -> Pattern[bytes]:
        regex = self.regex
        if regex is None:
            regex = b".*?" + re.escape(self.separator)

        return re.compile(regex, self.regex_flags)

    @override
    def __connectivity__(self) -> Connectivity:
        return self.__connectivity

    @property
    @abstractmethod
    def bind(self) -> str: ...

    @property
    def connectivity(self) -> Connectivity:
        return self.__connectivity

    @property
    def connected(self) -> bool:
        return self.__connectivity == Connectivity.CONNECTED

    @abstractmethod
    async def _connect(self) -> bool: ...

    @abstractmethod
    async def _disconnect(self) -> None: ...

    @abstractmethod
    async def _send(self, data: bytes) -> bytes | None: ...

    @abstractmethod
    async def _receive(self, count: int) -> bytes | None: ...

    async def connect(self) -> bool:
        if self.__connectivity == Connectivity.CONNECTED:
            return True

        self.system.events.emit(ConnectingEvent)
        self.__connectivity = Connectivity.CONNECTING

        reason: str | None = None

        try:
            connected = await self._connect()
        except Exception as exception:
            connected = False
            if text := str(exception).strip():
                reason = text

        if connected:
            self.__connectivity = Connectivity.CONNECTED
            self.system.events.emit(ConnectedEvent)
        else:
            self.__connectivity = Connectivity.DISCONNECTED
            self.system.events.emit(ConnectFailedEvent, reason=reason)

        return self.connected

    @action
    async def send(
        self,
        data: Annotated[
            MessageContent,
            Field(
                description="""
                Bytes to send over the connection. The connection's "separator" value is appended
                automatically if not present.
                """
            ),
        ],
    ) -> Message:
        """
        Send raw data over the connection. Returns the sent message.

        There is no guarantee that the message was will be received host-side, only that if this
        action returns successfully, the data was sent.
        """
        if not self.connected:
            raise ConnectionInactive()

        if not data.endswith(self.separator):
            data += self.separator

        try:
            sent = await self._send(data)
        except Exception:
            sent = None

        if sent is None and self.connected:
            self.system.events.emit(ConnectionLostEvent)
            await self.disconnect()
            raise ConnectionLost()

        message = Message(
            address=self.system.address,
            direction=MessageDirection.SEND,
            content=data,
        )

        self.system.store(message)
        self.system.events.emit(MessageSentEvent, message=message)
        return message

    async def disconnect(self) -> None:
        if self.__connectivity == Connectivity.DISCONNECTED:
            return

        self.system.events.emit(DisconnectingEvent)

        try:
            await self._disconnect()
        finally:
            self.__connectivity = Connectivity.DISCONNECTED
            self.system.events.emit(DisconnectedEvent)

    @routine
    async def routine__process_connection(self) -> None:
        regex = self.__regex_pattern
        initialized = False

        while True:
            trigger = self.reconnect_on.schedule.as_trigger()

            while True:
                if initialized:
                    next = trigger.get_next_fire_time()
                    if next is None:
                        break

                    delay = next - utc()
                    self.system.events.emit(ReconnectScheduledEvent, delay=delay)
                    await asyncio.sleep(delay.total_seconds())

                # Yield to event loop.
                await asyncio.sleep(0)

                connected = await self.connect()
                initialized = True
                if connected:
                    break

            while self.connected:
                try:
                    received = await self._receive(self.buffering.read)
                except Exception:
                    self.system.log.error(traceback.format_exc())
                    received = None

                # Yield to event loop.
                await asyncio.sleep(0)

                # If `_receive` returns `None`, an empty `bytes`, or throws an exception, the
                # connection is considered lost.
                if not received:
                    if self.connected:
                        self.system.events.emit(ConnectionLostEvent)
                        await self.disconnect()

                    break

                # Append received data to the buffer.
                self.__buffer.extend(received)

                # Drop data from the buffer if it exceeds the buffer size limit.
                excess = len(self.__buffer) - self.buffering.limit
                if excess > 0:
                    # Figure out how many times when need to drop `drop` bytes from the beginning
                    # of the buffer to get below `limit`.
                    drops = excess // self.buffering.drop
                    # If there is a remainder, we need to drop one more time.
                    if excess % self.buffering.drop != 0:
                        drops += 1

                    dropped = drops * self.buffering.drop
                    size = len(self.__buffer)
                    del self.__buffer[:dropped]

                    self.system.events.emit(
                        BufferOverflowEvent,
                        size=ByteSize(size),
                        limit=self.buffering.limit,
                        dropped=ByteSize(dropped),
                    )

                # Keep track of the last match processed.
                last: Match[bytes] | None = None

                # Find all matches in the buffer.
                for match in regex.finditer(self.__buffer):
                    last = match
                    # Extract bytes from the match.
                    data = match.group()

                    message = Message(
                        address=self.system.address,
                        direction=MessageDirection.RECEIVE,
                        content=data,
                    )

                    self.system.store(message)
                    self.system.events.emit(MessageReceivedEvent, message=message)

                # If any matches were found, drop all bytes up to the end of the last match.
                if last is not None:
                    del self.__buffer[: last.end()]

    @routine
    async def routine__disconnect_on_stop(self) -> None:
        try:
            await util.sleep_forever()
        finally:
            await self.disconnect()


class DisconnectVerifyType(StrEnum):
    RECONNECT = "reconnect"


class DisconnectVerify(ImmutableDataObject):
    type: Literal[DisconnectVerifyType.RECONNECT] = DisconnectVerifyType.RECONNECT
    interval: PositiveTimeDelta = timedelta(seconds=5)
    count: int = Field(ge=1)


class DisconnectOn(ImmutableDataObject):
    idle: PositiveTimeDelta
    verify: DisconnectVerify | None = None


class AnyIOConnection(Connection):
    timeout: PositiveTimeDelta = timedelta(seconds=5)
    disconnect_on: DisconnectOn | None = None

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self._stream: SocketStream | None = None

    @abstractmethod
    async def _create_stream(self) -> SocketStream: ...

    @override
    async def _connect(self) -> bool:
        if self._stream is not None:
            return True

        self._stream = await asyncio.wait_for(
            self._create_stream(),
            self.timeout.total_seconds(),
        )

        return True

    @override
    async def _disconnect(self) -> None:
        if self._stream is None:
            return

        try:
            await self._stream.aclose()
        except Exception as exception:
            if error := str(exception).strip():
                self.system.log.error(error)

        self._stream = None

    @override
    async def _send(self, data: bytes) -> bytes | None:
        if self._stream is None:
            return None

        try:
            await self._stream.send(data)
        except Exception:
            self.system.log.error(traceback.format_exc())
            return None

        return data

    @override
    async def _receive(self, count: int) -> bytes | None:
        if self._stream is None:
            return None

        try:
            return await self._stream.receive(count) or None
        except Exception:
            return None

    @routine
    async def routine__process_disconnect(self) -> None:
        condition = self.disconnect_on
        if condition is None:
            await util.sleep_forever()
            return

        async def wait_for_message_received() -> None:
            async for event in self.system.events.follow().every(MessageReceivedEvent):
                if isinstance(event, MessageReceivedEvent):
                    return

        while True:
            try:
                await asyncio.wait_for(
                    wait_for_message_received(),
                    condition.idle.total_seconds(),
                )
                continue
            except asyncio.TimeoutError:
                if not self.connected:
                    continue

            self.system.events.emit(IdleTimeoutEvent)

            disconnected = True

            if condition.verify is not None:
                self.system.events.emit(DisconnectVerifyStartedEvent)
                for count in range(1, condition.verify.count + 1):
                    match condition.verify.type:
                        case DisconnectVerifyType.RECONNECT:
                            try:
                                await asyncio.wait_for(
                                    self._create_stream(),
                                    self.timeout.total_seconds(),
                                )
                                self.system.events.emit(DisconnectUnverifiedEvent)
                                disconnected = False
                                break
                            except Exception:
                                continue

                if disconnected:
                    self.system.events.emit(DisconnectVerifiedEvent)

            if disconnected:
                try:
                    if self.connected:
                        self.system.events.emit(ConnectionLostEvent)
                        await self.disconnect()
                except Exception:
                    pass


class TCPConnection(AnyIOConnection):
    host: NonEmptyStr
    port: NonNegativeInt

    @property
    @override
    def bind(self) -> str:
        return f"{self.host}:{self.port}"

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_tcp(self.host, self.port)


class UNIXSocketConnection(AnyIOConnection):
    socket: NonEmptyStr

    @model_validator(mode="before")
    @classmethod
    def _validate_os(cls, value: Any) -> Any:
        if not UNIX:
            raise ValueError(f"`{cls.__name__}` is not supported on the current operating system.")

        return value

    @property
    @override
    def bind(self) -> str:
        return self.socket

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_unix(self.socket)
