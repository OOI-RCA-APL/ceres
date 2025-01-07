import asyncio
from asyncio import AbstractEventLoop, Task
from asyncio import Queue as AsyncQueue
from dataclasses import dataclass
from typing import Any, AsyncIterable, AsyncIterator, Iterable, overload

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres._internal import util


def ensure_event_loop(*, uvloop: bool = True, eager: bool = True) -> AbstractEventLoop:
    """
    Get the current running async event loop, or create and install a new one if necessary.

    :param uvloop: Whether or not to use `uvloop` as the event loop, provided it is installed and no current running loop exists.
    :param eager: Whether to use `asyncio.eager_task_factory` for the event loop, provided no current running loop exists.
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        if uvloop:
            try:
                from uvloop import EventLoopPolicy  # type: ignore

                if not isinstance(asyncio.get_event_loop_policy(), EventLoopPolicy):
                    asyncio.set_event_loop_policy(EventLoopPolicy())
            except Exception:
                pass

        try:
            return asyncio.get_running_loop()
        except Exception:
            loop = asyncio.new_event_loop()
            if eager:
                loop.set_task_factory(asyncio.eager_task_factory)

            asyncio.set_event_loop(loop)
            return loop


_undefined = object()


@dataclass
class _AZipLatestState:
    latest: list[Any]
    out: AsyncQueue[tuple[Any, ...]]
    tasks: list[Task[Any]]


class _AsyncZipLatest[T: tuple[Any, ...]]:
    def __init__(self, iterables: Iterable[AsyncIterable[Any]]) -> None:
        self.__iterables = tuple(iterables)
        self.__state: _AZipLatestState | None = None

    async def __aenter__(self) -> AsyncIterator[T]:
        self.__state = _AZipLatestState(
            latest=[_undefined] * len(self.__iterables),
            out=AsyncQueue(),
            tasks=[],
        )

        async def produce(
            state: _AZipLatestState,
            iterator: AsyncIterator[Any],
            index: int,
        ) -> None:
            while True:
                state.latest[index] = await anext(iterator)
                if all(current is not _undefined for current in state.latest):
                    state.out.put_nowait(tuple(state.latest))

        self.__state.tasks = [
            asyncio.create_task(produce(self.__state, aiter(iterable), index))
            for index, iterable in enumerate(self.__iterables)
        ]

        async def consume(out: AsyncQueue[Any]) -> AsyncIterator[T]:
            while True:
                value = await out.get()
                out.task_done()
                yield value

        return consume(self.__state.out)

    async def __aexit__(self, *args: Any) -> None:
        try:
            if self.__state and self.__state.tasks:
                await util.cancel(self.__state.tasks)
        finally:
            self.__state = None


@overload
def azip_latest[T1, T2](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    /,
) -> _AsyncZipLatest[tuple[T1, T2]]: ...


@overload
def azip_latest[T1, T2, T3](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    c: AsyncIterable[T3],
    /,
) -> _AsyncZipLatest[tuple[T1, T2, T3]]: ...


@overload
def azip_latest[T1, T2, T3, T4](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    c: AsyncIterable[T3],
    d: AsyncIterable[T4],
    /,
) -> _AsyncZipLatest[tuple[T1, T2, T3, T4]]: ...


@overload
def azip_latest[T1, T2, T3, T4, T5](
    a: AsyncIterable[T1],
    b: AsyncIterable[T2],
    c: AsyncIterable[T3],
    d: AsyncIterable[T4],
    e: AsyncIterable[T5],
    /,
) -> _AsyncZipLatest[tuple[T1, T2, T3, T4, T5]]: ...


def azip_latest(*streams: AsyncIterable[Any]) -> _AsyncZipLatest[tuple[Any, ...]]:
    return _AsyncZipLatest(streams)
