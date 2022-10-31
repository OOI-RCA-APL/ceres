from __future__ import annotations

import asyncio
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from datetime import timedelta

from pydantic.dataclasses import dataclass as validated_dataclass

from ...component import WithContext, WithParameters
from ...connection import Connection, ConnectionContext, ConnectionParameters
from ...exceptions import ConnectionInactiveException, ConnectionLostException


@validated_dataclass(kw_only=True, frozen=True)
class TCPConnectionParameters(ConnectionParameters):
    host: str
    port: int
    timeout: timedelta = timedelta(seconds=5)
    separator: bytes = b"\r\n"


@validated_dataclass(kw_only=True, frozen=True)
class TCPConnectionContext(ConnectionContext):
    pass


@validated_dataclass(kw_only=True, frozen=True)
class TCPConnectionReferences(ConnectionContext):
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
        context: TCPConnectionContext,
    ) -> None:
        super().__init__(parameters, context)
        self._stream: _Stream | None = None

    async def try_connect(self) -> bool:
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
        except Exception as exception:
            if error := str(exception).strip():
                self.logger.error(error)
            return False

        self._stream = _Stream(
            reader=reader,
            writer=writer,
        )

        return True

    async def try_disconnect(self) -> None:
        if not self._stream:
            return

        try:
            self._stream.writer.close()
        except Exception as exception:
            if error := str(exception).strip():
                self.logger.error(error)

        self._stream = None

    async def send_data(self, data: bytes) -> None:
        if not self._stream:
            raise ConnectionInactiveException("connection is not active")

        if not data.endswith(self.parameters.separator):
            data += self.parameters.separator

        try:
            self._stream.writer.write(data)
            await self._stream.writer.drain()
        except Exception:
            raise ConnectionLostException("connection was lost")

    async def receive_data(self) -> bytes:
        if not self._stream:
            raise ConnectionInactiveException("connection is not active")

        try:
            return await self._stream.reader.readuntil(self.parameters.separator)
        except Exception:
            raise ConnectionLostException("connection was lost")
