from __future__ import annotations

import asyncio
from asyncio import StreamReader, StreamWriter, TimeoutError
from dataclasses import dataclass
from datetime import timedelta

from ...component import WithContext, WithParameters
from ...connection import Connection, ConnectionContext, ConnectionParameters
from ...exceptions import ConnectionInactiveException, ConnectionLostException


@dataclass(kw_only=True, frozen=True)
class TCPConnectionParameters(ConnectionParameters):
    host: str
    port: int
    timeout: timedelta = timedelta(seconds=5)
    separator: bytes = b"\r\n"


@dataclass(kw_only=True, frozen=True)
class TCPConnectionContext(ConnectionContext):
    pass


@dataclass(kw_only=True, frozen=True)
class _Stream:
    reader: StreamReader
    writer: StreamWriter


class TCPConnection(
    WithParameters[TCPConnectionParameters],
    WithContext[TCPConnectionContext],
    Connection,
):
    def __init__(
        self,
        parameters: TCPConnectionParameters,
        context: ConnectionContext,
    ) -> None:
        super().__init__(parameters, context)
        self._stream: _Stream | None = None

    async def connect(self) -> bool:
        if self._stream:
            return True

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.parameters.host,
                    self.parameters.port,
                ),
                self.parameters.timeout.total_seconds(),
            )
        except (ConnectionError, TimeoutError):
            return False

        self._stream = _Stream(
            reader=reader,
            writer=writer,
        )

        return True

    async def disconnect(self) -> None:
        if self._stream:
            self._stream.writer.close()
            self._stream = None

    async def send(self, data: bytes) -> None:
        if not self._stream:
            raise ConnectionInactiveException("connection is not active")

        if not data.endswith(self.parameters.separator):
            data += self.parameters.separator

        try:
            self._stream.writer.write(data)
            await self._stream.writer.drain()
        except Exception:
            raise ConnectionLostException("connection was lost")

    async def receive(self) -> bytes:
        if not self._stream:
            raise ConnectionInactiveException("connection is not active")

        try:
            return await self._stream.reader.readuntil(self.parameters.separator)
        except Exception:
            raise ConnectionLostException("connection was lost")
