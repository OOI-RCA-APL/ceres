import asyncio
from abc import ABC, abstractmethod
from asyncio import FIRST_COMPLETED, Task
from asyncio import Event as AsyncEvent
from dataclasses import dataclass, field
from typing import Callable, cast

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
        return not self.__tasklet__.stopped.is_set()

    @property
    def stopping(self) -> bool:
        return self.__tasklet__.stopping.is_set()

    @abstractmethod
    async def __run__(self) -> None:
        ...

    @abstractmethod
    async def __stop__(self) -> None:
        ...

    async def __done__(self) -> None:
        pass

    @property
    def __tasklet__(self) -> TaskletInternal:
        if internal := self.__dict__.get(_INTERNAL_ATTRIBUTE_NAME):
            return cast(TaskletInternal, internal)

        internal = TaskletInternal()
        internal.stopping.set()
        internal.stopped.set()

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

        task_run = asyncio.create_task(self.__run__())
        task_wait_until_stopping = asyncio.create_task(self.__tasklet__.stopping.wait())

        async def main() -> None:
            await asyncio.wait(
                [
                    task_run,
                    task_wait_until_stopping,
                ],
                return_when=FIRST_COMPLETED,
            )

            try:
                if task_run.done():
                    try:
                        task_run.result()
                    except Exception as exception:
                        self.__tasklet__.exception = exception
                        if on_exception:
                            on_exception(self, exception)
            finally:
                self.__tasklet__.stopping.set()

                while not task_run.done() or not task_wait_until_stopping.done():
                    task_run.cancel()
                    task_wait_until_stopping.cancel()
                    await asyncio.sleep(0.025)

                try:
                    await self.__stop__()
                finally:
                    try:
                        await self.__done__()
                    finally:
                        if on_completed:
                            on_completed(self)

                        self.__tasklet__.task = None
                        self.__tasklet__.stopped.set()

        self.__tasklet__.task = asyncio.create_task(main(), name=str(type(self)))

    async def stop(self, raise_exceptions: bool = False) -> None:
        self.__tasklet__.stopping.set()
        await self.__tasklet__.stopped.wait()
        if raise_exceptions and self.__tasklet__.exception:
            raise self.__tasklet__.exception

    async def wait_until_stopping(self) -> None:
        await self.__tasklet__.stopping.wait()

    async def wait_until_stopped(self, raise_exceptions: bool = True) -> None:
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
        await self.wait_until_stopped(raise_exceptions)
