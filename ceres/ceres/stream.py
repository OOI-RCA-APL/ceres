from __future__ import annotations

from asyncio import Queue as AsyncQueue
from asyncio import QueueEmpty
from collections.abc import AsyncIterator
from typing import Any, AsyncIterable, Literal, Sequence, TypeVar
from weakref import WeakSet

__all__ = [
    "Stream",
    "StreamReader",
    "StreamView",
]

T = TypeVar("T")


class Stream(AsyncIterable[T]):
    __slots__ = ("_readers",)

    def __init__(self) -> None:
        self._readers: WeakSet[StreamReader[T]] = WeakSet()

    @property
    def readers(self) -> Sequence[StreamReader[T]]:
        return list(self._readers)

    def __aiter__(self) -> StreamReader[T]:
        return self.read()

    def put(self, value: T) -> None:
        for reader in self._readers:
            reader.feed(value)

    def read(self) -> StreamReader[T]:
        return StreamReader(self)

    def view(self) -> StreamView[T]:
        return StreamView(self)

    def has_reader(self, reader: StreamReader[Any]) -> bool:
        return reader in self._readers

    def add_reader(self, reader: StreamReader[T]) -> None:
        self._readers.add(reader)

    def remove_reader(self, reader: StreamReader[T]) -> None:
        self._readers.discard(reader)


class StreamView(AsyncIterable[T]):
    __slots__ = ("_stream",)

    def __init__(self, stream: Stream[T]) -> None:
        self._stream = stream

    @property
    def readers(self) -> Sequence[StreamReader[T]]:
        return self._stream.readers

    def __aiter__(self) -> StreamReader[T]:
        return self._stream.__aiter__()

    def read(self) -> StreamReader[T]:
        return self._stream.read()

    def view(self) -> StreamView[T]:
        return self._stream.view()


class StreamReader(AsyncIterator[T]):
    __slots__ = ("_stream", "_queue", "__weakref__")

    def __init__(self, stream: Stream[T]) -> None:
        self._stream = stream
        self._queue: AsyncQueue[T] = AsyncQueue()
        self.attach()

    @property
    def attached(self) -> bool:
        return self._stream.has_reader(self)

    def __len__(self) -> int:
        return self._queue.qsize()

    async def __anext__(self) -> T:
        return await self.get()

    def __aiter__(self) -> AsyncIterator[T]:
        self.attach()
        return self

    def __enter__(self) -> StreamReader[T]:
        self.attach()
        return self

    def __exit__(self, type: Any, value: Any, traceback: Any) -> Literal[False]:
        self.detach()
        return False

    def __del__(self) -> None:
        self.detach()

    async def get(self) -> T:
        self.attach()
        return await self._queue.get()

    def clear(self) -> list[T]:
        values: list[T] = []

        while not self._queue.empty():
            try:
                values.append(self._queue.get_nowait())
                self._queue.task_done()
            except QueueEmpty:
                break

        return values

    def attach(self) -> None:
        self._stream.add_reader(self)

    def detach(self) -> None:
        self._stream.remove_reader(self)

    def feed(self, value: T) -> None:
        self._queue.put_nowait(value)
