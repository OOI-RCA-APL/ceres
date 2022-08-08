from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Generic, Optional, TypeVar

from .database import Database
from .tasks import Tasklet, defer


class Object(Tasklet, ABC):
    async def execute(self) -> None:
        while True:
            await defer()
            await self.update()

    @abstractmethod
    def update(self) -> Awaitable[None]:
        ...


ObjectT = TypeVar("ObjectT", bound=Object)


@dataclass(frozen=True)
class ObjectDescriptor(Generic[ObjectT]):
    name: str
    module: Optional[str] = None
    instance: Optional[ObjectT] = None
    worker: str = "default"


@dataclass(frozen=True)
class ObjectContext(Generic[ObjectT]):
    key: str
    database: Database
