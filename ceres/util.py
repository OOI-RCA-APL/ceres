from __future__ import annotations

import asyncio
from asyncio import Queue as AsyncQueue
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Generic,
    TypeVar,
    overload,
)

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres._internal.util import cancel

_EntryT = TypeVar("_EntryT", bound=tuple[Any, ...], covariant=True)

_undefined = object()


@dataclass
class _AZipLatestState:
    latest: list[Any]
    out: AsyncQueue[tuple[Any, ...]]
    tasks: list[asyncio.Task[Any]]


class _AsyncZipLatest(Generic[_EntryT]):
    def __init__(self, *iterables: AsyncIterable[Any]) -> None:
        self.__iterables = tuple(iterables)
        self.__state: _AZipLatestState | None = None

    async def __aenter__(self) -> AsyncIterator[_EntryT]:
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

        async def consume(out: AsyncQueue[Any]) -> AsyncIterator[_EntryT]:
            while True:
                value = await out.get()
                out.task_done()
                yield value

        return consume(self.__state.out)

    async def __aexit__(self, *args: Any) -> None:
        try:
            if self.__state and self.__state.tasks:
                await cancel(*self.__state.tasks)
        finally:
            self.__state = None


_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")
_T3 = TypeVar("_T3")
_T4 = TypeVar("_T4")


@overload
def azip_latest(
    a: AsyncIterable[_T1],
    b: AsyncIterable[_T2],
    /,
) -> _AsyncZipLatest[tuple[_T1, _T2]]: ...


@overload
def azip_latest(
    a: AsyncIterable[_T1],
    b: AsyncIterable[_T2],
    c: AsyncIterable[_T3],
    /,
) -> _AsyncZipLatest[tuple[_T1, _T2, _T3]]: ...


@overload
def azip_latest(
    a: AsyncIterable[_T1],
    b: AsyncIterable[_T2],
    c: AsyncIterable[_T3],
    d: AsyncIterable[_T4],
    /,
) -> _AsyncZipLatest[tuple[_T1, _T2, _T3]]: ...


def azip_latest(*streams: AsyncIterable[Any]) -> _AsyncZipLatest[tuple[Any, ...]]:
    return _AsyncZipLatest(*streams)
