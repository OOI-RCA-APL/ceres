from abc import abstractmethod, abstractproperty
from typing import AsyncIterator
from uuid import UUID


class Subscription(AsyncIterator[object]):
    @abstractproperty
    def id(self) -> UUID:
        ...

    @abstractmethod
    async def get(self) -> object:
        ...
