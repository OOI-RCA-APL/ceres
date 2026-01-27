import asyncio
from abc import abstractmethod
from datetime import timedelta
from typing import Any, override

from anyio.abc import SocketStream
from pydantic import NonNegativeInt, model_validator

from ceres._internal import util
from ceres._internal.util import UNIX
from ceres.data import NonEmptyStr, PositiveTimeDelta, ValidatedDataclass


class Source(ValidatedDataclass):
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


class TCPSource(AnyIOSource, kw_only=False):
    host: NonEmptyStr
    port: NonNegativeInt

    @property
    @override
    def label(self) -> str:
        return f"{self.host}:{self.port}"

    @override
    async def _create_stream(self) -> SocketStream:
        import anyio

        return await anyio.connect_tcp(self.host, self.port)


class UNIXSocketSource(AnyIOSource, kw_only=False):
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
        import anyio

        return await anyio.connect_unix(self.socket)
