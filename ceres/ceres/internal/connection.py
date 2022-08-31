from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

import anyio
from pydantic import BaseModel

from ..config import ReconnectConfig
from ..connection import Connection, ConnectionContext
from ..errors import ComponentError
from ..exceptions import ConnectionInactiveException
from ..message import Message
from ..path import ConnectionPath
from ..result import Ok, Result
from .component import load_component
from .database.entity import MessageDirection, MessageEntity, eid
from .database.manager import DatabaseManager
from .tasks import Tasklet


class ReceivedMessage(BaseModel):
    id: UUID
    timestamp: datetime
    content: str


class ReconnectScheduler:
    def __init__(self, config: ReconnectConfig) -> None:
        self.interval = (
            config.interval
            if isinstance(config.interval, timedelta)
            else timedelta(seconds=config.interval)
        )
        self.backoff: float = config.backoff if config.backoff is not None else 1
        self.max_interval: timedelta | None = None

        if config.max_interval:
            self.max_interval = (
                config.max_interval
                if isinstance(config.max_interval, timedelta)
                else timedelta(seconds=config.max_interval)
            )

        self._retries = 0

    def reset(self) -> None:
        self._retries = 0

    def next(self) -> timedelta:
        next = self.interval * self.backoff**self._retries
        self._retries += 1
        return next


class ConnectionHandle(Tasklet):
    MAX_RECEIVE_BUFFER_SIZE = 2500

    def __init__(self, context: ConnectionHandleContext) -> None:
        self._context = context
        self._reconnect = ReconnectScheduler(context.reconnect)
        self._instance: Connection | None = None
        self._state = ConnectionState.DISCONNECTED
        self._receive_buffer: list[ReceivedMessage] = []
        self._is_flushing = False
        self._last_message_timestamp: datetime | None = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> ConnectionPath:
        return self._context.path

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    async def load(self) -> Result[Connection, ComponentError]:
        if not self._instance:
            match load_component(Connection, self._context.component, self._context.parameters):
                case Ok(instance):
                    self._instance = instance
                    self._instance.setup(
                        ConnectionContext(
                            id=self._context.id,
                            path=self._context.path,
                        )
                    )
                case fail:
                    return fail

        return Ok(self._instance)

    async def connect(self) -> bool:
        if not self._instance:
            return False
        if self._state == ConnectionState.CONNECTED:
            return True

        self._state = ConnectionState.CONNECTING
        if await self._instance.connect():
            self._state = ConnectionState.CONNECTED
        else:
            self._state = ConnectionState.DISCONNECTED

        return self.connected

    async def disconnect(self) -> None:
        if not self._instance or self._state == ConnectionState.DISCONNECTED:
            return

        try:
            await self._instance.disconnect()
        finally:
            self._state = ConnectionState.DISCONNECTED

    async def send(self, data: str) -> Message:
        if not self._instance:
            raise ConnectionInactiveException("Connection is not active.")

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

        return Message.from_entity(entity)

    async def _tasklet_run(self) -> None:
        async def process_update() -> None:
            while True:
                await self._update()

        async def process_flush() -> None:
            while True:
                await anyio.sleep(0.1)
                if not self._is_flushing:
                    await self._flush()

        async with anyio.create_task_group() as group:
            group.start_soon(process_flush)
            group.start_soon(process_update)

    async def _tasklet_stop(self) -> None:
        await self.disconnect()
        await self._flush()

    async def _update(self) -> None:
        if not self._instance:
            return

        while not await self.connect():
            await anyio.sleep(self._reconnect.next().total_seconds())

        self._reconnect.reset()

        while self._state == ConnectionState.CONNECTED:
            await self._receive()

    async def _receive(self) -> None:
        if not self._instance:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            data = await self._instance.receive()
        except Exception:
            await self.disconnect()
            raise

        # Ensure timestamps are different.
        if self._last_message_timestamp:
            while self._last_message_timestamp == datetime.now(timezone.utc):
                await anyio.sleep(0)

        timestamp = datetime.now(timezone.utc)

        message = ReceivedMessage(
            id=eid(),
            timestamp=timestamp,
            content=data,
        )

        self._last_message_timestamp = timestamp
        self._receive_buffer.append(message)

        if not self._is_flushing and len(self._receive_buffer) >= self.MAX_RECEIVE_BUFFER_SIZE:
            await self._flush()

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


class ConnectionHandleContext(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    id: UUID
    path: ConnectionPath
    component: str | object
    parameters: dict[str, Any]
    database: DatabaseManager
    reconnect: ReconnectConfig


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
