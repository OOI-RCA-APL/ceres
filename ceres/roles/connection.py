from __future__ import annotations

import asyncio
import re
import sys
import traceback
from abc import ABC, abstractmethod
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass, field
from datetime import timedelta
from functools import cached_property
from re import Match, Pattern, RegexFlag
from typing import Annotated, Literal, Self, final, override

from pydantic import (
    BeforeValidator,
    ByteSize,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from ceres._internal.lazy import lazy_imports
from ceres.component import Component, action, routine
from ceres.connectivity import Connectivity
from ceres.data import ImmutableDataObject, PositiveTimeDelta, StrEnum
from ceres.event import (
    BufferOverflowEvent,
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectingEvent,
    ConnectionLostEvent,
    DisconnectedEvent,
    DisconnectingEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    ReconnectScheduledEvent,
)
from ceres.message import Message, MessageContent, MessageDirection
from ceres.schedule import IntervalSchedule
from ceres.timing import utc

with lazy_imports(__name__):
    import socket

    from ceres._internal import util


class ConnectionException(Exception):
    pass


class ConnectionInactive(ConnectionException):
    pass


class ConnectionLost(ConnectionException):
    pass


class ConnectionReconnectSettings(ImmutableDataObject):
    schedule: IntervalSchedule = Field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )


class ConnectionBufferingSettings(ImmutableDataObject):
    read: ByteSize = TypeAdapter(ByteSize).validate_python("1 KB")
    limit: ByteSize = TypeAdapter(ByteSize).validate_python("100 KB")
    drop: ByteSize = TypeAdapter(ByteSize).validate_python("10 KB")

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


