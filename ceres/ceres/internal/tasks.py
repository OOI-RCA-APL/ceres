from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from asyncio import AbstractEventLoop, Event, Task
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar, cast

import uvloop


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
        uvloop.install()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop


@dataclass
class TaskletInternal:
    task: Task[Any] | None = None
    stop: Event = field(default_factory=Event)
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
        on_completed: Callable[[TaskletT], None | Awaitable[None]] | None = None,
        on_exception: Callable[[TaskletT, BaseException], None | Awaitable[None]] | None = None,
    ) -> None:
        if self.__tasklet__.task:
            return

        self.__tasklet__.exception = None
        self.__tasklet__.stop.clear()

        ensure_event_loop()

        async def task() -> None:
            await self._tasklet_run()
            await self._tasklet_stop()

        def done(task: Task[Any]) -> None:
            self.__tasklet__.task = None
            self.__tasklet__.stop.set()
            self.__tasklet__.exception = None

            if task.cancelled():
                return

            if exception := task.exception():
                self.__tasklet__.exception = exception
                if on_exception:
                    on_exception(self, exception)

            if on_completed:
                on_completed(self)

        self.__tasklet__.task = asyncio.create_task(task(), name=str(type(self)))
        self.__tasklet__.task.add_done_callback(done)

    async def stop(self, raise_exceptions: bool = False) -> None:
        if self.__tasklet__.task:
            self.__tasklet__.task = None

            if not self.__tasklet__.stop.is_set():
                self.__tasklet__.stop.set()

            try:
                await self._tasklet_stop()
            finally:
                await self.__tasklet__.stop.wait()

        if raise_exceptions and self.__tasklet__.exception:
            raise self.__tasklet__.exception

    async def join(self, raise_exceptions: bool = True) -> None:
        if not self.__tasklet__.task:
            return

        await self.__tasklet__.stop.wait()
        if raise_exceptions and self.__tasklet__.exception:
            raise self.__tasklet__.exception

    async def run(
        self: TaskletT,
        *,
        raise_exceptions: bool = True,
        on_completed: Callable[[TaskletT], None | Awaitable[None]] | None = None,
        on_exception: Callable[[TaskletT, BaseException], None | Awaitable[None]] | None = None,
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
