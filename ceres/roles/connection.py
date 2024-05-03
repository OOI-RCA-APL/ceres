import asyncio
import socket
import sys
import traceback
from abc import ABC, abstractmethod
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Literal, final

from pydantic import Field, field_validator
from typing_extensions import override

from ceres._internal.utilities import ensure_event_loop, show_td, sleep_forever
from ceres.component import Component, action, routine
from ceres.connectivity import Connectivity
from ceres.data import ImmutableDataObject, PositiveTimeDelta, StrEnum
from ceres.event import (
    ConnectedEvent,
    ConnectFailedEvent,
    ConnectingEvent,
    ConnectionLostEvent,
    DisconnectedEvent,
    DisconnectingEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from ceres.message import Message, MessageContent, MessageDirection
from ceres.schedule import IntervalSchedule
from ceres.timing import utc


class ConnectionException(Exception):
    pass


class ConnectionInactive(ConnectionException):
    pass


class ConnectionLost(ConnectionException):
    pass


class ReconnectSettings(ImmutableDataObject):
    schedule: IntervalSchedule = Field(
        default_factory=lambda: IntervalSchedule(
            interval=timedelta(seconds=1),
            multiplier=2,
            max=timedelta(seconds=60),
        )
    )


class Connection(Component, ABC):
    separator: bytes = b"\r\n"
    reconnect_settings: ReconnectSettings = field(default_factory=ReconnectSettings)

    @override
    def __setup__(self) -> None:
        super().__setup__()
        self.__connectivity = Connectivity.DISCONNECTED

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
    async def _try_connect(self) -> bool: ...

    @abstractmethod
    async def _try_disconnect(self) -> None: ...

    @abstractmethod
    async def _send_data(self, data: bytes) -> bytes | None: ...

    @abstractmethod
    async def _poll_data(self) -> bytes | None: ...

    async def connect(self) -> bool:
        if self.__connectivity == Connectivity.CONNECTED:
            return True

        self.system.events.emit(ConnectingEvent)
        self.__connectivity = Connectivity.CONNECTING

        try:
            connected = await self._try_connect()
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
    async def send_message(
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
            sent = await self._send_data(data)
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

    async def __poll_message(self) -> Message | None:
        try:
            data = await self._poll_data()
        except Exception:
            self.system.log.error(traceback.format_exc())
            data = None
            raise

        if data is None:
            if self.connected:
                self.system.events.emit(ConnectionLostEvent)
                await self.disconnect()

            return None

        message = Message(
            address=self.system.address,
            direction=MessageDirection.RECEIVE,
            content=data,
        )

        self.system.messages.store(message)
        self.system.events.emit(MessageReceivedEvent, message=message)
        return message

    async def disconnect(self) -> None:
        if self.__connectivity == Connectivity.DISCONNECTED:
            return

        self.system.events.emit(DisconnectingEvent)

        try:
            await self._try_disconnect()
        finally:
            self.__connectivity = Connectivity.DISCONNECTED
            self.system.events.emit(DisconnectedEvent)

    @routine
    async def routine__process_connection(self) -> None:
        while True:
            trigger = self.reconnect_settings.schedule.as_trigger()

            while not await self.connect():
                next = trigger.get_next_fire_time()
                if next is None:
                    break

                delay = (next - utc()).total_seconds()
                self.system.log.info(f"Reconnecting in {round(delay, 1):g} seconds...")
                await asyncio.sleep(delay)

            while self.connected:
                data = await self.__poll_message()
                if data is None:
                    break

    @routine
    async def routine__disconnect_on_stop(self) -> None:
        try:
            await sleep_forever()
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
    async def _try_connect(self) -> bool:
        if self.__stream:
            return True

        loop = ensure_event_loop()
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
    async def _try_disconnect(self) -> None:
        if not self.__stream:
            return

        try:
            self.__stream.writer.close()
        except Exception as exception:
            if error := str(exception).strip():
                self.system.log.error(error)

        self.__stream = None

    @override
    async def _send_data(self, data: bytes) -> bytes | None:
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
    async def _poll_data(self) -> bytes | None:
        if not self.__stream:
            return None

        try:
            return await self.__stream.reader.readuntil(self.separator)
        except Exception:
            return None

    @routine
    async def routine__process_disconnect(self) -> None:
        condition = self.disconnect_settings
        if condition is None:
            await sleep_forever()
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
                f"No new message has been received in {show_td(condition.idle)}."
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
                                f"{show_td(condition.verify.interval)}..."
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
