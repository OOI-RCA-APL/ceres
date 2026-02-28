import asyncio
from asyncio import AbstractEventLoop, CancelledError, Task, TaskGroup
from asyncio import Queue as AsyncQueue
from collections.abc import AsyncIterable, AsyncIterator, Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast, overload

from ceres._internal.util import MaybeRecursiveIterable, Undefined, flatten

__all__ = [
    "cancel",
    "concurrently",
    "race",
    "el",
    "spawn",
    "azip",
]


async def cancel(*tasks: MaybeRecursiveIterable[Task[Any]]) -> list[Task[Any]]:
    """
    Cancel all provided tasks and wait for them to complete.

    Returns:
        A flattened list of all tasks cancelled.
    """
    flattened = list(flatten(tasks))
    for task in flattened:
        task.cancel()

    await asyncio.gather(*flattened, return_exceptions=True)
    return flattened


_cancel: Final = cancel


async def concurrently(
    *coroutines: MaybeRecursiveIterable[Coroutine[Any, Any, Any] | None],
) -> list[Task[Any]]:
    """
    Run coroutines concurrently in a task group, waiting for all of them to complete or be
    cancelled. Any coroutine which is `None` is ignored.

    Returns:
        A list of all tasks created to run the given coroutines.
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
    """
    Wait for any of the given tasks or coroutines to complete.

    Args:
        tasks: The tasks or coroutines to wait for. If coroutines are given, they will be automatically scheduled as tasks.
        cancel: Whether or not to cancel all remaining tasks once at least one completes.
        raise_exceptions: Whether or not to raise any exceptions from completed tasks. If `True`, the first exception raised by any completed task will be raised, and all other exceptions will be ignored. If `False`, all exceptions will be ignored.

    Returns:
        A tuple of two sets. The first set contains all tasks that completed, and the second set contains all tasks which were still pending.
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
        try:
            if cancel:
                await _cancel(flattened)
        finally:
            raise


def el(*, uvloop: bool = True, eager: bool = True) -> AbstractEventLoop:
    """
    Get the current running async event loop, or create and install a new one if necessary.

    :param uvloop: Whether or not to use `uvloop` as the event loop, provided it is installed and no current running loop exists.
    :param eager: Whether to use `asyncio.eager_task_factory` for the event loop, provided no current running loop exists.
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
    """
    Run a function with the provided arguments in a new thread. Returns a coroutine which waits for
    the function call to complete and yields the return value.
    """

    def run() -> T:
        return function(*args, **kwargs)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor() as executor:
        return await el().run_in_executor(executor, run)


class AsyncZip[T: tuple[Any, ...]]:
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
