from __future__ import annotations

import asyncio
from asyncio import AbstractEventLoop, QueueEmpty
from asyncio import Queue as AsyncQueue
from collections.abc import AsyncIterator
from typing import (
    Any,
    AsyncIterable,
    Callable,
    Literal,
    Self,
    Sequence,
    cast,
    final,
    overload,
    override,
)
from weakref import WeakSet

from ceres._internal import util


def _get_running_loop() -> AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except Exception:
        return None


@final
class StreamReader[T](AsyncIterator[T]):
    __slots__ = (
        "_source",
        "_queue",
        "_loop",
        "__weakref__",
    )

    def __init__(self, source: Stream[T]) -> None:
        self._source = source
        self._queue: AsyncQueue[T] = AsyncQueue()

        try:
            self._loop = _get_running_loop()
        except Exception:
            self._loop = None

        self.attach()

    @property
    def source(self) -> Stream[T]:
        return self._source

    @property
    def loop(self) -> AbstractEventLoop | None:
        return self._loop

    @property
    def attached(self) -> bool:
        return self._source.has_reader(self)

    def __len__(self) -> int:
        return self._queue.qsize()

    @override
    async def __anext__(self) -> T:
        return await self.get()

    @override
    def __aiter__(self) -> AsyncIterator[T]:
        self.attach()
        return self

    def __enter__(self) -> Self:
        self.attach()
        return self

    def __exit__(self, type: Any, value: Any, traceback: Any) -> Literal[False]:
        self.detach()
        return False

    def __del__(self) -> None:
        self.detach()

    async def get(self) -> T:
        self.attach()

        loop = self._require_bound_event_loop()
        running = _get_running_loop()

        if running is loop:
            value = await self._queue.get()
            self._queue.task_done()
        else:
            value = await util.run_in_loop(self.get(), loop, running)

        return value

    def clear(self) -> list[T]:
        values: list[T] = []

        while not self._queue.empty():
            try:
                values.append(self._queue.get_nowait())
                self._queue.task_done()
            except QueueEmpty:
                break

        return values

    async def join(self) -> None:
        await self._queue.join()

    def attach(self) -> None:
        self._source.add_reader(self)

    def detach(self) -> None:
        self._source.remove_reader(self)

    def _put(self, value: T) -> None:
        loop = self._get_bound_event_loop()
        running = _get_running_loop()

        if running is loop or loop is None:
            self._queue.put_nowait(value)
        else:
            loop.call_soon_threadsafe(self._queue.put_nowait, value)

    def _get_bound_event_loop(self) -> AbstractEventLoop | None:
        if self._loop is None:
            self._loop = _get_running_loop()

        return self._loop

    def _require_bound_event_loop(self) -> AbstractEventLoop:
        loop = self._get_bound_event_loop()
        if loop is None:
            raise RuntimeError("No event loop is running.")

        return loop


class Stream[T](AsyncIterable[T]):
    __slots__ = (
        "_source",
        "_readers",
        "_derived",
        "_every",
        "_filter",
        "_map",
        "__weakref__",
    )

    def __init__(self, source: Stream[T] | None = None) -> None:
        self._source = source
        self._readers: WeakSet[StreamReader[T]] = WeakSet()
        self._derived: WeakSet[Stream[T]] = WeakSet()
        self._every: type[T] | None = None
        self._filter: Callable[[T], bool] | None = None
        self._map: Callable[[T], Any] | None = None

        if source is not None:
            source._derived.add(self)

    @property
    def readers(self) -> Sequence[StreamReader[T]]:
        return list(self._readers)

    @override
    def __aiter__(self) -> StreamReader[T]:
        return self.read()

    def read(self) -> StreamReader[T]:
        return StreamReader(self)

    def view(self) -> Stream[T]:
        return Stream(self)

    @overload
    def every[O](self, cls: type[O], /) -> Stream[O]: ...

    @overload
    def every[O](self, cls: O, /) -> Stream[O]: ...

    def every[O](self, cls: O | type[O], /) -> Stream[O]:
        derived = cast("Stream[O]", Stream(self))
        derived._every = cls  # type: ignore
        return derived

    def filter(self, filter: Callable[[T], bool], /) -> Stream[T]:
        derived = Stream(self)
        derived._filter = filter
        return derived

    def map[O](self, transform: Callable[[T], O], /) -> Stream[O]:
        derived = cast("Stream[O]", Stream(self))
        derived._map = transform  # type: ignore
        return derived

    def has_reader(self, reader: StreamReader[Any]) -> bool:
        return reader in self._readers

    def add_reader(self, reader: StreamReader[T]) -> None:
        self._readers.add(reader)

    def remove_reader(self, reader: StreamReader[T]) -> None:
        self._readers.discard(reader)

    def _put(self, value: T) -> None:
        try:
            if self._every is not None and not isinstance(value, self._every):
                return
            if self._filter is not None and not self._filter(value):
                return
            if self._map is not None:
                value = self._map(value)
        except Exception:
            return

        for reader in self._readers:
            reader._put(value)
        for child in self._derived:
            child._put(value)


class WriteStream[T](Stream[T]):
    def put(self, value: T) -> None:
        super()._put(value)
