from abc import abstractmethod
from typing import AsyncIterable, AsyncIterator, override

from ceres.data import ImmutableDataObject
from ceres.error import ParticleError
from ceres.message import Message
from ceres.particle import Particle


class DynamicSieve(ImmutableDataObject):
    @abstractmethod
    def read(self, messages: AsyncIterable[Message]) -> AsyncIterator[Particle | ParticleError]: ...


class Sieve[T: Particle](DynamicSieve):
    @abstractmethod
    @override
    def read(self, messages: AsyncIterable[Message]) -> AsyncIterator[T | ParticleError]: ...


class MonoSieve[T: Particle](Sieve[T]):
    @override
    async def read(
        self,
        messages: AsyncIterable[Message],
    ) -> AsyncIterator[T | ParticleError]:
        async for message in messages:
            yield self.parse(message)

    def parse(self, message: Message) -> T | ParticleError: ...
