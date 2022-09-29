from __future__ import annotations

import asyncio
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel

from ...connection import Connection
from ...exceptions import ConnectionInactiveException, ConnectionLostException


@dataclass
class Stream:
    reader: StreamReader
    writer: StreamWriter


class TCPConnectionParameters(BaseModel):
    host: str
    port: int
    connect_timeout: timedelta = timedelta(seconds=5)
    separator: bytes = b"\r\n"


class TCPConnection(Connection):
    def __init__(self, parameters: TCPConnectionParameters) -> None:
        self._parameters = parameters
        self._stream: Stream | None = None

    @property
    def host(self) -> str:
        return self._parameters.host

    @property
    def port(self) -> int:
        return self._parameters.port

    async def connect(self) -> bool:
        if self._stream:
            return True

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                self._parameters.connect_timeout.total_seconds(),
            )
        except (ConnectionError, TimeoutError):
            return False

        self._stream = Stream(
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
            raise ConnectionInactiveException("Connection is not active.")

        if not data.endswith(self._parameters.separator):
            data += self._parameters.separator

        try:
            self._stream.writer.write(data)
            await self._stream.writer.drain()
        except Exception:
            raise ConnectionLostException("Connection was lost.")

    async def receive(self) -> bytes:
        if not self._stream:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            return await self._stream.reader.readuntil(self._parameters.separator)
        except Exception:
            raise ConnectionLostException("Connection was lost.")
