from abc import ABC, abstractmethod
from asyncio import Queue as AsyncQueue
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Awaitable, Generic, Optional, TypeVar, Union, final

import anyio

# from .generic import MessageT
from .object import Object, ObjectDescriptor


class Connectivity(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


class ReconnectStrategy(ABC):
    def __init__(
        self,
        *,
        interval: Union[int, float, timedelta],
        backoff: Optional[float] = None,
        max: Optional[Union[int, float, timedelta]] = None,
    ) -> None:
        self.interval = interval if isinstance(interval, timedelta) else timedelta(seconds=interval)
        self.backoff: float = backoff if backoff is not None else 1
        self.max: Optional[timedelta] = None

        if max:
            self.max = max if isinstance(max, timedelta) else timedelta(seconds=max)

        self._retries = 0

    def reset(self) -> None:
        self._retries = 0

    def next(self) -> timedelta:
        next = self.interval * self.backoff**self._retries
        self._retries += 1
        return next


MessageT = TypeVar("MessageT")


@dataclass
class ConnectionInternal(Generic[MessageT]):
    outputs: AsyncQueue[MessageT] = field(default_factory=AsyncQueue)
    connectivity: Connectivity = Connectivity.DISCONNECTED
    reconnect_strategy: ReconnectStrategy = field(
        default_factory=lambda: ReconnectStrategy(
            interval=1,
            backoff=2,
            max=60,
        )
    )


class Connection(Generic[MessageT], Object, ABC):
    def __init__(self, reconnect_strategy: Optional[ReconnectStrategy] = None) -> None:
        super().__init__()
        if reconnect_strategy:
            self.__internal__.reconnect_strategy = reconnect_strategy

    @property
    def connectivity(self) -> Connectivity:
        return self.__internal__.connectivity

    @property
    def connected(self) -> bool:
        return self.__internal__.connectivity == Connectivity.CONNECTED

    @property
    def __internal__(self) -> ConnectionInternal[MessageT]:
        if internal := self.__dict__.get("__connection__"):
            return internal

        internal = ConnectionInternal()
        self.__dict__["__connection__"] = internal
        return internal

    @abstractmethod
    def connect(self) -> Awaitable[bool]:
        ...

    @abstractmethod
    def send(self, message: MessageT) -> Awaitable[None]:
        ...

    @abstractmethod
    def receive(self) -> Awaitable[MessageT]:
        ...

    @final
    async def get(self) -> MessageT:
        return await self.__internal__.outputs.get()

    @final
    async def update(self) -> None:
        while not self.connected:
            self.__internal__.connectivity = Connectivity.CONNECTING
            if await self.connect():
                self.__internal__.connectivity = Connectivity.CONNECTED
                break

            self.__internal__.connectivity = Connectivity.DISCONNECTED
            await anyio.sleep(self.__internal__.reconnect_strategy.next().total_seconds())

        self.__internal__.reconnect_strategy.reset()

        while self.connected:
            message = await self.receive()
            return self.__internal__.outputs.put_nowait(message)


@dataclass(frozen=True)
class ConnectionDescriptor(ObjectDescriptor[Connection]):
    pass
