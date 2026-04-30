from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, NamedTuple, SupportsIndex, overload, override

from ceres.data import ToBytes
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.connection.splitter import Splitter

__all__ = [
    "Chunk",
    "VirtualChunk",
    "Buffer",
]


@dataclass(slots=True)
class Chunk:
    """A timestamped block of bytes received from or sent over a connection."""

    data: bytes
    """The raw byte payload."""
    timestamp: datetime
    """The time at which this chunk was observed."""


type ChunkInput = Chunk | tuple[ToBytes, datetime | timedelta]
"""Anything that can be pushed into a `Buffer` as a single chunk.

Either a `Chunk` instance or a `(data, time)` tuple where `time` is an absolute `datetime` or
a `timedelta` offset from the previous chunk's timestamp.
"""


@dataclass(slots=True)
class VirtualChunk:
    """A view into a slice of a `Buffer`'s underlying byte storage.

    `VirtualChunk` avoids copying bytes until `data` is read. The view is only valid as long as
    the underlying source has not been modified at or before `end`.
    """

    source: bytes | bytearray | memoryview
    """The underlying byte storage being viewed."""
    start: int
    """Inclusive start index into `source`."""
    end: int
    """Exclusive end index into `source`."""
    timestamp: datetime
    """The timestamp associated with this slice."""

    _data: bytes | None = field(default=None, init=False)

    @property
    def span(self) -> tuple[int, int]:
        """The `(start, end)` index pair this chunk occupies in `source`."""
        return self.start, self.end

    @property
    def data(self) -> bytes:
        """The bytes covered by this view, materialized and cached on first access."""
        data = self._data
        if data is None:
            data = bytes(self.source[self.start : self.end])
            self._data = data

        return data

    def resolve(self) -> Chunk:
        """Return a `Chunk` carrying a copy of the viewed bytes and this chunk's timestamp."""
        return Chunk(self.data, self.timestamp)


class _BufferEntry(NamedTuple):
    """An internal index entry tracking the exclusive end position of a chunk in a `Buffer`."""

    end_position: int
    timestamp: datetime