class Connection(Component, ABC):
    separator: bytes
    regex: bytes | None = None
    regex_flags: RegexFlags = RegexFlag.MULTILINE | RegexFlag.DOTALL
    buffering: ConnectionBufferingSettings = field(default_factory=ConnectionBufferingSettings)
    reconnect_settings: ConnectionReconnectSettings = field(
        default_factory=ConnectionReconnectSettings
    )

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
            regex = re.compile(b".*" + re.escape(self.separator), self.regex_flags)

        return re.compile(regex, self.regex_flags)

    @override
    def __connectivity__(self) -> Connectivity:
        return self.__connectivity

    @property
    @abstractmethod
    def target(self) -> str: ...

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

        try:
            connected = await self._connect()
        except Exception as exception:
            connected = False
            if error := str(exception).strip():
                self.system.log.error(error)

        if connected:
            self.__connectivity = Connectivity.CONNECTED
            self.system.events.emit(ConnectedEvent)
        else:
            self.__connectivity = Connectivity.DISCONNECTED
            self.system.events.emit(ConnectFailedEvent)

        return self.connected

    @action
    async def send(
        self,
        data: Annotated[
            MessageContent,
            Field(
                description="""
                Bytes to send over the connection. 'The connection's "separator" value is appended
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

        self.system.messages.store(message)
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

        while True:
            trigger = self.reconnect_settings.schedule.as_trigger()

            while not await self.connect():
                next = trigger.get_next_fire_time()
                if next is None:
                    break

                delay = next - utc()
                self.system.events.emit(ReconnectScheduledEvent, delay=delay)
                await asyncio.sleep(delay.total_seconds())

            while self.connected:
                try:
                    received = await self._receive(self.buffering.read)
                except Exception:
                    self.system.log.error(traceback.format_exc())
                    received = None

                # If `_receive` returns `None` or throws an exception, the connection is considered
                # lost.
                if received is None:
                    if self.connected:
                        self.system.events.emit(ConnectionLostEvent)
                        await self.disconnect()

                    break

                # Append received data to the buffer.
                self.__buffer.extend(received)

                # Drop data from the buffer if it exceeds the buffer size limit.
                if len(self.__buffer) > self.buffering.limit:
                    size = ByteSize(len(self.__buffer))

                    del self.__buffer[: self.buffering.drop]
                    self.system.events.emit(
                        BufferOverflowEvent,
                        size=size,
                        limit=self.buffering.limit,
                        dropped=self.buffering.drop,
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

                    self.system.messages.store(message)
                    self.system.events.emit(MessageReceivedEvent, message=message)

                if last is not None:
                    # Remove all data up to and including the last match, if any were found.
                    del self.__buffer[: last.end()]

    @routine
    async def routine__disconnect_on_stop(self) -> None:
        try:
            await util.sleep_forever()
        finally:
            await self.disconnect()


@dataclass(kw_only=True, frozen=True)
class _Stream:
    reader: StreamReader
    writer: StreamWriter


class TCPDisconnectVerifyType(StrEnum):
    RECONNECT = "reconnect"


class TCPDisconnectVerify(ImmutableDataObject):
    type: Literal[TCPDisconnectVerifyType.RECONNECT] = TCPDisconnectVerifyType.RECONNECT
    interval: PositiveTimeDelta = timedelta(seconds=5)
    count: int = Field(ge=1)


class TCPDisconnectSettings(ImmutableDataObject):
    idle: PositiveTimeDelta
    verify: TCPDisconnectVerify | None = None


class TCPKeepAlive(ImmutableDataObject):
    idle: PositiveTimeDelta
    interval: PositiveTimeDelta
    count: int = Field(ge=1)

    @field_validator("idle", "interval")
    def _validate_timedeltas(cls, value: timedelta) -> timedelta:
        if value.microseconds != 0:
            raise ValueError("sub-second interval resolution is not allowed")

        return value


@final
class TCPConnection(Connection):
    host: str
    port: int
    timeout: PositiveTimeDelta = timedelta(seconds=5)
    disconnect_settings: TCPDisconnectSettings | None = None
    keep_alive: TCPKeepAlive | None = None

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__stream: _Stream | None = None

    @property
    @override
    def target(self) -> str:
        return f"{self.host}:{self.port}"

    @override
    async def _connect(self) -> bool:
        if self.__stream:
            return True

        loop = util.ensure_event_loop()
        sock = self.__create_socket()
        address = self.host, self.port
        await asyncio.wait_for(
            loop.sock_connect(sock, address),
            self.timeout.total_seconds(),
        )

        reader, writer = await asyncio.open_connection(sock=sock)
        self.__stream = _Stream(
            reader=reader,
            writer=writer,
        )

        return True

    @override
    async def _disconnect(self) -> None:
        if not self.__stream:
            return

        try:
            self.__stream.writer.close()
        except Exception as exception:
            if error := str(exception).strip():
                self.system.log.error(error)

        self.__stream = None

    @override
    async def _send(self, data: bytes) -> bytes | None:
        if not self.__stream:
            return None

        try:
            self.__stream.writer.write(data)
            await self.__stream.writer.drain()
        except Exception:
            self.system.log.error(traceback.format_exc())
            return None

        return data

    @override
    async def _receive(self, count: int) -> bytes | None:
        if not self.__stream:
            return None

        try:
            return await self.__stream.reader.read(count)
        except Exception:
            return None

    @routine
    async def routine__process_disconnect(self) -> None:
        condition = self.disconnect_settings
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

            self.system.log.warning(
                f"No new message has been received in {util.show_td(condition.idle)}."
            )

            disconnected = True

            if condition.verify is None:
                self.system.log.warning(
                    "No disconnect verification is set. Disconnect will happen immediately."
                )
            else:
                for count in range(1, condition.verify.count + 1):
                    self.system.log.warning(
                        f"Running disconnect verification {count}/{condition.verify.count}..."
                    )

                    match condition.verify.type:
                        case TCPDisconnectVerifyType.RECONNECT:
                            self.system.log.warning(
                                f"Attempting to create another connection to {self.target} within "
                                f"{util.show_td(condition.verify.interval)}..."
                            )
                            try:
                                await asyncio.wait_for(
                                    asyncio.open_connection(
                                        host=self.host,
                                        port=self.port,
                                    ),
                                    condition.verify.interval.total_seconds(),
                                )
                                self.system.log.info(
                                    "A second connection was created and dropped successfully. A "
                                    "disconnect has not occurred."
                                )
                                disconnected = False
                                break
                            except Exception:
                                self.system.log.warning("Failed to create a second connection.")
                                continue

                if disconnected:
                    self.system.log.error("Disconnect verified.")

            if disconnected:
                try:
                    if self.connected:
                        self.system.events.emit(ConnectionLostEvent)
                        await self.disconnect()
                except Exception:
                    pass

    def __create_socket(self) -> socket.socket:
        instance = socket.socket()

        if self.keep_alive is not None:
            keep_alive_idle = int(self.keep_alive.idle.total_seconds())
            keep_alive_interval = int(self.keep_alive.interval.total_seconds())
            keep_alive_count = self.keep_alive.count

            keep_alive_idle_ms = keep_alive_interval * 1000
            keep_alive_interval_ms = keep_alive_interval * 1000

            if sys.platform == "darwin":
                instance.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                # Set keep alive interval and count. The idle option is not configurable on Darwin.
                instance.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPALIVE,
                    keep_alive_interval_ms,
                )
                instance.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, keep_alive_count)
            elif sys.platform == "linux":
                instance.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                # Set keep alive idle, interval and count for Linux.
                instance.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPIDLE,  # type: ignore
                    keep_alive_idle,
                )
                instance.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, keep_alive_interval)
                instance.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, keep_alive_count)
            elif sys.platform == "win32":
                # Set keep alive idle and interval. The count option is not configurable on Windows.
                instance.ioctl(  # type: ignore
                    socket.SIO_KEEPALIVE_VALS,  # type: ignore
                    (
                        1,
                        keep_alive_idle_ms,
                        keep_alive_interval_ms,
                    ),
                )

        instance.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        instance.setblocking(False)
        return instance
