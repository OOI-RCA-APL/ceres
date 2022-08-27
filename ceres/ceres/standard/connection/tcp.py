from __future__ import annotations

import asyncio
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from datetime import timedelta

from ...connection import Connection
from ...exceptions import (
    ConnectionDecodeException,
    ConnectionInactiveException,
    ConnectionLostException,
)


@dataclass
class Stream:
    reader: StreamReader
    writer: StreamWriter


class TCPConnection(Connection):
    def __init__(
        self,
        host: str,
        port: int,
        connect_timeout: timedelta = timedelta(seconds=5),
        separator: str = "\r\n",
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._separator = separator
        self._stream: Stream | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    async def connect(self) -> bool:
        if self._stream:
            return True

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                self._connect_timeout.total_seconds(),
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

    async def send(self, data: str) -> None:
        if not self._stream:
            raise ConnectionInactiveException("Connection is not active.")

        if not data.endswith(self._separator):
            data += self._separator

        try:
            self._stream.writer.write(data.encode())
            await self._stream.writer.drain()
        except Exception:
            raise ConnectionLostException("Connection was lost.")

    async def receive(self) -> str:
        if not self._stream:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            data = await self._stream.reader.readuntil(self._separator.encode())
        except Exception:
            raise ConnectionLostException("Connection was lost.")

        try:
            return data.decode("utf-8")
        except Exception:
            raise ConnectionDecodeException("Failed to decode data as UTF-8.")
