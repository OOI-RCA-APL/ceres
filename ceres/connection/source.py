import asyncio
from abc import abstractmethod
from dataclasses import field
from datetime import timedelta
from typing import override

import anyio
from anyio.abc import SocketStream
from pydantic import NonNegativeInt

from ceres.__internal__.utilities.platforms import UNIX
from ceres.data import DataObject, NonBlankStr, PositiveTimeDelta
from ceres.timing import sdelta

__all__ = [
    "Source",
    "ConnectFailed",
    "ConnectTimeout",
    "AnyIOSource",
    "TCPSource",
    "UNIXSocketSource",
]


class Source(DataObject):
    """Abstract byte-oriented connection endpoint used by `Connection`.

    Subclasses adapt a concrete transport (TCP socket, UNIX socket, serial port, etc.) to the
    common `connect`, `disconnect`, `send`, `receive` interface that `Connection` drives.
    """

    @property
    @abstractmethod
    def label(self) -> str:
        """A short human-readable identifier for the source (e.g. `tcp://host:port`)."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """Establish the underlying connection.

        Returns:
            `True` if the source is connected when this call returns.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the underlying connection. Idempotent, safe to call when not connected."""
        ...

    @abstractmethod
    async def send(self, data: bytes) -> bytes | None:
        """Send `data` over the connection.

        Returns:
            The sent bytes on success, or `None` if the send failed (the caller should treat the
            connection as lost).
        """
        ...

    @abstractmethod
    async def receive(self, count: int) -> bytes | None:
        """Receive up to `count` bytes from the connection.

        Returns:
            The received bytes (length between 1 and `count`), or `None` if the connection is
            closed, errored, or returned no data (the caller should treat this as connection
            loss).
        """
        ...


class ConnectFailed(Exception):
    """Raised when an attempt to establish a `Source` connection fails."""


class ConnectTimeout(asyncio.TimeoutError):
    """Raised when a `Source` connect attempt exceeds its configured timeout."""


class AnyIOSource(Source):
    """Base class for `Source` implementations backed by an `anyio` `SocketStream`.

    Subclasses provide `_create_stream()` to open the underlying transport, this class handles
    timeouts, error mapping, and the common `send`/`receive`/`disconnect` lifecycle.
    """

    timeout: PositiveTimeDelta = timedelta(seconds=5)
    """Maximum time to wait for `_create_stream()` to complete during `connect()`."""
    _stream: SocketStream | None = field(init=False)

    def __post_init__(self) -> None:
        self._stream = None

    @abstractmethod
    async def _create_stream(self) -> SocketStream:
        """Open and return a new `SocketStream` for the concrete transport."""
        ...

    @override
    async def connect(self) -> bool:
        """Open the underlying stream, raising on timeout or connection failure.

        Returns:
            `True` when the connection is established.

        Raises:
            ConnectTimeout: If `_create_stream()` does not complete within `timeout`.
            ConnectFailed: If `_create_stream()` raises any other exception.
        """
        if self._stream is not None:
            return True

        try:
            self._stream = await asyncio.wait_for(
                self._create_stream(),
                self.timeout.total_seconds(),
            )
        except TimeoutError:
            raise ConnectTimeout(
                f"Connection attempt timed out after {sdelta(self.timeout, decimals=2)}."
            )
        except Exception as exception:
            raise ConnectFailed(f"Connection attempt failed. {exception}") from exception

        return True

    @override
    async def disconnect(self) -> None:
        """Close the stream and reset to a disconnected state. Swallow close errors."""
        if self._stream is None:
            return

        # Swallow close errors, the stream is being abandoned regardless.
        try:
            await self._stream.aclose()
        except Exception:
            pass

        self._stream = None

    @override
    async def send(self, data: bytes) -> bytes | None:
        """Write `data` to the stream.

        Returns:
            The sent bytes on success, or `None` if the stream is missing or the send fails.
        """
        if self._stream is None:
            return None

        try:
            await self._stream.send(data)
        except Exception:
            return None

        return data

    @override
    async def receive(self, count: int) -> bytes | None:
        """Read up to `count` bytes from the stream.

        Returns:
            The received bytes, or `None` if the stream is missing, closed, or errored.
        """
        if self._stream is None:
            return None

        try:
            # Coerce empty reads to `None` so the caller treats EOF and error identically.
            return await self._stream.receive(count) or None
        except Exception:
            return None


class TCPSource(AnyIOSource):
    """A `Source` that connects to a remote TCP host and port."""

    host: NonBlankStr
    """Hostname or IP address to connect to."""
    port: NonNegativeInt
    """TCP port to connect to."""

    @property
    @override
    def label(self) -> str:
        """Return a `tcp://host:port` label identifying this source."""
        return f"tcp://{self.host}:{self.port}"

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_tcp(self.host, self.port)


class UNIXSocketSource(AnyIOSource):
    """A `Source` that connects to a UNIX domain socket. Unsupported on non-UNIX platforms."""

    socket: NonBlankStr
    """Filesystem path of the UNIX domain socket to connect to."""

    def __post_init__(self) -> None:
        if not UNIX:
            raise ValueError(f"`{type(self)}` is not supported on the current operating system.")
        # Initialize the stream field that the base class relies on.
        super().__post_init__()

    @property
    @override
    def label(self) -> str:
        """Return a `unix://path` label identifying this source."""
        return f"unix://{self.socket}"

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_unix(self.socket)
