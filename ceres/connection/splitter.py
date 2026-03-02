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
    @abstractmethod
    def split(self, buffer: Buffer) -> Iterator[int]: ...


class Unsplit(Splitter):
    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        if buffer:
            yield buffer.size


class SplitByChunk(Splitter):
    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        if buffer:
            for chunk in buffer.chunks:
                yield chunk.end


_SPLIT_BY_LINE_PATTERN = re.compile(b"\n")


class SplitByLine(Splitter):
    @property
    def pattern(self) -> Pattern[bytes]:
        return _SPLIT_BY_LINE_PATTERN

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        if buffer:
            for match in self.pattern.finditer(buffer):
                yield match.end()


type SplitByRegexMode = Literal["prefix", "suffix", "infix"]


class SplitByRegex(Splitter):
    type Mode = SplitByRegexMode

    pattern: Pattern[bytes] = field(kw_only=False)
    mode: Mode = "suffix"

    if TYPE_CHECKING:

        def __init__(
            self,
            pattern: bytes | Pattern[bytes],
            *,
            mode: SplitByRegexMode = "suffix",
        ) -> None: ...

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        if not buffer:
            return

        for match in self.pattern.finditer(buffer):
            match self.mode:
                case "suffix":
                    yield match.start()
                case "prefix":
                    yield match.end()
                case "infix":
                    yield match.start()
                    yield match.end()


class SplitByDelay(Splitter):
    delay: PositiveTimeDelta = field(kw_only=False)

    if TYPE_CHECKING:

        def __init__(self, delay: PositiveInt | PositiveTimeDelta) -> None: ...

    @override
    def split(self, buffer: Buffer) -> Iterator[int]:
        if not buffer:
            return

        previous: datetime | None = buffer.earliest_timestamp
        for chunk in buffer.chunks:
            if previous is not None:
                if (chunk.timestamp - previous) >= self.delay:
                    yield chunk.start

            previous = chunk.timestamp

        return None
