from abc import abstractmethod
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
)
from dataclasses import field
from typing import TYPE_CHECKING, cast, override

from pydantic import ByteSize, Field, SkipValidation

from ceres.__internal__.manager import BaseComponentTaskManager
from ceres.__internal__.utilities.typing import is_assignable
from ceres.concurrency import awaitify, sleep
from ceres.connection.buffer import Buffer
from ceres.constants import DEFAULT_BUFFER_DROP, DEFAULT_BUFFER_SIZE
from ceres.data import DataObject, Name
from ceres.error import trace
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
from ceres.message import Message
from ceres.particle import Particle

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
type BufferSieveFunction[T: Particle = Particle] = Callable[[Buffer], Iterable[T]]
type SieveFunction[T: Particle = Particle] = MonoSieveFunction[T] | PolySieveFunction[T]


class FunctionSieve[T: Particle = Particle](Sieve[T]):
    function: SkipValidation[SieveFunction[T]] = field(kw_only=False)
    buffer_size: ByteSize = Field(default=DEFAULT_BUFFER_SIZE, gt=0)
    buffer_drop: ByteSize = Field(default=DEFAULT_BUFFER_DROP, gt=0)

    @override
    async def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[T]:
        poly = self._get_poly_sieve_function()
        async for message in poly(messages):
            yield cast("T", message)

    def _get_poly_sieve_function(self) -> PolySieveFunction:
        import inspect

        signature = inspect.signature(self.function)
        annotations = inspect.get_annotations(self.function, eval_str=True)
        parameters = list(signature.parameters.values())
        if len(signature.parameters) != 1:
            raise ValueError("Sieve method must take exactly one parameter.")

        annotation = annotations.get(parameters[0].name)

        poly: PolySieveFunction

        if is_assignable(annotation, AsyncIterable):
            poly = self.function  # type: ignore
        elif is_assignable(annotation, Message):
            inner = cast("MonoSieveFunction", self.function)

            async def poly(messages: AsyncIterable[Message]) -> AsyncGenerator[T]:
                async for message in messages:
                    result = await awaitify(inner(message))
                    if result is not None:
                        yield cast("T", result)
        elif is_assignable(annotation, Buffer):
            inner = cast("BufferSieveFunction", self.function)

            async def poly(messages: AsyncIterable[Message]) -> AsyncGenerator[T]:
                buffer = Buffer()

                async for message in messages:
                    buffer.push(message.data, message.timestamp)
                    if buffer.size > self.buffer_size:
                        buffer.pop_to(self.buffer_size, self.buffer_drop)

                    span: tuple[int, int] | None = None
                    for particle in inner(buffer):
                        span = particle.span
                        if span is None:
                            raise ValueError(
                                "Buffer sieves must assign `span` of yielded particles."
                            )

                        yield cast("T", particle)

                    # Remove data up to the end of the last particle span.
                    if span is not None:
                        _, end = span
                        buffer.pop(end)
        else:
            raise TypeError(
                f"Unrecognized sieve function signature `{inspect.signature(self.function)}`."
            )

        if poly is not self.function:
            poly.__name__ = self.function.__name__

        return poly


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
            while True:
                try:
                    sieve = config.create(self.__system__.component)
                    async for current in sieve.process(
                        self.__system__.messages.stream.where(config.filter)
                    ):
                        self.__system__.store(current)
                        self.__system__.events.emit(ParticleEvent, particle=current)
                except Exception as exception:
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
                        exception=trace(exception),
                    )
                    await sleep(config.retry_delay)
                    self.__system__.events.emit(SieveRetryEvent, sieve=config.name)
        finally:
            self.__system__.events.emit(SieveStoppedEvent, sieve=config.name)
