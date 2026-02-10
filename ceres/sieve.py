from __future__ import annotations

import asyncio
import traceback
from abc import abstractmethod
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import field
from typing import TYPE_CHECKING, Generic, TypeAlias, cast, override

from pydantic import SkipValidation
from typing_extensions import TypeVar

from ceres._internal import util
from ceres._internal.manager import BaseComponentTaskManager
from ceres.data import DataObject, Name
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

    ParticleT = TypeVar("ParticleT", bound=Particle, covariant=True, default=Particle)
else:
    Message = object

    ParticleT = TypeVar("ParticleT", covariant=True, default=Particle)


class Sieve(DataObject, Generic[ParticleT]):
    @abstractmethod
    def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[ParticleT]: ...


MonoSieveFunction = Callable[[Message], ParticleT | None | Awaitable[ParticleT | None]]
PolySieveFunction = Callable[[AsyncIterable[Message]], AsyncIterable[ParticleT]]
SieveFunction: TypeAlias = MonoSieveFunction[ParticleT] | PolySieveFunction[ParticleT]


class FunctionalSieve(Sieve[ParticleT], Generic[ParticleT]):
    function: SkipValidation[SieveFunction[ParticleT]] = field(kw_only=False)

    @override
    async def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[ParticleT]:
        poly = self._get_poly()
        async for message in poly(messages):
            yield cast("ParticleT", message)

    def _get_poly(self) -> PolySieveFunction:
        import inspect

        signature = inspect.signature(self.function)
        annotations = inspect.get_annotations(self.function, eval_str=True)
        parameters = list(signature.parameters.values())
        if len(signature.parameters) != 1:
            raise ValueError("Sieve method must take exactly one parameter.")

        annotation = annotations.get(parameters[0].name)
        mono = util.is_subtype(annotation, Message)

        if mono:
            inner = cast("MonoSieveFunction", self.function)

            async def poly(messages: AsyncIterable[Message]) -> AsyncIterator[ParticleT]:
                async for message in messages:
                    result = await util.awaitify(inner(message))
                    if result is not None:
                        yield cast("ParticleT", result)

            poly.__name__ = self.function.__name__
            return poly

        return cast("PolySieveFunction", self.function)


if TYPE_CHECKING:
    from ceres.config import SieveConfig
else:
    SieveConfig = object


class ComponentSieveManager(BaseComponentTaskManager[SieveConfig]):
    __slots__ = ()

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
                        self.__system__.messages.stream.where(config.filter)
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
