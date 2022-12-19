import asyncio
from abc import ABC, abstractmethod
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from asyncio import Task
from dataclasses import dataclass, field
from typing import Any, Callable, cast

from typing_extensions import Self


@dataclass
class TaskletInternal:
    task: Task[None] | None = None
    stopping: AsyncEvent = field(default_factory=AsyncEvent)
    stopped: AsyncEvent = field(default_factory=AsyncEvent)
    exception: BaseException | None = None


_INTERNAL_ATTRIBUTE_NAME = "__tasklet__"


class Tasklet(ABC):
    @property
    def running(self) -> bool:
        return self.__tasklet__.task is not None

    @property
    def stopping(self) -> bool:
        return self.running and self.__tasklet__.stopping.is_set()

    @abstractmethod
    async def __run__(self) -> None:
        ...

    @abstractmethod
    async def __stop__(self) -> None:
        ...

    @property
    def __tasklet__(self) -> TaskletInternal:
        if internal := self.__dict__.get(_INTERNAL_ATTRIBUTE_NAME):
            return cast(TaskletInternal, internal)

        internal = TaskletInternal()
        self.__dict__[_INTERNAL_ATTRIBUTE_NAME] = internal
        return internal

    def start(
        self,
        *,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
    ) -> None:
        if self.__tasklet__.task:
            return

        self.__tasklet__.exception = None
        self.__tasklet__.stopping.clear()
        self.__tasklet__.stopped.clear()

        run_task = asyncio.create_task(self.__run__())
        stopping_task = asyncio.create_task(self.__tasklet__.stopping.wait())

        async def main() -> None:
            done, _ = await asyncio.wait(
                [
                    run_task,
                    cast(Any, stopping_task),
                ],
                return_when=FIRST_COMPLETED,
            )

            try:
                if run_task in done:
                    try:
                        run_task.result()
                    except Exception as exception:
                        self.__tasklet__.exception = exception
                        if on_exception:
                            on_exception(self, exception)
                else:
                    run_task.cancel()

                if stopping_task in done:
                    stopping_task.result()
                else:
                    stopping_task.cancel()
            finally:
                try:
                    await self.__stop__()
                finally:
                    self.__tasklet__.task = None
                    self.__tasklet__.stopping.set()
                    self.__tasklet__.stopped.set()

                    if on_completed:
                        on_completed(self)

        self.__tasklet__.task = asyncio.create_task(main(), name=str(type(self)))

    async def stop(self, raise_exceptions: bool = False) -> None:
        if not self.__tasklet__.task:
            return

        self.__tasklet__.task = None
        self.__tasklet__.stopping.set()
        await self.__tasklet__.stopped.wait()
        if raise_exceptions and self.__tasklet__.exception:
            raise self.__tasklet__.exception

    async def join(self, raise_exceptions: bool = True) -> None:
        if not self.__tasklet__.task:
            return

        await self.__tasklet__.stopped.wait()
        if raise_exceptions and self.__tasklet__.exception:
            raise self.__tasklet__.exception

    async def run(
        self,
        *,
        raise_exceptions: bool = True,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
    ) -> None:
        self.start(
            on_completed=on_completed,
            on_exception=on_exception,
        )
        await self.join(raise_exceptions)
