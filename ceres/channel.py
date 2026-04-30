import asyncio
from asyncio import AbstractEventLoop, QueueEmpty
from asyncio import Queue as AsyncQueue
from collections.abc import AsyncIterable, AsyncIterator, Callable, Coroutine, Sequence
from typing import Any, Literal, Self, Union, cast, override
from weakref import WeakSet

__all__ = [
    "Channel",
    "OutputChannel",
    "ChannelReader",
]


class OutputChannel[T](AsyncIterable[T]):
    """Read-only view of a `Channel` that fans values out to readers and derived outputs.

    `OutputChannel` is the public side of the channel pub/sub primitive, callers can iterate it
    asynchronously, attach a `ChannelReader` directly, or build a derived output that filters or
    transforms incoming values. Only the originating `Channel` can publish, derived outputs forward
    values they receive from their source.

    Readers and downstream outputs are tracked with weak references so that consumers are released
    as soon as they go out of scope, this avoids leaking resources when a long-lived component or
    engine produces values to short-lived listeners.
    """

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
        """Construct an output, optionally chained to a `source` output.

        Args:
            source: The upstream output to receive values from, or `None` for a
                root output owned directly by a `Channel`.
        """
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
        """Return a snapshot of currently attached readers."""
        return list(self._readers)

    @override
    def __aiter__(self) -> ChannelReader[T]:
        return self.read()

    def read(self) -> ChannelReader[T]:
        """Create and attach a new `ChannelReader` to this output."""
        return ChannelReader(self)

    def every[O](self, cls: type[O], /, *classes: type[O]) -> OutputChannel[O]:
        """Create a derived output that only forwards values matching the given types.

        Args:
            cls: The first type to match against.
            *classes: Additional types to also match against, treated as a union.

        Returns:
            A new `OutputChannel` chained to this one, only `isinstance` matches pass through.
        """
        output = cast("OutputChannel[O]", OutputChannel(self))
        output._every = Union[cls, *classes] if classes else cls  # type: ignore
        return output

    def where(self, where: Callable[[T], bool], /) -> OutputChannel[T]:
        """Create a derived output that only forwards values for which `where` returns truthy.

        Args:
            where: Predicate evaluated for each value, exceptions are swallowed and treated
                as a non-match.

        Returns:
            A new `OutputChannel` chained to this one.
        """
        output = OutputChannel(self)
        output._where = where
        return output

    def map[O](self, transform: Callable[[T], O], /) -> OutputChannel[O]:
        """Create a derived output that transforms each value via `transform`.

        Args:
            transform: Function applied to each value before forwarding.

        Returns:
            A new `OutputChannel` chained to this one carrying the transformed type.
        """
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
        # Apply each filter or transform in order, any exception during evaluation drops
        # the value rather than propagating to the producer or other consumers.
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
    """Pub/sub primitive that fans values out to readers and derived `OutputChannel`s.

    A `Channel` is the writable side, owners call `put` to publish a value and any attached readers
    or chained outputs receive it. Use `output` to expose a read-only handle to consumers without
    leaking the ability to publish.
    """

    __slots__ = ()

    def put(self, value: T) -> None:
        """Publish `value` to every attached reader and chained output."""
        super()._put(value)

    def output(self) -> OutputChannel[T]:
        """Return a read-only `OutputChannel` view of this channel."""
        return OutputChannel(self)


class ChannelReader[T](AsyncIterator[T]):
    """Async iterator and queue that buffers values delivered from an `OutputChannel`.

    A `ChannelReader` registers itself with its source on construction, values published while the
    reader is attached are queued for retrieval via `get` or async iteration. The reader can be
    detached and reattached, and supports use as a context manager that detaches on exit.

    Each reader is bound to the event loop that was running when it was constructed (or the first
    loop encountered if none was running at construction time). Values produced from other loops
    are delivered safely via `call_soon_threadsafe`, and `get` calls issued from a different loop
    are routed back to the bound loop.
    """

    __slots__ = (
        "__weakref__",
        "_source",
        "_queue",
        "_loop",
    )

    def __init__(self, source: OutputChannel[T], /) -> None:
        """Construct a reader bound to `source` and attach it.

        Args:
            source: The output channel to receive values from.
        """
        self._source = source
        self._queue: AsyncQueue[T] = AsyncQueue()

        # Capture the running loop at construction time when possible so cross-loop
        # delivery can be handled correctly. Falling back to `None` lets the reader be
        # constructed outside of an async context.
        try:
            self._loop = _get_loop()
        except Exception:
            self._loop = None

        self.attach()

    @property
    def source(self) -> OutputChannel[T]:
        """Return the output channel this reader is attached to."""
        return self._source

    @property
    def loop(self) -> AbstractEventLoop | None:
        """Return the event loop this reader is bound to, if any."""
        return self._loop

    @property
    def attached(self) -> bool:
        """Return whether this reader is currently registered with its source."""
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
        """Wait for and return the next value from the channel.

        Returns:
            The next value published to the source channel after this reader attached.

        Raises:
            RuntimeError: If no event loop has been bound to this reader yet and one is not
                currently running.
        """
        self.attach()

        bound = self._require_bound_loop()
        running = _get_loop()

        # If the caller is on the same loop the reader was bound to, await the queue
        # directly. Otherwise, hop the coroutine over to the bound loop and wait for the
        # result on this loop.
        if running is bound:
            value = await self._queue.get()
            self._queue.task_done()
        else:
            value = await _run_in_loop(self.get(), bound, running)

        return value

    def clear(self) -> list[T]:
        """Drain and return all currently queued values without waiting for new ones."""
        values: list[T] = []

        while not self._queue.empty():
            try:
                values.append(self._queue.get_nowait())
                self._queue.task_done()
            except QueueEmpty:
                break

        return values

    async def join(self) -> None:
        """Wait until all queued values have been consumed and acknowledged."""
        await self._queue.join()

    def attach(self) -> None:
        """Register this reader with its source so it begins receiving values."""
        self._source._register(self)

    def detach(self) -> None:
        """Unregister this reader from its source so it stops receiving values."""
        self._source._unregister(self)

    def _put(self, value: T) -> None:
        bound = self._get_bound_loop()
        running = _get_loop()

        # Same-loop or no-bound-loop puts are safe to enqueue directly. Cross-loop puts
        # must hop through `call_soon_threadsafe` to avoid corrupting the queue's state.
        if running is bound or bound is None:
            self._queue.put_nowait(value)
        else:
            bound.call_soon_threadsafe(self._queue.put_nowait, value)

    def _get_bound_loop(self) -> AbstractEventLoop | None:
        # Lazily latch onto the first running loop encountered if one was not available
        # when the reader was constructed.
        if self._loop is None:
            self._loop = _get_loop()

        return self._loop

    def _require_bound_loop(self) -> AbstractEventLoop:
        bound = self._get_bound_loop()
        if bound is None:
            raise RuntimeError("No event loop is running.")

        return bound


def _get_loop() -> AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except Exception:
        return None


async def _run_in_loop[T](
    coroutine: Coroutine[T, Any, Any],
    bound_loop: AbstractEventLoop,
    running_loop: AbstractEventLoop | None = None,
):
    # Schedule `coroutine` on the bound loop, then block this loop's executor until the
    # bound loop's future completes. This bridges loops without busy-waiting.
    from threading import Event

    if running_loop is None:
        running_loop = asyncio.get_running_loop()

    future = asyncio.run_coroutine_threadsafe(coroutine, bound_loop)
    finished = Event()

    def callback(_: object):
        finished.set()

    future.add_done_callback(callback)

    await running_loop.run_in_executor(None, finished.wait)
    return future.result()
