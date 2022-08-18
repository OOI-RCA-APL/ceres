from abc import ABC, abstractmethod
from datetime import timedelta
from enum import Enum
from typing import Any, Awaitable, Optional, cast

import anyio

from .component import Component, load_component
from .config import ConnectionConfig, ReconnectConfig
from .database import Database
from .exceptions import ConnectionInactiveException
from .message import Message
from .tasks import Tasklet, defer


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
    def send(self, data: str) -> Awaitable[Message]:
        ...

    @abstractmethod
    def receive(self) -> Awaitable[Message]:
        ...


class ConnectionHandle(Tasklet):
    def __init__(
        self,
        config: ConnectionConfig,
        database: Database,
    ) -> None:
        self._config = config
        self._database = database
        self._reconnect = ReconnectScheduler(config.reconnect)
        self._connection: Optional[Connection] = None
        self._connectivity = Connectivity.DISCONNECTED

    @property
    def config(self) -> ConnectionConfig:
        return self._config

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

        await self._connection.disconnect()

    async def send(self, data: str) -> Message:
        if not self._connection:
            raise ConnectionInactiveException("Connection is not active.")

        return await self._connection.send(data)

    async def receive(self) -> Message:
        if not self._connection:
            raise ConnectionInactiveException("Connection is not active.")

        return await self._connection.receive()
        ...

    async def load(self) -> None:
        if self._connection:
            return

        self._connection = await load_component(self._config, cast(Any, Connection))

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
            message = await self._connection.receive()
            print(message)

    async def execute(self) -> None:
        while True:
            await self.update()
            await defer()
