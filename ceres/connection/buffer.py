from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, NamedTuple, overload, override

from ceres.timing import utc

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from ceres.connection.splitter import Splitter
    from ceres.data import BytesLike


@dataclass(slots=True)
class Chunk:
    data: bytes
    timestamp: datetime


@dataclass
class VirtualChunk:
    __slots__ = (
        "source",
        "start",
        "end",
        "timestamp",
        "_data",
    )

    source: Final[bytes | bytearray]
    start: Final[int]
    end: Final[int]
    timestamp: Final[datetime]

    def __post_init__(self) -> None:
        self._data: bytes | None = None

    @property
    def span(self) -> tuple[int, int]:
        return self.start, self.end

    @property
    def data(self) -> bytes:
        data = self._data
        if data is None:
            data = bytes(self.source[self.start : self.end])
            self._data = data

        return data

    def resolve(self) -> Chunk:
        return Chunk(self.data, self.timestamp)


type ChunkInput = tuple[BytesLike, datetime | timedelta]


class _Entry(NamedTuple):
    end_position: int
    timestamp: datetime


class Buffer:
    """
    A buffer for storing incoming bytes along with associated timestamps for each logical "chunk"
    received/sent over a connection. Works as a FIFO queue of byte chunks.
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
        self._entries: list[_Entry] = []  # A list of (end position, timestamp) tuples.
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

    def __contains__(self, item: bytes) -> bool:
        return item in self.data

    def __bool__(self) -> bool:
        return bool(self._data)

    @overload
    def __get_item__(self, index: int, /) -> int: ...

    @overload
    def __get_item__(self, index: slice, /) -> bytes: ...

    def __get_item__(self, index: int | slice, /) -> int | bytes:
        if isinstance(index, slice):
            return bytes(self._data[index])

        return self._data[index]

    def __iter__(self) -> Iterator[int]:
        yield from self._data

    @property
    def size(self) -> int:
        return len(self._data)

    @property
    def data(self) -> bytes:
        if self._data_bytes is None:
            self._data_bytes = bytes(self._data)

        return self._data_bytes

    @property
    def chunks(self) -> Iterator[VirtualChunk]:
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
        from ceres.connection.splitter import SplitByChunk

        if splitter is None:
            splitter = SplitByChunk()

        previous: VirtualChunk | None = None
        for split in splitter.split(self):
            timestamp = self.timestamp_at(split - 1)
            if timestamp is None:
                continue

            start = 0 if previous is None else previous.end
            end = split

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
        if self._entries:
            return self._entries[0].timestamp

        return self.latest_timestamp

    @property
    def latest_timestamp(self) -> datetime | None:
        return self._latest_timestamp

    def push(self, data: BytesLike, time: datetime | timedelta | None = None, /) -> None:
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
                self._entries[-1] = _Entry(
                    last_entry.end_position + len(data), last_entry.timestamp
                )
                return
        else:
            self._entries.append(_Entry(end, timestamp))

        self._latest_timestamp = timestamp

    def extend(self, records: Iterable[ChunkInput]) -> None:
        for data, timestamp in records:
            self.push(data, timestamp)

    def pop(self, count: int) -> Chunk | None:
        if count <= 0:
            return None

        count = min(count, self.size)
        entry_index = self._get_entry_index_at(count - 1)
        if entry_index is None:
            return None

        entry = self._entries[entry_index]
        next_start_position = self._start_position + count
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
            self._start_position = 0

        return Chunk(data, entry.timestamp)

    def pop_to_size(self, limit: int, by: int = 1) -> Chunk | None:
        excess = self.size - limit
        if excess <= 0:
            return None

        # Figure out how many times when need to pop `by` bytes from the beginning of the buffer to
        # get below a byte length of `limit`.
        pops = excess // by
        # If there is a remainder, we need to drop one more time.
        if excess % by != 0:
            pops += 1

        popped_byte_count = pops * by
        return self.pop(popped_byte_count)

    def clear(self) -> None:
        self._data.clear()
        self._data_bytes = None
        self._start_position = 0
        self._entries.clear()
        self._latest_timestamp = None

    def chunk_at(self, index: int) -> VirtualChunk | None:
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
        entry = self._get_entry_at(index)
        if entry is not None:
            return entry.timestamp

        return None

    def _get_entry_index_at(self, index: int) -> int | None:
        if index < 0 or index >= len(self._data):
            return None

        import bisect

        return bisect.bisect_left(
            self._entries,
            self._start_position + index,
            key=lambda x: x.end_position,
        )

    def _get_entry_at(self, index: int) -> _Entry | None:
        entry_index = self._get_entry_index_at(index)
        if entry_index is None:
            return None

        return self._entries[entry_index]
