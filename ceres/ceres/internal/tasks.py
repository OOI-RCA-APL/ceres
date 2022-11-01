import asyncio
from abc import ABC, abstractmethod
from asyncio import FIRST_COMPLETED, AbstractEventLoop, Event, Task
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, cast


def event_loop_exists() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def ensure_event_loop() -> AbstractEventLoop:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            import uvloop

            uvloop.install()
        except Exception:
            pass

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop


@dataclass
class TaskletInternal:
    task: Task[Any] | None = None
    stopping: Event = field(default_factory=Event)
    stopped: Event = field(default_factory=Event)
    exception: BaseException | None = None


TASKLET_INTERNAL_ATTRIBUTE_NAME = "__tasklet_internal__"

TaskletT = TypeVar("TaskletT", bound="Tasklet")


class Tasklet(ABC):
    @property
    def running(self) -> bool:
        return self.__tasklet__.task is not None

    @property
    def __tasklet__(self) -> TaskletInternal:
        if internal := self.__dict__.get(TASKLET_INTERNAL_ATTRIBUTE_NAME):
            return cast(TaskletInternal, internal)

        internal = TaskletInternal()
        self.__dict__[TASKLET_INTERNAL_ATTRIBUTE_NAME] = internal
        return internal

    def start(
        self: TaskletT,
        *,
        on_completed: Callable[[TaskletT], None] | None = None,
        on_exception: Callable[[TaskletT, BaseException], None] | None = None,
    ) -> None:
        if self.__tasklet__.task:
            return

        self.__tasklet__.exception = None
        self.__tasklet__.stopping.clear()
        self.__tasklet__.stopped.clear()

        run_task = asyncio.create_task(self._tasklet_run())
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
                    await self._tasklet_stop()
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
        self: TaskletT,
        *,
        raise_exceptions: bool = True,
        on_completed: Callable[[TaskletT], None] | None = None,
        on_exception: Callable[[TaskletT, BaseException], None] | None = None,
    ) -> None:
        self.start(
            on_completed=on_completed,
            on_exception=on_exception,
        )
        await self.join(raise_exceptions)

    @abstractmethod
    async def _tasklet_run(self) -> None:
        ...

    @abstractmethod
    async def _tasklet_stop(self) -> None:
        ...
