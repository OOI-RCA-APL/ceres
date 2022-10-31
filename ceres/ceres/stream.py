from __future__ import annotations

from asyncio import Queue as AsyncQueue
from asyncio import QueueEmpty
from collections.abc import AsyncIterator
from typing import Any, Callable, Generic, Literal, TypeVar

__all__ = [
    "Stream",
    "StreamReader",
    "StreamView",
]

T = TypeVar("T")


class Stream(Generic[T]):
    __slots__ = ("_readers",)

    def __init__(self) -> None:
        self._readers: set[StreamReader[T]] = set()

    def put(self, value: T) -> None:
        for reader in self._readers:
            reader._queue.put_nowait(value)

    def read(self) -> StreamReader[T]:
        def register() -> None:
            self._readers.add(reader)

        def unregister() -> None:
            try:
                self._readers.remove(reader)
            except KeyError:
                pass

        reader: StreamReader[T] = StreamReader(register, unregister)
        return reader

    def view(self) -> StreamView[T]:
        return StreamView(self)


class StreamView(Generic[T]):
    __slots__ = ("_stream",)

    def __init__(self, stream: Stream[T]) -> None:
        self._stream = stream

    def read(self) -> StreamReader[T]:
        return self._stream.read()

    def view(self) -> StreamView[T]:
        return self._stream.view()


class StreamReader(AsyncIterator[T]):
    __slots__ = ("_register", "_unregister", "_queue")

    def __init__(
        self,
        register: Callable[[], None],
        unregister: Callable[[], None],
    ) -> None:
        self._register = register
        self._unregister = unregister
        self._queue: AsyncQueue[T] = AsyncQueue()

    def __len__(self) -> int:
        return self._queue.qsize()

    async def __anext__(self) -> T:
        return await self.get()

    def __aiter__(self) -> AsyncIterator[T]:
        self._register()
        return self

    def __enter__(self) -> StreamReader[T]:
        self._register()
        return self

    def __exit__(self, type: Any, value: Any, traceback: Any) -> Literal[False]:
        self.dispose()
        return False

    def __del__(self) -> None:
        self.dispose()

    async def get(self) -> T:
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

    def dispose(self) -> None:
        self._unregister()
