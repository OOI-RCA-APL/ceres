import inspect
import traceback
from asyncio import Queue as AsyncQueue
from logging import Logger
from typing import Awaitable, Callable, final

from ceres.events import Event
from ceres.listener import ListenerBinding


@final
class EventProcessor:
    __slots__ = (
        "__binding",
        "__handler",
        "__handler_arity",
        "__logger",
        "__queue",
    )

    def __init__(
        self,
        *,
        binding: ListenerBinding,
        handler: Callable[[Event], None | Awaitable[None]] | Callable[[], None | Awaitable[None]],
        logger: Logger,
    ) -> None:
        self.__binding = binding
        self.__handler = handler
        self.__handler_arity = len(inspect.signature(self.__handler).parameters)
        self.__logger = logger
        self.__queue: AsyncQueue[Event] = AsyncQueue()

    @property
    def binding(self) -> ListenerBinding:
        return self.__binding

    @property
    def idle(self) -> bool:
        return self.__queue._finished.is_set()  # type: ignore

    def put(self, event: Event) -> None:
        self.__queue.put_nowait(event)

    def clear(self) -> None:
        while not self.__queue.empty():
            self.__queue.get_nowait()
            self.__queue.task_done()

    async def run(self) -> None:
        while True:
            event = await self.__queue.get()

            try:
                result = self.__handler(*[event][: self.__handler_arity])
                if inspect.iscoroutine(result):
                    await result
            except Exception:
                self.__logger.error(
                    f"An exception occurred while processing event {event}: "
                    f"{traceback.format_exc()}"
                )
            finally:
                self.__queue.task_done()

    async def wait_until_empty(self) -> None:
        if self.__queue.empty():
            return

        await self.__queue.join()
