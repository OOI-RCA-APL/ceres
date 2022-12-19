from asyncio import Queue as AsyncQueue
from asyncio import QueueEmpty
from collections.abc import AsyncIterator
from typing import Any, AsyncIterable, Literal, Sequence, TypeVar, final
from weakref import WeakSet

from typing_extensions import Self

_T = TypeVar("_T")


@final
class StreamReader(AsyncIterator[_T]):
    __slots__ = (
        "__stream",
        "__queue",
        "__weakref__",
    )

    def __init__(self, stream: "Stream[_T]") -> None:
        self.__stream = stream
        self.__queue: AsyncQueue[_T] = AsyncQueue()
        self.attach()

    @property
    def attached(self) -> bool:
        return self.__stream.has_reader(self)

    def __len__(self) -> int:
        return self.__queue.qsize()

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
        value = await self.__queue.get()
        self.__queue.task_done()
        return value

    def clear(self) -> list[_T]:
        values: list[_T] = []

        while not self.__queue.empty():
            try:
                values.append(self.__queue.get_nowait())
                self.__queue.task_done()
            except QueueEmpty:
                break

        return values

    async def join(self) -> None:
        await self.__queue.join()

    def attach(self) -> None:
        self.__stream.add_reader(self)

    def detach(self) -> None:
        self.__stream.remove_reader(self)

    def feed(self, value: _T) -> None:
        self.__queue.put_nowait(value)


@final
class StreamView(AsyncIterable[_T]):
    __slots__ = ("__stream",)

    def __init__(self, stream: "Stream[_T]") -> None:
        self.__stream = stream

    @property
    def readers(self) -> Sequence[StreamReader[_T]]:
        return self.__stream.readers

    def __aiter__(self) -> StreamReader[_T]:
        return self.__stream.__aiter__()

    def read(self) -> StreamReader[_T]:
        return self.__stream.read()

    def view(self) -> Self:
        return self.__stream.view()


@final
class Stream(AsyncIterable[_T]):
    __slots__ = ("__readers",)

    def __init__(self) -> None:
        self.__readers: WeakSet[StreamReader[_T]] = WeakSet()

    @property
    def readers(self) -> Sequence[StreamReader[_T]]:
        return list(self.__readers)

    def __aiter__(self) -> StreamReader[_T]:
        return self.read()

    def put(self, value: _T) -> None:
        for reader in self.__readers:
            reader.feed(value)

    def read(self) -> StreamReader[_T]:
        return StreamReader(self)

    def view(self) -> StreamView[_T]:
        return StreamView(self)

    def has_reader(self, reader: StreamReader[Any]) -> bool:
        return reader in self.__readers

    def add_reader(self, reader: StreamReader[_T]) -> None:
        self.__readers.add(reader)

    def remove_reader(self, reader: StreamReader[_T]) -> None:
        self.__readers.discard(reader)
