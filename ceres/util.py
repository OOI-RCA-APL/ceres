import asyncio
from asyncio import AbstractEventLoop, CancelledError, Task, TaskGroup
from asyncio import Queue as AsyncQueue
from collections.abc import AsyncIterable, AsyncIterator, Coroutine, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast, overload

from ceres._internal.util import MaybeRecursiveIterable, flatten


async def cancel(*tasks: MaybeRecursiveIterable[Task[Any]]) -> None:
    """
    Cancel all given tasks and wait for them to complete.
    """
    flattened = list(flatten(tasks))
    for task in flattened:
        task.cancel()

    await asyncio.gather(*flattened, return_exceptions=True)


async def concurrently(
    *coroutines: MaybeRecursiveIterable[Coroutine[Any, Any, Any] | None],
) -> None:
    """
    Run all given coroutines concurrently in a single task group, waiting for all to complete or be cancelled.
    """
    async with TaskGroup() as group:
        for current in flatten(coroutines):
            if current is not None:
                group.create_task(current)


async def wait_any[T](
    *tasks: MaybeRecursiveIterable[Task[T] | Coroutine[T, Any, Any]],
    cancelling: bool = False,
    raised: bool = False,
) -> tuple[set[Task[T]], set[Task[T]]]:
    """
    Wait for any of the given tasks or coroutines to complete.

    If `cancelling` is `True`, all remaining tasks will be cancelled and awaited once the first task
    completes. This is `False` by default.

    :param tasks: The tasks or coroutines to wait for. If coroutines are given, they will be automatically scheduled as tasks.
    :param cancelling: Whether or not to cancel all remaining tasks once one completes.
    :return: A tuple of two sets. The first set contains all tasks that completed, and the second set contains all tasks still pending.
    """
    flattened = _to_tasks(flatten(tasks))
    try:
        done, pending = await _wait_many(asyncio.FIRST_COMPLETED, flattened)
        if cancelling:
            await cancel(pending)

        if raised:
            for task in done:
                if not task.cancelled() and (exception := task.exception()):
                    raise exception

        return done, pending
    except CancelledError:
        try:
            if cancelling:
                await cancel(flattened)
        finally:
            raise


async def wait_all[T](
    *tasks: MaybeRecursiveIterable[Task[T] | Coroutine[T, Any, Any]],
) -> tuple[Task[T]]:
    """
    Wait for all of the given tasks or coroutines to complete.

    :param tasks: The tasks or coroutines to wait for. If a coroutines are given, they will be automatically scheduled as tasks.
    :return: A tuple of all tasks completed.
    """
    done, _ = await _wait_many(asyncio.ALL_COMPLETED, _to_tasks(flatten(tasks)))
    return done  # type: ignore


def _to_tasks[T](
    tasks: Iterable[Task[T] | Coroutine[Any, Any, T]],
) -> list[Task[T]]:
    return [asyncio.create_task(task) if not isinstance(task, Task) else task for task in tasks]


async def _wait_many[T](
    condition: str,
    tasks: Sequence[Task[T]],
) -> tuple[set[Task[T]], set[Task[T]]]:
    result = await asyncio.wait(tasks, return_when=condition)
    return result


def ensure_event_loop(*, uvloop: bool = True, eager: bool = True) -> AbstractEventLoop:
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


_UNDEFINED = object()


@dataclass
class _AsyncZipState:
    latest: list[Any]
    out: AsyncQueue[tuple[Any, ...]]
    tasks: list[Task[Any]]


class AsyncZip[T: tuple[Any, ...]]:
    def __init__(self, iterables: Iterable[AsyncIterable[Any]]) -> None:
        self._iterables = tuple(iterables)
        self._state: _AsyncZipState | None = None

    async def __aenter__(self) -> AsyncIterator[T]:
        self._state = _AsyncZipState(
            latest=[_UNDEFINED] * len(self._iterables),
            out=AsyncQueue(),
            tasks=[],
        )

        async def produce(
            state: _AsyncZipState,
            iterator: AsyncIterator[Any],
            index: int,
        ) -> None:
            while True:
                state.latest[index] = await anext(iterator)
                if all(current is not _UNDEFINED for current in state.latest):
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
