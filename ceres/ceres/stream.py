from asyncio import Queue as AsyncQueue
from asyncio import QueueEmpty
from collections.abc import AsyncIterator
from typing import Any, AsyncIterable, Literal, Sequence, TypeVar
from weakref import WeakSet

from typing_extensions import Self

_T = TypeVar("_T")


class StreamReader(AsyncIterator[_T]):
    __slots__ = ("_stream", "_queue", "__weakref__")

    def __init__(self, stream: "Stream[_T]") -> None:
        self._stream = stream
        self._queue: AsyncQueue[_T] = AsyncQueue()
        self.attach()

    @property
    def attached(self) -> bool:
        return self._stream.has_reader(self)

    def __len__(self) -> int:
        return self._queue.qsize()

    async def __anext__(self) -> _T:
        return await self.get()

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
        return await self._queue.get()

    def clear(self) -> list[_T]:
        values: list[_T] = []

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

    def feed(self, value: _T) -> None:
        self._queue.put_nowait(value)


class StreamView(AsyncIterable[_T]):
    __slots__ = ("_stream",)

    def __init__(self, stream: "Stream[_T]") -> None:
        self._stream = stream

    @property
    def readers(self) -> Sequence[StreamReader[_T]]:
        return self._stream.readers

    def __aiter__(self) -> StreamReader[_T]:
        return self._stream.__aiter__()

    def read(self) -> StreamReader[_T]:
        return self._stream.read()

    def view(self) -> Self:
        return self._stream.view()


class Stream(AsyncIterable[_T]):
    __slots__ = ("_readers",)

    def __init__(self) -> None:
        self._readers: WeakSet[StreamReader[_T]] = WeakSet()

    @property
    def readers(self) -> Sequence[StreamReader[_T]]:
        return list(self._readers)

    def __aiter__(self) -> StreamReader[_T]:
        return self.read()

    def put(self, value: _T) -> None:
        for reader in self._readers:
            reader.feed(value)

    def read(self) -> StreamReader[_T]:
        return StreamReader(self)

    def view(self) -> StreamView[_T]:
        return StreamView(self)

    def has_reader(self, reader: StreamReader[Any]) -> bool:
        return reader in self._readers

    def add_reader(self, reader: StreamReader[_T]) -> None:
        self._readers.add(reader)

    def remove_reader(self, reader: StreamReader[_T]) -> None:
        self._readers.discard(reader)
