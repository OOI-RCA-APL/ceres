import asyncio
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from datetime import timedelta
from typing import final

from ...connection import Connection
from ...exceptions import ConnectionInactiveException, ConnectionLostException


@dataclass(kw_only=True, frozen=True)
class _Stream:
    reader: StreamReader
    writer: StreamWriter


@final
class TCPConnection(Connection):
    class Parameters(Connection.Parameters):
        host: str
        port: int
        timeout: timedelta = timedelta(seconds=5)
        separator: bytes = b"\r\n"

    parameters: Parameters

    def __post_init__(self) -> None:
        super().__post_init__()
        self.__stream: _Stream | None = None

    @property
    def target(self) -> str:
        return f"{self.parameters.host}:{self.parameters.port}"

    async def try_connect(self) -> bool:
        if self.__stream:
            return True

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                self.parameters.host,
                self.parameters.port,
            ),
            self.parameters.timeout.total_seconds(),
        )

        self.__stream = _Stream(
            reader=reader,
            writer=writer,
        )

        return True

    async def try_disconnect(self) -> None:
        if not self.__stream:
            return

        try:
            self.__stream.writer.close()
        except Exception as exception:
            if error := str(exception).strip():
                self.logger.error(error)

        self.__stream = None

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

    async def receive_data(self) -> bytes:
        if not self.__stream:
            raise ConnectionInactiveException("connection is not active")

        try:
            return await self.__stream.reader.readuntil(self.parameters.separator)
        except Exception:
            raise ConnectionLostException("connection was lost")
