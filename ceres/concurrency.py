import asyncio
import math
from asyncio import AbstractEventLoop, CancelledError, Task, TaskGroup
from asyncio import Queue as AsyncQueue
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Iterable,
    Sequence,
)
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final, cast, overload

from ceres.__internal__.utilities.collections import MaybeRecursiveIterable, flatten
from ceres.__internal__.utilities.undefined import Undefined

if TYPE_CHECKING:
    from types import EllipsisType

__all__ = [
    "sleep",
    "awaitify",
    "cancel",
    "concurrently",
    "race",
    "el",
    "spawn",
    "azip",
]


async def sleep(delay: float | timedelta | EllipsisType, /) -> None:
    """Asynchronously sleep for a given `delay`.

    Args:
        delay: A number of seconds, a `timedelta` representing the duration to sleep for, or
            `...` to sleep forever (or until cancelled).
    """
    if delay is ...:
        delay = math.inf
    elif isinstance(delay, timedelta):
        delay = delay.total_seconds()

    await asyncio.sleep(delay)


async def awaitify[T](value: Awaitable[T] | T, /) -> T:
    """Await `value` if it is awaitable, otherwise return it as-is.

    Useful when a callback may return either a plain value or a coroutine, allowing call sites
    to uniformly await the result.

    Args:
        value: The value to await, or to return directly.

    Returns:
        The awaited value, or `value` itself if it was not awaitable.
    """
    import inspect

    if inspect.isawaitable(value):
        return cast("T", await value)

    return cast("T", value)


async def cancel(*tasks: MaybeRecursiveIterable[Task[Any]]) -> list[Task[Any]]:
    """Cancel all provided tasks and wait for them to complete.

    Exceptions raised during cancellation are suppressed, the goal is to ensure all tasks reach
    a final state.

    Args:
        tasks: Tasks to cancel, may be passed individually or as nested iterables.

    Returns:
        A flattened list of all tasks that were cancelled.
    """
    flattened = list(flatten(tasks))
    for task in flattened:
        task.cancel()

    await asyncio.gather(*flattened, return_exceptions=True)
    return flattened


# Internal alias so the public name `cancel` can be shadowed by parameters in functions like
# `race()` without losing access to the helper.
_cancel: Final = cancel


async def concurrently(
    *coroutines: MaybeRecursiveIterable[Coroutine[Any, Any, Any] | None],
) -> list[Task[Any]]:
    """Run coroutines concurrently in a task group, waiting for all of them to finish.

    Any coroutine that is `None` is silently ignored, which makes it convenient to conditionally
    include work without filtering call-site arguments.

    Args:
        coroutines: Coroutines to schedule, may be passed individually or as nested iterables.

    Returns:
        The list of tasks created to run the given coroutines.
    """
    tasks: list[Task[Any]] = []
    async with TaskGroup() as group:
        for current in flatten(coroutines):
            if current is not None:
                tasks.append(group.create_task(current))

    return tasks


async def race[T](
    *tasks: MaybeRecursiveIterable[Task[T] | Coroutine[T, Any, Any]],
    cancel: bool = True,
    raise_exceptions: bool = True,
) -> tuple[set[Task[T]], set[Task[T]]]:
    """Wait for any of the given tasks or coroutines to complete.

    Args:
        tasks: The tasks or coroutines to wait for. Coroutines are automatically scheduled as
            tasks before waiting.
        cancel: Whether to cancel all remaining tasks once at least one completes.
        raise_exceptions: Whether to raise exceptions from completed tasks. If `True`, the first
            exception raised by any completed task is re-raised, all others are ignored. If
            `False`, all exceptions are ignored.

    Returns:
        A tuple of two sets, the first containing all tasks that completed, the second
        containing all tasks that were still pending when `race()` returned.
    """
    flattened = _to_tasks(flatten(tasks))
    try:
        done, pending = await _wait_many(asyncio.FIRST_COMPLETED, flattened)
        if cancel:
            await _cancel(pending)

        if raise_exceptions:
            for task in done:
                if not task.cancelled() and (exception := task.exception()):
                    raise exception

        return done, pending
    except CancelledError:
        # When the caller is cancelled, propagate the cancellation to every task so nothing is
        # left running in the background.
        try:
            if cancel:
                await _cancel(flattened)
        finally:
            raise


