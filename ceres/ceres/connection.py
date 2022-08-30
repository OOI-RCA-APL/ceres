from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import anyio

from .component import Component, ComponentLoadError
from .config import ReconnectConfig
from .data import DataObject
from .database import DatabaseManager
from .database.entity import MessageEntity, eid
from .exceptions import ConnectionInactiveException
from .message import Message
from .path import ConnectionPath
from .result import Ok, Result
from .tasks import Tasklet


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


class Connection(Component, ABC):
    @abstractmethod
    async def connect(self) -> bool:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def send(self, data: str) -> None:
        ...

    @abstractmethod
    async def receive(self) -> str:
        ...


class ConnectionContext(DataObject):
    class Config:
        arbitrary_types_allowed = True

    id: UUID
    path: ConnectionPath
    component: str | object
    parameters: dict[str, Any]
    database: DatabaseManager
    reconnect: ReconnectConfig


ConnectionState = Literal["disconnected", "connecting", "connected"]


class ReceivedMessage(DataObject):
    id: UUID
    timestamp: datetime
    content: str


class ConnectionHandle(Tasklet):
    MAX_RECEIVE_BUFFER_SIZE = 2500

    def __init__(self, context: ConnectionContext) -> None:
        self._context = context
        self._reconnect = ReconnectScheduler(context.reconnect)
        self._connection: Connection | None = None
        self._state: ConnectionState = "disconnected"
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
        return self._state == "connected"

    def load(self) -> Result[Connection, ComponentLoadError]:
        if not self._connection:
            if not (
                result := Connection.load(
                    self._context.component,
                    self._context.parameters,
                )
            ).ok:
                return result

            self._connection = result.value

        return Ok.create(self._connection)

    async def send(self, data: str) -> Message:
        if not self._connection:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            await self._connection.send(data)
        except Exception:
            await self._disconnect()
            raise

        async with self._context.database.session() as session:
            session.add(
                entity := MessageEntity(
                    connection_id=self._context.id,
                    timestamp=datetime.now(timezone.utc),
                    direction="receive",
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
        await self._disconnect()
        await self._flush()

    async def _update(self) -> None:
        if not self._connection:
            return

        while not self.connected:
            self._state = "connecting"
            if await self._connection.connect():
                self._state = "connected"
                break

            self._state = "disconnected"
            await anyio.sleep(self._reconnect.next().total_seconds())

        self._reconnect.reset()

        while self.connected:
            await self._receive()

    async def _connect(self) -> bool:
        if not self._connection:
            return False
        if self.connected:
            return True

        self._state = "connecting"
        if await self._connection.connect():
            self._state = "connecting"
        else:
            self._state = "disconnected"

        return self.connected

    async def _disconnect(self) -> None:
        if not self._connection:
            return

        try:
            await self._connection.disconnect()
        finally:
            self._state = "disconnected"

    async def _receive(self) -> None:
        if not self._connection:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            data = await self._connection.receive()
        except Exception:
            await self._disconnect()
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
                            direction="receive",
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
