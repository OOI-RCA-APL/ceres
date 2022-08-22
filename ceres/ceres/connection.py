from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import Enum
from time import sleep
from typing import Any, Awaitable, List, Optional, Union, cast
from uuid import UUID

import anyio

from .component import Component, load_component
from .config import ReconnectConfig
from .data import DataObject
from .database import Database
from .database.entity import MessageEntity, eid
from .exceptions import ConnectionInactiveException
from .message import Message
from .path import ConnectionPath
from .tasks import Tasklet

MAX_RECEIVE_BUFFER_SIZE = 2500


class Connectivity(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


class ReconnectScheduler:
    def __init__(self, config: ReconnectConfig) -> None:
        self.interval = (
            config.interval
            if isinstance(config.interval, timedelta)
            else timedelta(seconds=config.interval)
        )
        self.backoff: float = config.backoff if config.backoff is not None else 1
        self.max_interval: Optional[timedelta] = None

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
    def connect(self) -> Awaitable[bool]:
        ...

    @abstractmethod
    def disconnect(self) -> Awaitable[None]:
        ...

    @abstractmethod
    def send(self, data: str) -> Awaitable[None]:
        ...

    @abstractmethod
    def receive(self) -> Awaitable[str]:
        ...


class ConnectionContext(DataObject):
    class Config:
        arbitrary_types_allowed = True

    id: UUID
    path: ConnectionPath
    component: Union[str, "Connection"]
    database: Database
    reconnect: ReconnectConfig


class ReceivedMessage(DataObject):
    id: UUID
    timestamp: datetime
    content: str


class ConnectionHandle(Tasklet):
    def __init__(self, context: ConnectionContext) -> None:
        self._context = context
        self._reconnect = ReconnectScheduler(context.reconnect)
        self._connection: Optional[Connection] = None
        self._connectivity = Connectivity.DISCONNECTED
        self._receive_buffer: List[ReceivedMessage] = []
        self._is_flushing = False

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> ConnectionPath:
        return self._context.path

    @property
    def connectivity(self) -> Connectivity:
        return self._connectivity

    @property
    def connected(self) -> bool:
        return self._connectivity == Connectivity.CONNECTED

    async def connect(self) -> bool:
        if not self._connection:
            return False
        if self.connected:
            return True

        self._connectivity = Connectivity.CONNECTING
        if await self._connection.connect():
            self._connectivity = Connectivity.CONNECTED
        else:
            self._connectivity = Connectivity.DISCONNECTED

        return self.connected

    async def disconnect(self) -> None:
        if not self._connection:
            return

        try:
            await self._connection.disconnect()
        finally:
            self._connectivity = Connectivity.DISCONNECTED

    async def send(self, data: str) -> Message:
        if not self._connection:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            await self._connection.send(data)
        except Exception:
            await self.disconnect()
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

    async def receive(self) -> None:
        if not self._connection:
            raise ConnectionInactiveException("Connection is not active.")

        try:
            data = await self._connection.receive()
        except Exception:
            await self.disconnect()
            raise

        sleep(1 / 1000000)
        message = ReceivedMessage(
            id=eid(),
            timestamp=datetime.now(timezone.utc),
            content=data,
        )

        self._receive_buffer.append(message)

        if not self._is_flushing and len(self._receive_buffer) >= MAX_RECEIVE_BUFFER_SIZE:
            await self.flush()

    async def load(self) -> None:
        if self._connection:
            return

        self._connection = await load_component(self._context.component, cast(Any, Connection))

    async def update(self) -> None:
        if not self._connection:
            return

        while not self.connected:
            self._connectivity = Connectivity.CONNECTING
            if await self._connection.connect():
                self._connectivity = Connectivity.CONNECTED
                break

            self._connectivity = Connectivity.DISCONNECTED
            await anyio.sleep(self._reconnect.next().total_seconds())

        self._reconnect.reset()

        while self.connected:
            await self.receive()

    async def flush(self) -> None:
        if not self._receive_buffer:
            return

        self._is_flushing = True

        messages = self._receive_buffer
        self._receive_buffer = []

        async def execute() -> None:
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

        try:
            await execute()
            # anyio.to_thread(execute)
        except Exception:
            self._receive_buffer = [*messages, *self._receive_buffer]
        finally:
            self._is_flushing = False

    async def execute(self) -> None:
        async def process_update() -> None:
            while True:
                await self.update()

        async def process_flush() -> None:
            while True:
                await anyio.sleep(0.1)
                if not self._is_flushing:
                    await self.flush()

        async with anyio.create_task_group() as group:
            group.start_soon(process_flush)
            group.start_soon(process_update)

    async def teardown(self) -> None:
        await self.disconnect()
        await self.flush()
