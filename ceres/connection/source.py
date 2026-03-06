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
    @property
    @abstractmethod
    def label(self) -> str: ...

    @abstractmethod
    async def connect(self) -> bool: ...
    @abstractmethod
    async def disconnect(self) -> None: ...
    @abstractmethod
    async def send(self, data: bytes) -> bytes | None: ...
    @abstractmethod
    async def receive(self, count: int) -> bytes | None: ...


class ConnectFailed(Exception):
    pass


class ConnectTimeout(asyncio.TimeoutError):
    pass


class AnyIOSource(Source):
    timeout: PositiveTimeDelta = timedelta(seconds=5)
    _stream: SocketStream | None = field(init=False)

    def __post_init__(self) -> None:
        self._stream = None

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
                f"Connection attempt timed out after {sdelta(self.timeout, decimals=2)}."
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
    host: NonBlankStr
    port: NonNegativeInt

    @property
    @override
    def label(self) -> str:
        return f"tcp://{self.host}:{self.port}"

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_tcp(self.host, self.port)


class UNIXSocketSource(AnyIOSource):
    socket: NonBlankStr

    def __post_init__(self) -> None:
        if not UNIX:
            raise ValueError(f"`{type(self)}` is not supported on the current operating system.")

    @property
    @override
    def label(self) -> str:
        return f"unix://{self.socket}"

    @override
    async def _create_stream(self) -> SocketStream:
        return await anyio.connect_unix(self.socket)
