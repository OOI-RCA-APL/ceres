import asyncio
import traceback

from ..connection import Connection
from ..events import MessageReceivedEvent, MessageSentEvent
from ..message import Message, MessageDirection
from .component import ComponentHandle, ComponentHandleContext
from .database.entity import MessageEntity


class ConnectionHandle(ComponentHandle[Connection]):
    @classmethod
    def get_max_buffer_size(cls) -> int:
        return 2500

    @classmethod
    def _get_component_type(cls) -> type[Connection]:
        return Connection

    def __init__(self, context: ComponentHandleContext) -> None:
        super().__init__(context)
        self._message_buffer: list[Message] = []
        self._is_flushing_messages = False

    async def _tasklet_run(self) -> None:
        await asyncio.gather(
            super()._tasklet_run(),
            self._process_message_events(),
            self._process_message_flush(),
        )

    async def _process_message_events(self) -> None:
        if not self.instance:
            return

        async for event in self.instance.event_stream:
            if isinstance(event, (MessageSentEvent, MessageReceivedEvent)):
                self._message_buffer.append(event.message)
                if (
                    not self._is_flushing_messages
                    and len(self._message_buffer) >= self.get_max_buffer_size()
                ):
                    await self._flush_messages()

    async def _process_message_flush(self) -> None:
        if not self.instance:
            return

        while True:
            await asyncio.sleep(0.1)
            if not self._is_flushing_messages:
                await self._flush_messages()

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

        try:
            if self.instance:
                await self.instance.disconnect()
        finally:
            await self._flush_messages()

    async def _flush_messages(self) -> None:
        if not self._message_buffer:
            return

        self._is_flushing_messages = True

        messages = self._message_buffer
        self._message_buffer = []

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
            self._message_buffer = [*messages, *self._message_buffer]
            self.logger.error(
                f"An exception occurred when flushing messages: {traceback.format_exc()}"
            )
        finally:
            self._is_flushing_messages = False
