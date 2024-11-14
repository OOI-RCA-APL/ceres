from abc import abstractmethod
from typing import TYPE_CHECKING, AsyncIterable, AsyncIterator, Generic, override

from typing_extensions import TypeVar

from ceres.data import ValidatedDataclass
from ceres.error import ParticleError
from ceres.message import Message
from ceres.particle import Particle

if TYPE_CHECKING:
    _T = TypeVar("_T", bound=Particle, covariant=True, default=Particle)
else:
    _T = TypeVar("_T", covariant=True, default=Particle)


class Sieve(ValidatedDataclass, Generic[_T]):
    @abstractmethod
    def read(self, messages: AsyncIterable[Message]) -> AsyncIterator[_T | ParticleError]: ...


class MonoSieve(Sieve[_T], Generic[_T]):
    @override
    async def read(
        self,
        messages: AsyncIterable[Message],
    ) -> AsyncIterator[_T | ParticleError]:
        async for message in messages:
            yield self.parse(message)

    def parse(self, message: Message) -> _T | ParticleError: ...
