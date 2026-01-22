from __future__ import annotations

import asyncio
import traceback
from abc import abstractmethod
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import TYPE_CHECKING, Generic, override

from pydantic import SkipValidation
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.manager import BaseComponentTaskManager
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
else:
    SieveConfig = object


class ComponentSieveManager(BaseComponentTaskManager[SieveConfig]):
    @override
    def add(self, config: SieveConfig) -> None:
        super().add(config)
        if config.name is not None:
            self.__system__.events.emit(SieveAddedEvent, sieve=config.name)

    @override
    async def remove(self, name: Name) -> SieveConfig | None:
        config = await super().remove(name)
        if config is not None:
            self.__system__.events.emit(SieveRemovedEvent, sieve=name)
            config.system = None

        return config

    @override
    async def process(self, config: SieveConfig) -> None:
        self.__system__.events.emit(SieveStartedEvent, sieve=config.name)
        retry = 0

        try:
            sieve = config.create(self.__system__.component)
            while True:
                try:
                    async for current in sieve.process(
                        self.__system__.messages.follow(config.filter)
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