class Buffer:
    """A FIFO queue of timestamped byte chunks backed by a single contiguous bytearray.

    `Buffer` accumulates incoming bytes from a connection along with the timestamp at which
    each chunk was observed. Bytes are stored in one contiguous `bytearray`, while a parallel
    list of `(end_position, timestamp)` entries records the boundary and time of each pushed
    chunk. Adjacent chunks with the same timestamp are merged into a single entry.

    Indexing into the buffer is byte-oriented and zero-based relative to the current contents,
    independent of how many bytes have been popped from the front.
    """

    __slots__ = (
        "_data",
        "_data_bytes",
        "_start_position",
        "_entries",
        "_latest_timestamp",
    )

    def __init__(self, chunks: Iterable[ChunkInput] | None = None) -> None:
        self._data = bytearray()
        self._data_bytes: bytes | None = None  # Cache for bytes representation.
        self._start_position = 0
        self._entries: list[_BufferEntry] = []  # A list of (end position, timestamp) tuples.
        self._latest_timestamp: datetime | None = None

        if chunks is not None:
            self.extend(chunks)

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Buffer):
            return NotImplemented

        if self._data != other._data:
            return False
        if len(self._entries) != len(other._entries):
            return False
        for ours, theirs in zip(self.chunks, other.chunks):
            if ours != theirs:
                return False

        return True

    @override
    def __repr__(self) -> str:
        chunks = [(chunk.data, chunk.timestamp) for chunk in self.chunks]
        return f"{self.__class__.__name__}({chunks!r})"

    @override
    def __str__(self) -> str:
        return self.__repr__()

    def __bytes__(self) -> bytes:
        return self.data

    def __buffer__(self, flags: int, /) -> memoryview:
        return memoryview(self._data).toreadonly()

    def __len__(self) -> int:
        return self.size

    def __contains__(self, item: SupportsIndex) -> bool:
        return item in self._data

    def __bool__(self) -> bool:
        return bool(self._data)

    @overload
    def __getitem__(self, index: int, /) -> int: ...

    @overload
    def __getitem__(self, index: slice, /) -> bytes: ...

    def __getitem__(self, index: int | slice, /) -> int | bytes:
        if isinstance(index, slice):
            return bytes(self._data[index])

        return self._data[index]

    def __iter__(self) -> Iterator[int]:
        yield from self._data

    @property
    def size(self) -> int:
        """Total number of bytes currently held in the buffer."""
        return len(self._data)

    @property
    def data(self) -> bytes:
        """All buffered bytes as an immutable `bytes` object, cached between mutations."""
        if self._data_bytes is None:
            self._data_bytes = bytes(self._data)

        return self._data_bytes

    @property
    def chunks(self) -> Iterator[VirtualChunk]:
        """Iterate over the original push boundaries as `VirtualChunk` views.

        Adjacent pushes that shared a timestamp are emitted as one merged chunk.
        """
        previous_position = self._start_position
        for entry in self._entries:
            start = previous_position - self._start_position
            end = entry.end_position - self._start_position

            yield VirtualChunk(self._data, start, end, entry.timestamp)
            previous_position = entry.end_position

    def split(
        self,
        splitter: Splitter | None = None,
        *,
        linearize: bool = False,
    ) -> Iterator[VirtualChunk]:
        """Yield `VirtualChunk` views of the buffer split according to `splitter`.

        Args:
            splitter: The `Splitter` to use, defaults to `SplitByChunk` which preserves the
                original push boundaries.
            linearize: If true, force each yielded chunk's timestamp to be strictly greater than
                the previous chunk's timestamp by nudging duplicates forward by one microsecond.

        Yields:
            `VirtualChunk` instances covering successive non-overlapping byte ranges.
        """
        from ceres.connection.splitter import SplitByChunk

        if splitter is None:
            splitter = SplitByChunk()

        previous: VirtualChunk | None = None
        for split in splitter.split(self):
            # The splitter yields exclusive end indices, look up the timestamp at the last byte
            # included in the chunk.
            timestamp = self.timestamp_at(split - 1)
            if timestamp is None:
                continue

            start = 0 if previous is None else previous.end
            end = split

            # Ignore degenerate splits that would produce an empty or backwards range.
            if end <= start:
                continue

            if linearize and previous is not None:
                if timestamp <= previous.timestamp:
                    timestamp = previous.timestamp + timedelta(microseconds=1)

            chunk = VirtualChunk(self._data, start, end, timestamp)
            previous = chunk
            yield chunk

    def drain(
        self,
        splitter: Splitter | None = None,
        *,
        linearize: bool = False,
    ) -> list[Chunk]:
        """Split the buffer with `splitter`, pop the consumed bytes, and return the chunks.

        Args:
            splitter: The `Splitter` to use, defaults to `SplitByChunk`.
            linearize: See `split()`.

        Returns:
            The drained `Chunk` objects in order. Bytes after the last split are left in the
            buffer untouched.
        """
        chunks: list[Chunk] = []
        end: int | None = None
        for chunk in self.split(splitter, linearize=linearize):
            end = chunk.end
            chunks.append(chunk.resolve())

        if end is not None:
            self.pop(end)

        return chunks

    @property
    def earliest_timestamp(self) -> datetime | None:
        """Timestamp of the oldest entry, or the latest timestamp if the buffer is empty."""
        if self._entries:
            return self._entries[0].timestamp

        return self.latest_timestamp

    @property
    def latest_timestamp(self) -> datetime | None:
        """Timestamp of the most recently pushed chunk, or `None` if no data was ever pushed."""
        return self._latest_timestamp

    @overload
    def push(self, data: ToBytes, time: datetime | timedelta | None = None, /) -> None: ...
    @overload
    def push(self, data: ChunkInput, /) -> None: ...
    @overload
    def push(self, data: ChunkInput, time: datetime | timedelta | None = None, /) -> None: ...
    def push(
        self,
        data: ToBytes | ChunkInput,
        time: datetime | timedelta | None = None,
        /,
    ) -> None:
        """Append `data` to the buffer with the given timestamp.

        If `time` is `None`, default to `utc()` when no prior data exists, otherwise reuse the
        latest timestamp. If `time` is a `timedelta`, treat it as an offset from the latest
        timestamp (or from `utc()` when the buffer is empty). When `data` is a `Chunk` or
        `(data, time)` tuple, the explicit `time` argument takes precedence over the embedded
        time when provided.

        Adjacent pushes that share a timestamp are merged into the same internal entry to keep
        the index compact.

        Raises:
            ValueError: If the resolved timestamp is earlier than `latest_timestamp`.
        """
        if isinstance(data, tuple):
            data, data_time = data
            if time is None:
                time = data_time
        if isinstance(data, Chunk):
            data_time = data.timestamp
            data = data.data
            if time is None:
                time = data_time

        data = bytes(data)
        if not data:
            return

        latest = self.latest_timestamp

        if time is None:
            timestamp = utc()
        elif isinstance(time, timedelta):
            if latest is None:
                timestamp = utc() + time
            else:
                timestamp = latest + time
        else:
            timestamp = time

        if self._entries and latest is not None:
            if timestamp < latest:
                raise ValueError("Cannot push data with timestamp earlier than latest timestamp.")

        start = self._start_position + len(self._data)
        end = start + len(data)
        self._data.extend(data)
        self._data_bytes = None

        if timestamp == latest:
            if self._entries:
                last_entry = self._entries[-1]
                self._entries[-1] = _BufferEntry(
                    last_entry.end_position + len(data),
                    last_entry.timestamp,
                )
                return

        self._entries.append(_BufferEntry(end, timestamp))
        self._latest_timestamp = timestamp

    def extend(self, records: Iterable[ChunkInput]) -> None:
        """Push each item in `records` into the buffer in order."""
        for current in records:
            self.push(current)

    def pop(self, count: int) -> Chunk | None:
        """Remove the first `count` bytes from the buffer.

        Args:
            count: Number of bytes to remove from the front of the buffer. Values clamp to the
                current buffer size.

        Returns:
            A `Chunk` carrying the popped bytes and the timestamp of the entry that contained
            the last popped byte, or `None` if `count <= 0` or the buffer is empty.
        """
        if count <= 0:
            return None

        count = min(count, self.size)
        entry_index = self._get_entry_index_at(count - 1)
        if entry_index is None:
            return None

        entry = self._entries[entry_index]
        next_start_position = self._start_position + count
        # If we removed every byte covered by the boundary entry, drop the entry itself.
        next_entry_index = (
            entry_index + 1 if entry.end_position <= next_start_position else entry_index
        )

        data = bytes(self._data[:count])
        del self._data[:count]
        self._data_bytes = None

        del self._entries[:next_entry_index]

        if self._entries:
            self._start_position = next_start_position
        else:
            # Reset the absolute position counter when the buffer empties, this keeps the
            # internal indices small over the buffer's lifetime.
            self._start_position = 0

        return Chunk(data, entry.timestamp)

    def pop_to(self, size: int, by: int = 1) -> Chunk | None:
        """Pop bytes in multiples of `by` until the buffer fits within `size` bytes.

        Args:
            size: Target maximum buffer size in bytes.
            by: Granularity at which bytes are dropped, the actual pop count is rounded up to the
                next multiple of `by`.

        Returns:
            The `Chunk` returned by the underlying `pop()`, or `None` when no bytes need to be
            dropped.
        """
        excess = self.size - size
        if excess <= 0:
            return None

        # Determine how many `by`-sized blocks must be dropped to bring the buffer under `size`.
        pops = excess // by
        # Round up to cover any remainder.
        if excess % by != 0:
            pops += 1

        popped_byte_count = pops * by
        return self.pop(popped_byte_count)

    def clear(self) -> None:
        """Remove all data and reset internal indices, leaving the buffer empty."""
        self._data.clear()
        self._data_bytes = None
        self._start_position = 0
        self._entries.clear()
        self._latest_timestamp = None

    def chunk_at(self, index: int) -> VirtualChunk | None:
        """Return the `VirtualChunk` covering the byte at `index`, or `None` if out of bounds."""
        entry_index = self._get_entry_index_at(index)
        if entry_index is None:
            return None

        entry = self._entries[entry_index]

        if entry_index > 0:
            previous = self._entries[entry_index - 1]
            start = previous.end_position - self._start_position
        else:
            start = 0

        end = entry.end_position - self._start_position
        return VirtualChunk(self._data, start, end, entry.timestamp)

    def timestamp_at(self, index: int) -> datetime | None:
        """Return the timestamp of the chunk containing the byte at `index`, or `None`."""
        entry = self._get_entry_at(index)
        if entry is not None:
            return entry.timestamp

        return None

    def _get_entry_index_at(self, index: int) -> int | None:
        """Return the index of the entry whose byte range contains `index`, or `None`.

        End positions are exclusive, so `bisect_right` is required to map an index that falls
        on a chunk boundary to the chunk that begins at that boundary rather than the one that
        ends there.
        """
        if index < 0 or index >= len(self._data):
            return None

        import bisect

        return bisect.bisect_right(
            self._entries,
            self._start_position + index,
            key=lambda x: x.end_position,
        )

    def _get_entry_at(self, index: int) -> _BufferEntry | None:
        entry_index = self._get_entry_index_at(index)
        if entry_index is None:
            return None

        return self._entries[entry_index]
