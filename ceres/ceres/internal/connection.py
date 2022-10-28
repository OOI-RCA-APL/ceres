import asyncio

from ..connection import Connection
from ..message import Message, MessageDirection
from ..protocols import ReferencedConnectionHandle
from .component import ComponentHandle, ComponentHandleContext
from .database.entity import MessageEntity


class ConnectionHandle(ComponentHandle[Connection], ReferencedConnectionHandle):
    @classmethod
    def get_max_buffer_size(cls) -> int:
        return 2500

    @classmethod
    def _get_component_type(cls) -> type[Connection]:
        return Connection

    def __init__(self, context: ComponentHandleContext) -> None:
        super().__init__(context)
        self._buffer: list[Message] = []
        self._flushing = False

    async def _tasklet_run(self) -> None:
        await asyncio.gather(
            super()._tasklet_run(),
            self._process_messages(),
            self._process_flush(),
        )

    async def _process_messages(self) -> None:
        while True:
            if not self._instance:
                await asyncio.sleep(1)
                continue

            message = await self._instance.get_next_message()
            self._buffer.append(message)

            if not self._flushing and len(self._buffer) >= self.get_max_buffer_size():
                await self._flush()

    async def _process_flush(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            if not self._flushing:
                await self._flush()

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

        try:
            if self.instance:
                await self.instance.disconnect()
        finally:
            await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return

        self._flushing = True

        messages = self._buffer
        self._buffer = []

        try:
            async with self._context.database.session() as session:
                session.add_all(
                    [
                        MessageEntity(
                            id=message.id,
                            connection_id=self._context.id,
                            timestamp=message.timestamp,
                            direction=MessageDirection.RECEIVE,
                            content=message.content,
                        )
                        for message in messages
                    ]
                )

                await session.commit()
        except Exception:
            self._buffer = [*messages, *self._buffer]
        finally:
            self._flushing = False
