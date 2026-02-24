import asyncio
from asyncio import AbstractEventLoop, QueueEmpty
from asyncio import Queue as AsyncQueue
from collections.abc import AsyncIterable, AsyncIterator, Callable, Sequence
from typing import Any, Literal, Self, Union, cast, override
from weakref import WeakSet

from ceres._internal import util


def _get_loop() -> AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except Exception:
        return None


class OutputChannel[T](AsyncIterable[T]):
    __slots__ = (
        "__weakref__",
        "_source",
        "_readers",
        "_outputs",
        "_every",
        "_where",
        "_map",
    )

    def __init__(self, source: OutputChannel[T] | None = None, /) -> None:
        self._source = source
        self._readers: WeakSet[ChannelReader[T]] = WeakSet()
        self._outputs: WeakSet[OutputChannel[T]] = WeakSet()
        self._every: type[T] | None = None
        self._where: Callable[[T], bool] | None = None
        self._map: Callable[[T], Any] | None = None

        if source is not None:
            source._outputs.add(self)

    @property
    def readers(self) -> Sequence[ChannelReader[T]]:
        return list(self._readers)

    @override
    def __aiter__(self) -> ChannelReader[T]:
        return self.read()

    def read(self) -> ChannelReader[T]:
        return ChannelReader(self)

    def every[O](self, cls: type[O], /, *classes: type[O]) -> OutputChannel[O]:
        output = cast("OutputChannel[O]", OutputChannel(self))
        output._every = Union[cls, *classes] if classes else cls  # type: ignore
        return output

    def where(self, where: Callable[[T], bool], /) -> OutputChannel[T]:
        output = OutputChannel(self)
        output._where = where
        return output

    def map[O](self, transform: Callable[[T], O], /) -> OutputChannel[O]:
        output = cast("OutputChannel[O]", OutputChannel(self))
        output._map = transform  # type: ignore
        return output

    def _is_registered(self, reader: ChannelReader[Any]) -> bool:
        return reader in self._readers

    def _register(self, reader: ChannelReader[T]) -> None:
        self._readers.add(reader)

    def _unregister(self, reader: ChannelReader[T]) -> None:
        self._readers.discard(reader)

    def _put(self, value: T) -> None:
        try:
            if self._every is not None and not isinstance(value, self._every):
                return
            if self._where is not None and not self._where(value):
                return
            if self._map is not None:
                value = self._map(value)
        except Exception:
            return

        for reader in self._readers:
            reader._put(value)
        for output in self._outputs:
            output._put(value)


class Channel[T](OutputChannel[T]):
    __slots__ = ()

    def put(self, value: T) -> None:
        super()._put(value)

    def output(self) -> OutputChannel[T]:
        return OutputChannel(self)


class ChannelReader[T](AsyncIterator[T]):
    __slots__ = (
        "__weakref__",
        "_source",
        "_queue",
        "_loop",
    )

    def __init__(self, source: OutputChannel[T], /) -> None:
        self._source = source
        self._queue: AsyncQueue[T] = AsyncQueue()

        try:
            self._loop = _get_loop()
        except Exception:
            self._loop = None

        self.attach()

    @property
    def source(self) -> OutputChannel[T]:
        return self._source

    @property
    def loop(self) -> AbstractEventLoop | None:
        return self._loop

    @property
    def attached(self) -> bool:
        return self._source._is_registered(self)

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

        bound = self._require_bound_loop()
        running = _get_loop()

        if running is bound:
            value = await self._queue.get()
            self._queue.task_done()
        else:
            value = await util.run_in_loop(self.get(), bound, running)

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
        self._source._register(self)

    def detach(self) -> None:
        self._source._unregister(self)

    def _put(self, value: T) -> None:
        bound = self._get_bound_loop()
        running = _get_loop()

        if running is bound or bound is None:
            self._queue.put_nowait(value)
        else:
            bound.call_soon_threadsafe(self._queue.put_nowait, value)

    def _get_bound_loop(self) -> AbstractEventLoop | None:
        if self._loop is None:
            self._loop = _get_loop()

        return self._loop

    def _require_bound_loop(self) -> AbstractEventLoop:
        bound = self._get_bound_loop()
        if bound is None:
            raise RuntimeError("No event loop is running.")

        return bound
