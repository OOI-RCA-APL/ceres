from __future__ import annotations

from asyncio import Queue as AsyncQueue
from asyncio import QueueEmpty
from collections.abc import AsyncIterator
from typing import Any, AsyncIterable, Callable, Literal, Sequence, TypeVar, cast, final, overload
from weakref import WeakSet

from typing_extensions import Self, override

_T = TypeVar("_T")
_O = TypeVar("_O")


@final
class StreamReader(AsyncIterator[_T]):
    __slots__ = (
        "_source",
        "_queue",
        "__weakref__",
    )

    def __init__(self, source: "Stream[_T]") -> None:
        self._source = source
        self._queue: "AsyncQueue[_T]" = AsyncQueue()
        self.attach()

    @property
    def attached(self) -> bool:
        return self._source.has_reader(self)

    def __len__(self) -> int:
        return self._queue.qsize()

    @override
    async def __anext__(self) -> _T:
        return await self.get()

    @override
    def __aiter__(self) -> AsyncIterator[_T]:
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

    async def get(self) -> _T:
        self.attach()
        value = await self._queue.get()
        self._queue.task_done()
        return value

    def clear(self) -> list[_T]:
        values: list[_T] = []

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

    def _put(self, value: _T) -> None:
        self._queue.put_nowait(value)


class Stream(AsyncIterable[_T]):
    __slots__ = (
        "_source",
        "_readers",
        "_derived",
        "_every",
        "_filter",
        "_map",
        "__weakref__",
    )

    def __init__(self, source: "Stream[_T] | None" = None) -> None:
        self._source = source
        self._readers: "WeakSet[StreamReader[_T]]" = WeakSet()
        self._derived: "WeakSet[Stream[_T]]" = WeakSet()
        self._every: "type[_T] | None" = None
        self._filter: "Callable[[_T], bool] | None" = None
        self._map: "Callable[[_T], Any] | None" = None

        if source is not None:
            source._derived.add(self)

    @property
    def readers(self) -> Sequence[StreamReader[_T]]:
        return list(self._readers)

    @override
    def __aiter__(self) -> StreamReader[_T]:
        return self.read()

    def read(self) -> StreamReader[_T]:
        return StreamReader(self)

    def view(self) -> "Stream[_T]":
        return Stream(self)

    @overload
    def every(self, cls: type[_O], /) -> "Stream[_O]": ...

    @overload
    def every(self, cls: _O, /) -> "Stream[_O]": ...

    def every(self, cls: _O | type[_O], /) -> "Stream[_O]":
        derived = cast(Stream[_O], Stream(self))
        derived._every = cls  # type: ignore
        return derived

    def filter(self, filter: Callable[[_T], bool], /) -> "Stream[_T]":
        derived = Stream(self)
        derived._filter = filter
        return derived

    def map(self, transform: Callable[[_T], _O], /) -> "Stream[_O]":
        derived = cast(Stream[_O], Stream(self))
        derived._map = transform  # type: ignore
        return derived

    def has_reader(self, reader: StreamReader[Any]) -> bool:
        return reader in self._readers

    def add_reader(self, reader: StreamReader[_T]) -> None:
        self._readers.add(reader)

    def remove_reader(self, reader: StreamReader[_T]) -> None:
        self._readers.discard(reader)

    def _put(self, value: _T) -> None:
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
            reader._put(value)  # type: ignore
        for child in self._derived:
            child._put(value)


class WriteStream(Stream[_T]):
    def put(self, value: _T) -> None:
        super()._put(value)
