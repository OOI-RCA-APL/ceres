import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4

from ..config import ConnectionConfig, ConnectionReconnectConfig
from ..connection import Connection, ConnectionContext
from ..events import (
    ConnectedEvent,
    DisconnectedEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from ..exceptions import ComponentNotLoadedException, ConnectionInactiveException
from ..message import Message, MessageDirection
from ..path import ConnectionPath, LocalConnectionPath
from ..protocols import ReferencedConnectionHandle
from .component import ComponentHandle, ComponentHandleContext
from .database.entity import MessageEntity


@dataclass(kw_only=True, frozen=True)
class ReceivedMessage:
    id: UUID
    timestamp: datetime
    content: bytes


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class ReconnectScheduler:
    def __init__(self, config: ConnectionReconnectConfig) -> None:
        self.interval = config.interval
        self.max_interval = config.max_interval

        if config.backoff is not None:
            self.backoff: float = config.backoff
        else:
            self.backoff = 1

        self._retries = 0

    def reset(self) -> None:
        self._retries = 0

    def next(self) -> timedelta:
        next = self.interval * self.backoff**self._retries
        if self.max_interval is not None and next > self.max_interval:
            next = self.max_interval
        self._retries += 1
        return next


@dataclass(kw_only=True, frozen=True)
class ConnectionHandleContext(ComponentHandleContext):
    path: ConnectionPath


class ConnectionHandle(
    ComponentHandle[
        ConnectionHandleContext,
        Connection,
        ConnectionContext,
    ],
    ReferencedConnectionHandle,
):
    MAX_RECEIVE_BUFFER_SIZE = 2500

    def __init__(self, context: ConnectionHandleContext) -> None:
        super().__init__(context)
        self._state = ConnectionState.DISCONNECTED
        self._receive_buffer: list[ReceivedMessage] = []
        self._is_flushing = False
        self._last_message_timestamp: datetime | None = None
        self._reconnect = ReconnectScheduler(self.config.reconnect)

    @property
    def path(self) -> ConnectionPath:
        return self._context.path

    @property
    def config(self) -> ConnectionConfig:
        return super().config  # type: ignore

    @property
    def instance(self) -> Connection | None:
        return super().instance

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    def _get_component_type(self) -> type[Connection]:  # type: ignore
        return Connection

    async def connect(self) -> bool:
        if not self._instance:
            return False
        if self._state == ConnectionState.CONNECTED:
            return True

        self.logger.info("Connecting...")

        self._state = ConnectionState.CONNECTING
        if await self._instance.connect():
            self._state = ConnectionState.CONNECTED
            await self._context.unit.broadcast(
                ConnectedEvent(
                    path=LocalConnectionPath(self._context.path.name),
                    timestamp=datetime.now(timezone.utc),
                )
            )
            self.logger.info("Connected successfully.")
        else:
            self._state = ConnectionState.DISCONNECTED
            self.logger.error("Failed to connect.")

        return self.connected

    async def disconnect(self) -> None:
        if not self._instance or self._state == ConnectionState.DISCONNECTED:
            return

        self.logger.info("Disconnecting...")

        try:
            await self._instance.disconnect()
        finally:
            self._state = ConnectionState.DISCONNECTED
            try:
                await self._context.unit.broadcast(
                    DisconnectedEvent(
                        path=LocalConnectionPath(self._context.path.name),
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            finally:
                self.logger.info("Disconnected.")

    async def send(self, data: bytes) -> Message:
        if not self._instance:
            raise ComponentNotLoadedException("connection is not loaded")

        try:
            await self._instance.send(data)
        except Exception:
            await self.disconnect()
            raise

        async with self._context.database.session() as session:
            session.add(
                entity := MessageEntity(
                    connection_id=self._context.id,
                    timestamp=datetime.now(timezone.utc),
                    direction=MessageDirection.SEND,
                    content=data,
                )
            )

            await session.commit()

        message = Message.create_from(entity)
        await self._context.unit.broadcast(
            MessageSentEvent(
                path=LocalConnectionPath(self._context.path.name),
                message=message,
            )
        )

        return message

    async def _tasklet_run(self) -> None:
        await super()._tasklet_run()

        async def process_update() -> None:
            while True:
                await self._update()

        async def process_flush() -> None:
            while True:
                await asyncio.sleep(0.1)
                if not self._is_flushing:
                    await self._flush()

        await asyncio.gather(
            process_update(),
            process_flush(),
        )

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

        await self.disconnect()
        await self._flush()

    async def _update(self) -> None:
        if not self._instance:
            return

        while not await self.connect():
            await self.alert("error", "connection-attempt-failed")
            seconds = self._reconnect.next().total_seconds()
            self.logger.info(f"Reconnecting in {seconds:g} seconds...")
            await asyncio.sleep(seconds)

        self._reconnect.reset()

        while self._state == ConnectionState.CONNECTED:
            await self._receive()

    async def _receive(self) -> None:
        if not self._instance:
            raise ConnectionInactiveException("connection is not active")

        try:
            data = await self._instance.receive()
        except Exception:
            await self.disconnect()
            raise

        self.logger.info(f"Received: {repr(data)}")

        # Ensure timestamps are different.
        if self._last_message_timestamp:
            while self._last_message_timestamp == datetime.now(timezone.utc):
                await asyncio.sleep(0)

        timestamp = datetime.now(timezone.utc)

        message = ReceivedMessage(
            id=uuid4(),
            timestamp=timestamp,
            content=data,
        )

        self._last_message_timestamp = timestamp
        self._receive_buffer.append(message)

        if not self._is_flushing and len(self._receive_buffer) >= self.MAX_RECEIVE_BUFFER_SIZE:
            await self._flush()

        await self._context.unit.broadcast(
            MessageReceivedEvent(
                path=LocalConnectionPath(self._context.path.name),
                message=Message(
                    id=message.id,
                    connection_id=self._context.id,
                    timestamp=message.timestamp,
                    content=message.content,
                    direction=MessageDirection.RECEIVE,
                ),
            )
        )

    async def _flush(self) -> None:
        if not self._receive_buffer:
            return

        self._is_flushing = True

        messages = self._receive_buffer
        self._receive_buffer = []

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
            self._receive_buffer = [*messages, *self._receive_buffer]
        finally:
            self._is_flushing = False
