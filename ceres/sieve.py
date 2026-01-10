from __future__ import annotations

import asyncio
import traceback
from abc import abstractmethod
from asyncio import Task
from typing import TYPE_CHECKING, AsyncIterable, AsyncIterator, Callable, Generic, override

from pydantic import SkipValidation
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.manager import BaseComponentManager
from ceres.channel import Channel
from ceres.data import Name, ValidatedDataclass
from ceres.event import (
    ParticleEvent,
    SieveAddedEvent,
    SieveExceptionEvent,
    SieveRemovedEvent,
    SieveRetryEvent,
    SieveRetryPendingEvent,
    SieveStartedEvent,
    SieveStoppedEvent,
)
from ceres.particle import Particle

if TYPE_CHECKING:
    from ceres._internal.protocols import ComponentSource
    from ceres.message import Message

    _T = TypeVar("_T", bound=Particle, covariant=True, default=Particle)
else:
    Message = object

    _T = TypeVar("_T", covariant=True, default=Particle)


class Sieve(ValidatedDataclass, Generic[_T]):
    @abstractmethod
    def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[_T]: ...


class MethodSieve(Sieve[_T], Generic[_T]):
    method: SkipValidation[Callable[[AsyncIterable[Message]], AsyncIterator[_T]]]

    @override
    async def process(
        self,
        messages: AsyncIterable[Message],
    ) -> AsyncIterator[_T]:
        async for message in self.method(messages):
            yield message


if TYPE_CHECKING:
    from ceres.config import SieveConfig


class ComponentSieveManager(BaseComponentManager):
    __slots__ = (
        "__configs",
        "__runners",
        "__running",
        "__stopping",
        "__syncs",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__configs: dict[Name, SieveConfig] = {}
        self.__runners: dict[Name, Task[None]] = {}
        self.__running = False
        self.__stopping = False
        self.__syncs: Channel[SieveConfig] = Channel()

    @property
    def count(self) -> int:
        return len(self.__configs)

    async def __run__(self) -> None:
        self.__running = True
        try:
            await self.__sync_runners()
            await util.sleep_forever()
            async for _ in self.__syncs:
                await self.__sync_runners()
        finally:
            self.__stopping = True
            try:
                await util.cancel(self.__runners.values())
                self.__runners.clear()
            finally:
                self.__running = False
                self.__stopping = False

    def add(self, sieve: SieveConfig) -> None:
        assert sieve.name not in self.__configs
        self.__configs[sieve.name] = sieve
        self.__system__.events.emit(SieveAddedEvent, sieve=sieve.name)
        if self.__running and not self.__stopping:
            self.__syncs.put(sieve)

    def get(self, name: Name) -> SieveConfig | None:
        return self.__configs.get(name)

    def get_all(self) -> list[SieveConfig]:
        return list(self.__configs.values())

    async def remove(self, name: Name) -> SieveConfig | None:
        runner = self.__runners.get(name)
        if runner is not None:
            await util.cancel(runner)
            self.__runners.pop(name, None)

        config = self.__configs.pop(name, None)
        self.__system__.events.emit(SieveRemovedEvent, sieve=name)
        return config

    async def clear(self) -> None:
        await self.__clear_runners()
        self.__configs.clear()

    async def __clear_runners(self) -> None:
        await util.cancel(self.__runners.values())
        self.__runners.clear()

    async def __remove_runner(self, name: Name) -> asyncio.Task[None] | None:
        runner = self.__runners.get(name)
        if runner is not None:
            await util.cancel(runner)
            self.__runners.pop(name, None)

        return runner

    async def __create_runner(self, config: SieveConfig) -> asyncio.Task[None]:
        runner = asyncio.create_task(self.__run(config), name=config.name + "-task")
        self.__runners[config.name] = runner
        return runner

    async def __sync_runners(self) -> None:
        for config in self.__configs.values():
            await self.__create_runner(config)

    async def __run(self, config: SieveConfig) -> None:
        self.__system__.events.emit(SieveStartedEvent, sieve=config.name)
        retry = 0

        try:
            sieve = config.create(self.__system__.component)
            while True:
                try:
                    async for current in sieve.process(
                        self.__system__.messages.follow(filter=config.filter)
                    ):
                        self.__system__.store(current)
                        self.__system__.events.emit(ParticleEvent, particle=current)
                except Exception as exception:
                    traceback.print_exc()
                    if config.retries is not None:
                        if retry >= config.retries:
                            break

                    self.__system__.events.emit(
                        SieveRetryPendingEvent,
                        sieve=config.name,
                        delay=config.retry_delay,
                    )
                    retry += 1

                    self.__system__.events.emit(
                        SieveExceptionEvent,
                        sieve=config.name,
                        traceback=util.get_traceback(exception),
                    )
                    await asyncio.sleep(config.retry_delay.total_seconds())
                    self.__system__.events.emit(SieveRetryEvent, sieve=config.name)
        finally:
            self.__system__.events.emit(SieveStoppedEvent, sieve=config.name)
