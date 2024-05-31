from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from asyncio import Event as AsyncEvent
from asyncio import Task
from dataclasses import dataclass, field
from typing import Callable, cast

from typing_extensions import Self

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres._internal.utilities import cancel, wait_any


@dataclass
class _TaskletInternal:
    task: Task[None] | None = None
    stopping: AsyncEvent = field(default_factory=AsyncEvent)
    stopped: AsyncEvent = field(default_factory=AsyncEvent)
    exception: BaseException | None = None


_INTERNAL_ATTRIBUTE_NAME = "__tasklet__"


class Tasklet(ABC):
    """
    Base class for objects that run as asyncio background tasks, including all instances of
    `Node`, like `Component` and `Engine`.
    """

    @property
    def running(self) -> bool:
        """
        `True` if the tasklet is currently running.
        """
        return not self.__tasklet__.stopped.is_set()

    @property
    def stopping(self) -> bool:
        """
        `True` if the tasklet is presently in the process of stopping or completely stopped.
        """
        return self.__tasklet__.stopping.is_set()

    @abstractmethod
    async def __run__(self) -> None: ...

    @abstractmethod
    async def __stop__(self) -> None: ...

    @property
    def __tasklet__(self) -> _TaskletInternal:
        if internal := self.__dict__.get(_INTERNAL_ATTRIBUTE_NAME):
            return cast(_TaskletInternal, internal)

        internal = _TaskletInternal()
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
        """
        Start the tasklet as a background task. If the tasklet is already running, this does
        nothing.
        """
        if self.__tasklet__.task:
            return

        self.__tasklet__.exception = None
        self.__tasklet__.stopping.clear()
        self.__tasklet__.stopped.clear()

        task_run = asyncio.create_task(self.__run__())
        task_exit = asyncio.create_task(self.__tasklet__.stopping.wait())

        async def main() -> None:
            await wait_any(task_run, task_exit)

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
                await cancel(task_run, task_exit)

                try:
                    await self.__stop__()
                finally:
                    if on_completed:
                        on_completed(self)

                    self.__tasklet__.task = None
                    self.__tasklet__.stopped.set()

        self.__tasklet__.task = asyncio.create_task(main(), name=str(type(self)))

    async def stop(self, raise_exceptions: bool = False) -> None:
        """
        Stop the tasklet and wait for it to stop completely. Calling this while the tasklet is
        already stopped does nothing and will return immediately.
        """
        self.__tasklet__.stopping.set()
        await self.__tasklet__.stopped.wait()
        if raise_exceptions and self.__tasklet__.exception:
            raise self.__tasklet__.exception

    async def wait_until_stopping(self) -> None:
        """
        Wait until the tasklet is stopping. Calling this while the tasklet is already stopped will
        return immediately.
        """
        await self.__tasklet__.stopping.wait()

    async def wait_until_stopped(self, raise_exceptions: bool = True) -> None:
        """
        Wait until the tasklet is stopped. Calling this while the tasklet is already stopped will
        return immediately.
        """
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
        """
        Start the tasklet, then wait for it to stop. If the tasklet is already running, this is
        equivalent to calling `wait_until_stopped()`.
        """
        self.start(
            on_completed=on_completed,
            on_exception=on_exception,
        )
        await self.wait_until_stopped(raise_exceptions)
