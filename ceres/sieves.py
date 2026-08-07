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
    "BufferSieveFunction",
    "SieveFunction",
    "FunctionSieve",
    "SieveManager",
]


class Sieve[T = Particle](DataObject):
    """Extract `Particle` instances from a stream of `Message` objects.

    Subclasses implement `process()` to consume an asynchronous stream of messages and yield
    parsed particles. A `Sieve` is the bridge between the raw `Message` data flowing from a
    `Connection` and the structured `Particle` objects that downstream consumers care about.
    """

    @abstractmethod
    def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[T]:
        """Consume `messages` and yield extracted particles.

        Args:
            messages: An asynchronous stream of `Message` objects to parse.

        Yields:
            Particles parsed from the message stream.
        """
        ...


type MonoSieveFunction[T: Particle = Particle] = Callable[[Message], T | None | Awaitable[T | None]]
"""A sieve function that parses a single `Particle` from a single `Message`.

The sieve calls this function once for each message received. Returning `None` signals that the
message did not represent a valid particle and should be skipped.
"""

type PolySieveFunction[T: Particle = Particle] = Callable[
    [AsyncIterable[Message]], AsyncIterable[T]
]
"""A sieve function that yields particles parsed from an asynchronous stream of `Message` objects.

Use this form when particle extraction needs cross-message state, for example when one particle
spans multiple messages.
"""

type BufferSieveFunction[T: Particle = Particle] = Callable[[Buffer], Iterable[T]]
"""A sieve function that yields particles extracted from a `Buffer` of accumulated connection data.

The sieve appends incoming message data to a `Buffer` and calls this function each time new data
arrives. Each yielded `Particle` must populate its `span` attribute, the sieve uses it to advance
the buffer past consumed bytes.
"""

type SieveFunction[T: Particle = Particle] = MonoSieveFunction[T] | PolySieveFunction[T]
"""Any callable usable as a `Sieve` function for parsing particles from messages or buffered data.
"""


class FunctionSieve[T: Particle = Particle](Sieve[T]):
    """A `Sieve` that delegates particle extraction to a user-supplied callable.

    The callable's parameter annotation determines how it is invoked. A `Message` parameter is
    treated as a `MonoSieveFunction`, an `AsyncIterable[Message]` parameter is treated as a
    `PolySieveFunction`, and a `Buffer` parameter is treated as a `BufferSieveFunction`.
    """

    function: SkipValidation[SieveFunction[T]] = field(kw_only=False)
    """The user-supplied callable used to parse particles."""
    buffer_size: ByteSize = Field(default=DEFAULT_BUFFER_SIZE, gt=0)
    """Number of bytes to keep in the buffer before dropping old data."""
    buffer_drop: ByteSize = Field(default=DEFAULT_BUFFER_DROP, gt=0)
    """Number of bytes to drop from the buffer when it exceeds `buffer_size`."""

    @override
    async def process(self, messages: AsyncIterable[Message]) -> AsyncIterator[T]:
        poly = self._get_poly_sieve_function()
        async for message in poly(messages):
            yield cast("T", message)

    def _get_poly_sieve_function(self) -> PolySieveFunction:
        """Return a `PolySieveFunction` adapter for `self.function`.

        Inspect the signature of `self.function` and wrap it as needed so the rest of the sieve
        can invoke it uniformly as a `PolySieveFunction`.

        Raises:
            ValueError: If `self.function` does not take exactly one parameter.
            TypeError: If the parameter's type annotation is not one of `Message`,
                `AsyncIterable[Message]`, or `Buffer`.
        """
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
                    # Drop old data once the buffer exceeds the configured size limit.
                    if buffer.size > self.buffer_size:
                        buffer.pop_to(self.buffer_size, self.buffer_drop)

                    # Track the furthest particle end so we can advance the buffer past all
                    # consumed bytes after iterating, even when particles arrive out of order.
                    end: int | None = None
                    for particle in inner(buffer):
                        if particle is None:
                            continue

                        span = particle.span
                        if span is None:
                            raise ValueError(
                                "Buffer sieves must assign `span` of yielded particles."
                            )

                        if end is None or span[1] > end:
                            end = span[1]

                        yield cast("T", particle)

                    # Drop bytes up to the end of the furthest particle span so the next
                    # iteration only sees unparsed data.
                    if end is not None:
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
    """Manage the lifecycle of `Sieve` instances within a component.

    Add/remove sieve configurations and run each one as a managed task, restarting on failure
    according to the configuration's retry policy.
    """

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
        """Run the sieve described by `config`, restarting on failure per its retry policy.

        Emit lifecycle events (`SieveStartedEvent`, `SieveStoppedEvent`, retry events) and
        forward each parsed particle through `ParticleEvent`. Optionally store particles
        when `config.stored` is true.
        """
        self.__system__.events.emit(SieveStartedEvent, sieve=config.name)
        retry = 0

        try:
            while True:
                try:
                    sieve = config.create(self.__system__.component)
                    async for current in sieve.process(
                        self.__system__.messages.stream.where(config.filter)
                    ):
                        if config.stored:
                            self.__system__.store(current)
                        self.__system__.events.emit(ParticleEvent, particle=current)
                except Exception as exception:
                    # Stop retrying once we've exhausted the configured retry budget.
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
