from abc import abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any, Final, Protocol, override

import anyio
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
from anyio.abc import ByteStream, Listener, SocketAttribute, SocketStream
from pydantic import NonNegativeInt, model_validator

from ceres import Component, routine
from ceres._internal import util
from ceres._internal.util import UNIX
from ceres.concurrency import sleep
from ceres.data import NonEmptyStr
from ceres.event import (
    ClientConnectedEvent,
    ClientDisconnectedEvent,
    ServerBindEvent,
    ServerBindExceptionEvent,
    ServerProcessingExceptionEvent,
)
from ceres.schedule import IntervalSchedule, Schedule
from ceres.timing import utc


class Client(Protocol):
    __slots__ = ()

    async def receive(self, size: int = ...) -> bytes: ...
    async def send(self, data: bytes) -> None: ...
    async def send_eof(self) -> None: ...


class Server[ClientT: Client](Component):
    auto_eof: bool = True
    """
    If `True`, ensure an EOF is sent once handler exits, provided one has not already been sent.
    """

    rebind_on: Schedule = IntervalSchedule(
        interval=timedelta(seconds=1),
        multiplier=2,
        max=timedelta(seconds=60),
    )

    @routine
    @abstractmethod
    async def serve(self) -> None: ...

    @abstractmethod
    async def handle(self, client: ClientT) -> None: ...


class _AnyIOClient[StreamT: ByteStream](Client):
    __slots__ = ("stream",)

    def __init__(self, stream: StreamT) -> None:
        self.stream: Final = stream
        """Inner stream for this client connection."""

    @property
    @abstractmethod
    def bind(self) -> str: ...

    @override
    async def receive(self, size: int = 65536) -> bytes:
        """
        Receive at most `count` bytes from the peer.

        :param count: Maximum number of bytes to receive.
        :return: The received bytes.
        :raises ~anyio.EndOfStream: If this client's stream has been closed from the other end.
        """
        return await self.stream.receive(size)

    @override
    async def send(self, data: bytes) -> None:
        """
        Send the given bytes to the peer.

        :param data: The bytes to send.
        """
        await self.stream.send(data)

    @override
    async def send_eof(self) -> None:
        """
        Send an end-of-file indication to the peer.

        You should not try to send any further data to this stream after calling this
        method. This method is idempotent (does nothing on successive calls).
        """
        await self.stream.send_eof()


class _AnyIOServer[ClientT: _AnyIOClient](Server[ClientT]):
    @property
    @abstractmethod
    def bind(self) -> str: ...

    @abstractmethod
    async def _create_listener(self) -> Listener[SocketStream]: ...

    @abstractmethod
    def _create_client(self, stream: SocketStream) -> ClientT: ...

    @abstractmethod
    async def _cleanup(self) -> None: ...

    @override
    async def serve(self) -> None:
        trigger = self.rebind_on.create_trigger()

        while True:
            try:
                async with await self._create_listener() as listener:
                    # Reset rebind schedule on success.
                    trigger = self.rebind_on.create_trigger()
                    self.system.events.emit(
                        ServerBindEvent,
                        bind=self.bind,
                    )

                    await listener.serve(self._execute_handler)

            except* OSError as exception:
                self.system.events.emit(
                    ServerBindExceptionEvent,
                    bind=self.bind,
                    traceback=util.get_traceback(exception),
                )
            finally:
                await self._cleanup()

            next = trigger.get_next_fire_time()
            if next is None:
                break

            await sleep(next - utc())

    async def _execute_handler(self, stream: SocketStream) -> None:
        client = self._create_client(stream)
        bind = client.bind

        self.system.events.emit(
            ClientConnectedEvent,
            client=bind,
        )

        try:
            async with stream:
                try:
                    await self.handle(client)
                finally:
                    try:
                        # Attempt to send an EOF once the handler exits.
                        if self.auto_eof:
                            await client.send_eof()
                    except Exception:
                        pass
        except EndOfStream, BrokenResourceError, ClosedResourceError:
            pass
        except Exception as exception:
            self.system.events.emit(
                ServerProcessingExceptionEvent,
                traceback=util.get_traceback(exception),
                client=bind,
            )
        finally:
            self.system.events.emit(
                ClientDisconnectedEvent,
                client=bind,
            )


class TCPClient(_AnyIOClient[SocketStream]):
    __slots__ = ("_host", "_port")

    @override
    def __init__(self, stream: SocketStream) -> None:
        super().__init__(stream)

        address = self.stream.extra(SocketAttribute.remote_address)
        port = self.stream.extra(SocketAttribute.remote_port)

        self._host: Final = address[0] if isinstance(address, tuple) else address
        self._port: Final = port

    @property
    @override
    def bind(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port


class TCPServer(_AnyIOServer[TCPClient]):
    host: NonEmptyStr = "0.0.0.0"
    port: NonNegativeInt

    @property
    @override
    def bind(self) -> str:
        return f"{self.host}:{self.port}"

    @abstractmethod
    @override
    async def handle(self, client: TCPClient) -> None: ...

    @override
    async def _create_listener(self) -> Listener[SocketStream]:
        return await anyio.create_tcp_listener(
            local_host=self.host,
            local_port=self.port,
            reuse_port=True,
        )

    @override
    def _create_client(self, stream: SocketStream) -> TCPClient:
        return TCPClient(stream)

    @override
    async def _cleanup(self) -> None:
        pass


class UNIXSocketClient(_AnyIOClient[SocketStream]):
    __slots__ = ("_socket",)

    @override
    def __init__(self, stream: SocketStream) -> None:
        super().__init__(stream)

        address = self.stream.extra(SocketAttribute.remote_address)
        self._socket: Final = address[0] if isinstance(address, tuple) else address

    @property
    @override
    def bind(self) -> str:
        return self.socket

    @property
    def socket(self) -> str:
        address = self.stream.extra(SocketAttribute.remote_address)
        return address[0] if isinstance(address, tuple) else address


class UNIXSocketServer(_AnyIOServer[UNIXSocketClient]):
    socket: Path
    socket_mode: NonNegativeInt | None = None

    @model_validator(mode="before")
    @classmethod
    def _validate_os(cls, value: Any) -> Any:
        if not UNIX:
            raise ValueError(f"`{cls.__name__}` is not supported on the current operating system.")

        return value

    @property
    @override
    def bind(self) -> str:
        return str(self.socket)

    @abstractmethod
    @override
    async def handle(self, client: UNIXSocketClient) -> None: ...

    @override
    async def _create_listener(self) -> Listener[SocketStream]:
        return await anyio.create_unix_listener(
            self.socket,
            mode=self.socket_mode,
        )

    @override
    def _create_client(self, stream: SocketStream) -> UNIXSocketClient:
        return UNIXSocketClient(stream)

    @override
    async def _cleanup(self) -> None:
        try:
            self.socket.unlink(missing_ok=True)
        except OSError:
            pass
