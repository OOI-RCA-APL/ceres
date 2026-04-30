import re
from abc import abstractmethod
from collections.abc import Iterator
from dataclasses import field
from re import Pattern
from typing import TYPE_CHECKING, Literal, override

from ceres.data import DataObject, PositiveTimeDelta

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic import PositiveInt

    from ceres.connection.buffer import Buffer

__all__ = [
    "Splitter",
    "Unsplit",
    "SplitByChunk",
    "SplitByLine",
    "SplitByRegex",
    "SplitByDelay",
]


class Splitter(DataObject.Frozen, abstract=True):
    """Determine where to slice a `Buffer` into framed pieces.

    Subclasses yield exclusive end indices into the buffer's current contents. Each yielded
    index marks the boundary between two consecutive logical frames, the bytes from the previous
    yield (or zero) up to (but not including) the yielded index form one frame.
    """

    @abstractmethod
    def split(self, buffer: Buffer) -> Iterator[int]:
        """Yield exclusive end indices marking frame boundaries within `buffer`.

        Args:
            buffer: The `Buffer` to inspect. The splitter must not modify it.

        Yields:
            Strictly increasing exclusive end indices into `buffer`.
        """
        ...


class Unsplit(Splitter):
    """Treat the entire buffer as a single frame."""

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        """Yield the buffer's total size as a single boundary if the buffer is non-empty."""
        if buffer:
            yield buffer.size


class SplitByChunk(Splitter):
    """Split on the original push boundaries recorded by the buffer."""

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        """Yield the end index of each chunk stored in the buffer."""
        if buffer:
            for chunk in buffer.chunks:
                yield chunk.end


_SPLIT_BY_LINE_PATTERN = re.compile(b"\n")


class SplitByLine(Splitter):
    """Split on each newline (`\\n`), inclusive of the newline byte itself."""

    @property
    def pattern(self) -> Pattern[bytes]:
        """The compiled regex used to locate line breaks."""
        return _SPLIT_BY_LINE_PATTERN

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        """Yield the end index of each newline match found in the buffer."""
        if buffer:
            for match in self.pattern.finditer(buffer):
                yield match.end()


type SplitByRegexMode = Literal["prefix", "suffix", "infix"]
"""How a `SplitByRegex` treats each match relative to the surrounding frames.

- `"prefix"`: The match starts a new frame, yielding `match.start()`.
- `"suffix"`: The match ends a frame, yielding `match.end()`.
- `"infix"`: The match is its own frame, yielding both `match.start()` and `match.end()`.
"""


class SplitByRegex(Splitter):
    """Split wherever a regular expression matches, with placement controlled by `mode`."""

    type Mode = SplitByRegexMode

    pattern: Pattern[bytes] = field(kw_only=False)
    """The compiled regex applied to the buffer's bytes."""
    mode: Mode = "suffix"
    """Where the match falls relative to its surrounding frames, see `SplitByRegexMode`."""

    if TYPE_CHECKING:

        def __init__(
            self,
            pattern: bytes | Pattern[bytes],
            *,
            mode: SplitByRegexMode = "suffix",
        ) -> None: ...

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        """Yield boundary indices for each regex match, placed according to `mode`."""
        if not buffer:
            return

        for match in self.pattern.finditer(buffer):
            match self.mode:
                case "prefix":
                    yield match.start()
                case "suffix":
                    yield match.end()
                case "infix":
                    yield match.start()
                    yield match.end()


class SplitByDelay(Splitter):
    """Split whenever the gap between consecutive chunks meets or exceeds `delay`."""

    delay: PositiveTimeDelta = field(kw_only=False)
    """Minimum inter-chunk delay that triggers a split."""

    if TYPE_CHECKING:

        def __init__(self, delay: PositiveInt | PositiveTimeDelta) -> None: ...

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        """Yield a boundary at each chunk whose gap from the prior chunk meets `delay`."""
        if not buffer:
            return

        previous: datetime | None = buffer.earliest_timestamp
        for chunk in buffer.chunks:
            if previous is not None:
                if (chunk.timestamp - previous) >= self.delay:
                    yield chunk.start

            previous = chunk.timestamp
