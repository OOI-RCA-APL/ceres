from asyncio import Queue as AsyncQueue
from typing import AsyncIterator
from uuid import UUID

from ..subscription import Subscription


class QueueSubscription(Subscription):
    def __init__(self, *, id: UUID, queue: AsyncQueue[object]) -> None:
        self.__id = id
        self.__queue = queue

    @property
    def id(self) -> UUID:
        return self.__id

    def __aiter__(self) -> AsyncIterator[object]:
        return self

    async def __anext__(self) -> object:
        return await self.get()

    async def get(self) -> object:
        value = await self.__queue.get()
        self.__queue.task_done()
        return value
