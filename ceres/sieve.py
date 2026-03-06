import traceback
from abc import abstractmethod
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from dataclasses import field
from typing import TYPE_CHECKING, cast, override

from pydantic import SkipValidation

from ceres.__internal__.manager import BaseComponentTaskManager
from ceres.__internal__.utilities.exceptions import trace
from ceres.__internal__.utilities.typing import is_assignable
from ceres.concurrency import awaitify, sleep
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
else:
    Message = object

__all__ = [
    "Sieve",
    "MonoSieveFunction",
    "PolySieveFunction",
    "SieveFunction",
    "FunctionSieve",
    "SieveManager",
]


class Sieve[T = Particle](DataObject):
    @abstractmethod
    def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[T]: ...


type MonoSieveFunction[T: Particle = Particle] = Callable[[Message], T | None | Awaitable[T | None]]
type PolySieveFunction[T: Particle = Particle] = Callable[
    [AsyncIterable[Message]], AsyncIterable[T]
]
type SieveFunction[T: Particle = Particle] = MonoSieveFunction[T] | PolySieveFunction[T]


class FunctionSieve[T: Particle = Particle](Sieve[T]):
    function: SkipValidation[SieveFunction[T]] = field(kw_only=False)

    @override
    async def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[T]:
        poly = self._get_poly()
        async for message in poly(messages):
            yield cast("T", message)

    def _get_poly(self) -> PolySieveFunction:
        import inspect

        signature = inspect.signature(self.function)
        annotations = inspect.get_annotations(self.function, eval_str=True)
        parameters = list(signature.parameters.values())
        if len(signature.parameters) != 1:
            raise ValueError("Sieve method must take exactly one parameter.")

        annotation = annotations.get(parameters[0].name)
        mono = is_assignable(annotation, Message)

        if mono:
            inner = cast("MonoSieveFunction", self.function)

            async def poly(messages: AsyncIterable[Message]) -> AsyncIterator[T]:
                async for message in messages:
                    result = await awaitify(inner(message))
                    if result is not None:
                        yield cast("T", result)

            poly.__name__ = self.function.__name__
            return poly

        return cast("PolySieveFunction", self.function)


if TYPE_CHECKING:
    from ceres.config import SieveConfig
else:
    SieveConfig = object


class SieveManager(BaseComponentTaskManager[SieveConfig]):
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
                        traceback=trace(exception),
                    )
                    await sleep(config.retry_delay)
                    self.__system__.events.emit(SieveRetryEvent, sieve=config.name)
        finally:
            self.__system__.events.emit(SieveStoppedEvent, sieve=config.name)
