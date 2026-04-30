from abc import abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any, Final, Protocol, override

import anyio
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
from anyio.abc import ByteStream, Listener, SocketAttribute, SocketStream
from pydantic import NonNegativeInt, model_validator

from ceres import Component, routine
from ceres.__internal__.utilities.platforms import UNIX
from ceres.concurrency import sleep
from ceres.data import NonEmptyStr
from ceres.error import trace
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
    """Protocol describing a connected peer that a `Server` handler can talk to."""

    __slots__ = ()

    async def receive(self, size: int = ...) -> bytes:
        """Receive up to `size` bytes from the peer."""
        ...

    async def send(self, data: bytes) -> None:
        """Send `data` to the peer."""
        ...

    async def send_eof(self) -> None:
        """Signal end-of-file to the peer. Should be idempotent."""
        ...


class Server[ClientT: Client](Component):
    """Abstract accepting server that runs a handler per connected client.

    Concrete subclasses implement `serve()` to accept connections and `handle()` to process
    each client. Implementations in this module bind the lifecycle to an `anyio` listener and
    wire in connection/disconnection events plus automatic rebind on failure.
    """

    auto_eof: bool = True
    """If true, send EOF to the client after `handle()` returns when none was sent already."""

    rebind_on: Schedule = IntervalSchedule(
        interval=timedelta(seconds=1),
        multiplier=2,
        max=timedelta(seconds=60),
    )
    """Schedule that controls how long to wait before rebinding after a bind failure."""

    @routine
    @abstractmethod
    async def serve(self) -> None:
        """Run the server's accept loop until cancelled or the rebind schedule is exhausted."""
        ...

    @abstractmethod
    async def handle(self, client: ClientT) -> None:
        """Process a single connected `client`. Called once per accepted connection."""
        ...


class _AnyIOClient[StreamT: ByteStream](Client):
    """Base `Client` implementation backed by an `anyio` `ByteStream`."""

    __slots__ = ("stream",)

    def __init__(self, stream: StreamT) -> None:
        self.stream: Final = stream
        """Inner stream used to talk to the peer."""

    @property
    @abstractmethod
    def bind(self) -> str:
        """Short human-readable identifier for the peer (e.g. `host:port`)."""
        ...

    @override
    async def receive(self, size: int = 65536) -> bytes:
        """Receive at most `size` bytes from the peer.

        Args:
            size: Maximum number of bytes to receive.

        Returns:
            The received bytes.

        Raises:
            anyio.EndOfStream: If the peer has closed the stream.
        """
        return await self.stream.receive(size)

    @override
    async def send(self, data: bytes) -> None:
        """Send `data` to the peer.

        Args:
            data: Bytes to send.
        """
        await self.stream.send(data)

    @override
    async def send_eof(self) -> None:
        """Signal end-of-file to the peer.

        Do not send further data after calling this method. The call is idempotent, successive
        invocations have no effect.
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
                    exception=trace(exception),
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
                client=bind,
                exception=trace(exception),
            )
        finally:
            self.system.events.emit(
                ClientDisconnectedEvent,
                client=bind,
            )


class TCPClient(_AnyIOClient[SocketStream]):
    """`Client` bound to a TCP peer, exposing the peer's host and port."""

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
        """Remote peer's host or IP address."""
        return self._host

    @property
    def port(self) -> int:
        """Remote peer's TCP port."""
        return self._port


class TCPServer(_AnyIOServer[TCPClient]):
    """`Server` that binds a TCP listener to `host:port` and serves `TCPClient`s."""

    host: NonEmptyStr = "0.0.0.0"
    """Local interface to bind the listener on."""
    port: NonNegativeInt
    """Local TCP port to bind the listener on."""

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
    """`Client` bound to a UNIX domain socket peer."""

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
        """Filesystem path of the remote peer's socket."""
        address = self.stream.extra(SocketAttribute.remote_address)
        return address[0] if isinstance(address, tuple) else address


class UNIXSocketServer(_AnyIOServer[UNIXSocketClient]):
    """`Server` that binds a UNIX domain socket listener and serves `UNIXSocketClient`s.

    Unsupported on non-UNIX platforms, `_validate_os` rejects construction on other systems.
    """

    socket: Path
    """Filesystem path at which to create the UNIX domain socket."""
    socket_mode: NonNegativeInt | None = None
    """Optional file mode for the created socket. `None` keeps the platform default."""

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
