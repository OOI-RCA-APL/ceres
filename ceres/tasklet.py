import asyncio
import traceback
from abc import ABC, abstractmethod
from asyncio import Event as AsyncEvent
from asyncio import Task
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Self, cast

from ceres.concurrency import cancel, race

__all__ = [
    "Tasklet",
]


@dataclass
class _TaskletInternal:
    task: Task[None] | None = None
    stopping: AsyncEvent = field(default_factory=AsyncEvent)
    stopped: AsyncEvent = field(default_factory=AsyncEvent)
    exception: BaseException | None = None


_INTERNAL_ATTRIBUTE_NAME = "__tasklet__"


class Tasklet(ABC):
    """Base class for objects that run as asyncio background tasks.

    Subclasses implement `__run__()` for the main task body and `__stop__()` for cleanup,
    optionally overriding `__stopping__()` and `__post_stop__()` for additional lifecycle hooks.
    All `Node` instances like `Component` and `Engine` are tasklets.
    """

    @property
    def running(self) -> bool:
        """`True` if the tasklet is currently running."""
        return not self.__tasklet_internal__.stopped.is_set()

    @property
    def stopping(self) -> bool:
        """`True` if the tasklet is presently in the process of stopping or completely stopped."""
        return self.__tasklet_internal__.stopping.is_set()

    @abstractmethod
    async def __run__(self) -> None:
        """Run the tasklet's main body.

        The tasklet exits naturally when this coroutine returns, or early when `stop()` is called.
        """
        ...

    @abstractmethod
    async def __stop__(self) -> None:
        """Release resources acquired during `__run__()`.

        Called once the run task has been cancelled or has completed, before `__post_stop__()`.
        """
        ...

    def __stopping__(self) -> None:
        """Run synchronous logic the moment the tasklet begins stopping.

        Invoked immediately after the stopping event is set and before the run task is cancelled.
        """

    async def __post_stop__(self) -> None:
        """Run asynchronous cleanup after `__stop__()` has completed.

        Any exception raised here is caught and printed, the tasklet is still marked as stopped.
        """

    @property
    def __tasklet_internal__(self) -> _TaskletInternal:
        if internal := getattr(self, _INTERNAL_ATTRIBUTE_NAME, None):
            return cast("_TaskletInternal", internal)

        internal = _TaskletInternal()
        internal.stopping.set()
        internal.stopped.set()

        setattr(self, _INTERNAL_ATTRIBUTE_NAME, internal)
        return internal

    def start(
        self,
        *,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
    ) -> None:
        """Start the tasklet as a background task.

        If the tasklet is already running, this does nothing.

        Args:
            on_completed: Callback invoked after the tasklet has stopped, regardless of outcome.
            on_exception: Callback invoked with the raised exception when `__run__()` raises a
                non-cancellation exception.
        """
        if self.__tasklet_internal__.task:
            return

        self.__tasklet_internal__.exception = None
        self.__tasklet_internal__.stopping.clear()
        self.__tasklet_internal__.stopped.clear()

        task_run = asyncio.create_task(self.__run__(), name="tasklet-run")
        task_exit = asyncio.create_task(
            self.__tasklet_internal__.stopping.wait(), name="tasklet-exit"
        )

        async def main() -> None:
            await race(task_run, task_exit, cancel=False, raise_exceptions=False)

            try:
                if task_run.done():
                    try:
                        task_run.result()
                    except Exception as exception:
                        self.__tasklet_internal__.exception = exception
                        if on_exception:
                            on_exception(self, exception)
            finally:
                self.__tasklet_internal__.stopping.set()
                self.__stopping__()
                await cancel(task_run, task_exit)

                try:
                    await self.__stop__()
                finally:
                    if on_completed:
                        on_completed(self)

                    try:
                        await self.__post_stop__()
                    except Exception:
                        traceback.print_exc()

                    self.__tasklet_internal__.task = None
                    self.__tasklet_internal__.stopped.set()

        self.__tasklet_internal__.task = asyncio.create_task(main(), name=str(type(self)))

    async def stop(self, raise_exceptions: bool = False) -> None:
        """Stop the tasklet and wait for it to stop completely.

        Calling this while the tasklet is already stopped does nothing and returns immediately.

        Args:
            raise_exceptions: If `True`, re-raise any exception captured from `__run__()`.

        Raises:
            BaseException: The exception captured from `__run__()`, when `raise_exceptions` is set.
        """
        self.__tasklet_internal__.stopping.set()
        await self.__tasklet_internal__.stopped.wait()
        if raise_exceptions and self.__tasklet_internal__.exception:
            raise self.__tasklet_internal__.exception

    async def wait_until_stopping(self) -> None:
        """Wait until the tasklet enters the stopping state.

        Returns immediately if the tasklet is already stopping or stopped.
        """
        await self.__tasklet_internal__.stopping.wait()

    async def wait_until_stopped(self, raise_exceptions: bool = True) -> None:
        """Wait until the tasklet is fully stopped.

        Returns immediately if the tasklet is already stopped.

        Args:
            raise_exceptions: If `True`, re-raise any exception captured from `__run__()`.

        Raises:
            BaseException: The exception captured from `__run__()`, when `raise_exceptions` is set.
        """
        if not self.__tasklet_internal__.task:
            return

        await self.__tasklet_internal__.stopped.wait()
        if raise_exceptions and self.__tasklet_internal__.exception:
            raise self.__tasklet_internal__.exception

    async def run(
        self,
        *,
        raise_exceptions: bool = True,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
    ) -> None:
        """Start the tasklet, then wait for it to stop.

        If the tasklet is already running, this is equivalent to calling `wait_until_stopped()`.

        Args:
            raise_exceptions: If `True`, re-raise any exception captured from `__run__()`.
            on_completed: Callback invoked after the tasklet has stopped, regardless of outcome.
            on_exception: Callback invoked with the raised exception when `__run__()` raises a
                non-cancellation exception.

        Raises:
            BaseException: The exception captured from `__run__()`, when `raise_exceptions` is set.
        """
        self.start(
            on_completed=on_completed,
            on_exception=on_exception,
        )
        try:
            await self.wait_until_stopped(raise_exceptions)
        finally:
            # Handle cancellation.
            await self.stop(raise_exceptions)