def el(*, uvloop: bool = True, eager: bool = True) -> AbstractEventLoop:
    """Get the current running async event loop, or create and install a new one if necessary.

    Args:
        uvloop: Whether to use `uvloop` as the event loop, provided it is installed and no
            running loop already exists.
        eager: Whether to use `asyncio.eager_task_factory` for the event loop, provided no
            running loop already exists.

    Returns:
        The running event loop, or a freshly installed one.
    """
    loop: AbstractEventLoop | None = None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop is None and uvloop:
        try:
            from uvloop import new_event_loop

            loop = cast("AbstractEventLoop", new_event_loop())
        except Exception:
            pass

    if loop is None:
        loop = asyncio.new_event_loop()

    if eager:
        loop.set_task_factory(asyncio.eager_task_factory)

    # Prefer the running loop if one exists, this avoids replacing the loop a coroutine is
    # currently executing on.
    try:
        return asyncio.get_running_loop()
    except Exception:
        pass

    try:
        asyncio.set_event_loop(loop)
    except Exception:
        pass

    return loop


async def spawn[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a synchronous function in a new thread and await its result.

    Args:
        function: The function to invoke.
        *args: Positional arguments forwarded to `function`.
        **kwargs: Keyword arguments forwarded to `function`.

    Returns:
        The value returned by `function`.
    """

    def run() -> T:
        return function(*args, **kwargs)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor() as executor:
        return await el().run_in_executor(executor, run)


class AsyncZip[T: tuple[Any, ...]]:
    """Async context manager that zips multiple async iterables into tuples.

    On each iteration, the most recent value from every input iterable is combined into a tuple
    and yielded. A tuple is only emitted once every iterable has produced at least one value.
    The producing tasks are cancelled when the context manager exits.
    """

    @dataclass
    class _State:
        latest: list[Any]
        out: AsyncQueue[tuple[Any, ...]]
        tasks: list[Task[Any]]

    def __init__(self, iterables: Iterable[AsyncIterable[Any]]) -> None:
        self._iterables = tuple(iterables)
        self._state: AsyncZip._State | None = None

    async def __aenter__(self) -> AsyncIterator[T]:
        self._state = AsyncZip._State(
            latest=[Undefined] * len(self._iterables),
            out=AsyncQueue(),
            tasks=[],
        )

        async def produce(
            state: AsyncZip._State,
            iterator: AsyncIterator[Any],
            index: int,
        ) -> None:
            while True:
                state.latest[index] = await anext(iterator)
                # Wait for every iterable to have emitted before producing combined tuples,
                # otherwise downstream consumers see partial state.
                if all(current is not Undefined for current in state.latest):
                    state.out.put_nowait(tuple(state.latest))

        self._state.tasks = [
            asyncio.create_task(produce(self._state, aiter(iterable), index))
            for index, iterable in enumerate(self._iterables)
        ]

        async def consume(out: AsyncQueue[Any]) -> AsyncIterator[T]:
            while True:
                value = await out.get()
                out.task_done()
                yield value

        return consume(self._state.out)

    async def __aexit__(self, *args: Any) -> None:
        try:
            if self._state and self._state.tasks:
                await cancel(self._state.tasks)
        finally:
            self._state = None


@overload
def azip[T1, T2](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    /,
) -> AsyncZip[tuple[T1, T2]]: ...


@overload
def azip[T1, T2, T3](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    c: AsyncIterable[T3],
    /,
) -> AsyncZip[tuple[T1, T2, T3]]: ...


@overload
def azip[T1, T2, T3, T4](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    c: AsyncIterable[T3],
    d: AsyncIterable[T4],
    /,
) -> AsyncZip[tuple[T1, T2, T3, T4]]: ...


@overload
def azip[T1, T2, T3, T4, T5](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    c: AsyncIterable[T3],
    d: AsyncIterable[T4],
    e: AsyncIterable[T5],
    /,
) -> AsyncZip[tuple[T1, T2, T3, T4, T5]]: ...


def azip(*streams: AsyncIterable[Any]) -> AsyncZip[tuple[Any, ...]]:
    """Combine multiple async iterables into a stream of tuples of their latest values.

    Args:
        *streams: The async iterables to zip together.

    Returns:
        An `AsyncZip` context manager whose iterator yields tuples containing the most recent
        value from each input stream.
    """
    return AsyncZip(streams)


def _to_tasks[T](
    tasks: Iterable[Task[T] | Coroutine[Any, Any, T]],
) -> list[Task[T]]:
    return [
        cast("Task[T]", asyncio.create_task(task) if not isinstance(task, Task) else task)
        for task in tasks
    ]


async def _wait_many[T](
    condition: str,
    tasks: Sequence[Task[T]],
) -> tuple[set[Task[T]], set[Task[T]]]:
    result = await asyncio.wait(tasks, return_when=condition)
    return result
