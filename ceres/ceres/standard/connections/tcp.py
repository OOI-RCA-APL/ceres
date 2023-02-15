import asyncio
import socket
import sys
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Literal, final

from pydantic import Field, validator
from typing_extensions import override

from ...connection import Connection
from ...data import ImmutableDataObject, PositiveTimeDelta
from ...events import ConnectionLostEvent, MessageReceivedEvent
from ...exceptions import ConnectionInactiveException, ConnectionLostException
from ...internal.utilities import ensure_event_loop, show_td
from ...routine import routine


@dataclass(kw_only=True, frozen=True)
class _Stream:
    reader: StreamReader
    writer: StreamWriter


class TCPDisconnectVerifyKind(str, Enum):
    RECONNECT = "reconnect"


class TCPDisconnectVerify(ImmutableDataObject):
    kind: Literal[TCPDisconnectVerifyKind.RECONNECT] = TCPDisconnectVerifyKind.RECONNECT
    interval: PositiveTimeDelta = timedelta(seconds=5)
    count: int = Field(ge=1)


class TCPDisconnect(ImmutableDataObject):
    idle: PositiveTimeDelta
    verify: TCPDisconnectVerify | None = None


class TCPKeepAlive(ImmutableDataObject):
    idle: PositiveTimeDelta
    interval: PositiveTimeDelta
    count: int = Field(ge=1)

    @validator("idle", "interval")
    def _validate_timedeltas(cls, value: timedelta) -> timedelta:
        if value.microseconds != 0:
            raise ValueError("sub-second interval resolution is not allowed")

        return value


@final
class TCPConnection(Connection):
    class Parameters(Connection.Parameters):
        host: str
        port: int
        timeout: PositiveTimeDelta = timedelta(seconds=5)
        separator: bytes = b"\r\n"
        disconnect: TCPDisconnect | None = None
        keep_alive: TCPKeepAlive | None = None

    parameters: Parameters

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__stream: _Stream | None = None

    @property
    @override
    def target(self) -> str:
        return f"{self.parameters.host}:{self.parameters.port}"

    @override
    async def try_connect(self) -> bool:
        if self.__stream:
            return True

        loop = ensure_event_loop()
        sock = self.__create_socket()
        address = self.parameters.host, self.parameters.port
        await asyncio.wait_for(
            loop.sock_connect(sock, address),
            self.parameters.timeout.total_seconds(),
        )

        reader, writer = await asyncio.open_connection(sock=sock)
        self.__stream = _Stream(
            reader=reader,
            writer=writer,
        )

        return True

    @override
    async def try_disconnect(self) -> None:
        if not self.__stream:
            return

        try:
            self.__stream.writer.close()
        except Exception as exception:
            if error := str(exception).strip():
                self.logger.error(error)

        self.__stream = None

    @override
    async def send_data(self, data: bytes) -> None:
        if not self.__stream:
            raise ConnectionInactiveException("connection is not active")

        if not data.endswith(self.parameters.separator):
            data += self.parameters.separator

        try:
            self.__stream.writer.write(data)
            await self.__stream.writer.drain()
        except Exception:
            raise ConnectionLostException("connection was lost")

    @override
    async def receive_data(self) -> bytes:
        if not self.__stream:
            raise ConnectionInactiveException("connection is not active")

        try:
            return await self.__stream.reader.readuntil(self.parameters.separator)
        except Exception:
            raise ConnectionLostException("connection was lost")

    @routine
    async def __process_disconnect(self) -> None:
        disconnect = self.parameters.disconnect
        if disconnect is None:
            return

        async def wait_for_message_received() -> None:
            async for event in self.events:
                if isinstance(event, MessageReceivedEvent):
                    return

        while True:
            try:
                await asyncio.wait_for(
                    wait_for_message_received(),
                    disconnect.idle.total_seconds(),
                )
                continue
            except asyncio.TimeoutError:
                if not self.connected:
                    continue

            self.logger.warning(f"No new message has been received in {show_td(disconnect.idle)}.")

            disconnected = True

            if disconnect.verify is None:
                self.logger.warning(
                    f"No disconnect verification is set. Disconnect will happen immediately."
                )
            else:
                for count in range(1, disconnect.verify.count + 1):
                    self.logger.warning(
                        f"Running disconnect verification {count}/{disconnect.verify.count}..."
                    )

                    match disconnect.verify.kind:
                        case TCPDisconnectVerifyKind.RECONNECT:
                            self.logger.warning(
                                f"Attempting to create another connection to {self.target} within {show_td(disconnect.verify.interval)}..."
                            )
                            try:
                                await asyncio.wait_for(
                                    asyncio.open_connection(
                                        host=self.parameters.host,
                                        port=self.parameters.port,
                                    ),
                                    disconnect.verify.interval.total_seconds(),
                                )
                                self.logger.info(
                                    f"A second connection was created and dropped successfully. A disconnect has not occurred."
                                )
                                disconnected = False
                                break
                            except Exception:
                                self.logger.warning(f"Failed to create a second connection.")
                                continue
                        case _:
                            pass

                if disconnected:
                    self.logger.error("Disconnect verified.")

            if disconnected:
                try:
                    self.emit_event(ConnectionLostEvent())
                    await self.disconnect()
                except Exception:
                    pass

    def __create_socket(self) -> socket.socket:
        instance = socket.socket()

        if self.parameters.keep_alive is not None:
            keep_alive_idle = int(self.parameters.keep_alive.idle.total_seconds())
            keep_alive_interval = int(self.parameters.keep_alive.interval.total_seconds())
            keep_alive_count = self.parameters.keep_alive.count

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
