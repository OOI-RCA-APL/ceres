import re
from functools import lru_cache
from re import Pattern
from typing import Callable

from .exceptions import ParseException


class Parser:
    def __init__(self, content: bytes) -> None:
        self._characters = content
        self._index = 0
        self._remaining: bytes | None = content

    @property
    def characters(self) -> bytes:
        return self._characters

    @property
    def index(self) -> int:
        return self._index

    @index.setter
    def index(self, value: int) -> None:
        value = max(value, 0)
        value = min(value, len(self.characters))
        if value == self._index:
            return

        self._index = value
        self._remaining = None

    @property
    def remaining(self) -> bytes:
        if self._remaining is None:
            self._remaining = self._characters[self.index :]

        return self._remaining

    def peek(self, offset: int = 0, length: int = 1) -> bytes | None:
        start = self.index + offset
        result = self._characters[start : start + length]
        if result == b"":
            return None

        return result

    def next(self) -> bytes | None:
        character = self.peek()
        if not character:
            return None

        self.index += 1
        return character

    def eat_while(self, condition: Callable[[bytes], bool]) -> bytes:
        result = b""

        while True:
            character = self.peek()
            if not character:
                break
            if not condition(character):
                break

            result += character
            self.next()

        return result

    def try_eat(self, sequence: bytes) -> bool:
        if self.remaining.startswith(sequence):
            self.index += len(sequence)
            return True

        return False

    def eat(self, sequence: bytes) -> None:
        if not self.try_eat(sequence):
            raise ParseException(f"expected {repr(sequence)}, got {repr(self.remaining)}")

    def try_eat_pattern(self, pattern: bytes) -> bytes | None:
        try:
            regex = _get_regex(pattern)
        except re.error:
            raise ValueError(f"invalid regular expression {repr(pattern)}")

        if match := regex.match(self.remaining, 0):
            group = match.group()
            self._index += len(group)
            return group

        return None

    def eat_pattern(self, pattern: bytes) -> bytes:
        if result := self.try_eat_pattern(pattern):
            return result

        raise ParseException(f"expected pattern {repr(pattern)}, got {repr(self.remaining)}")

    def try_eat_int(self) -> int | None:
        if result := self.try_eat_pattern(rb"([\+\-])?[0-9]+"):
            return int(result.decode())

        return None

    def eat_int(self) -> int:
        if (result := self.try_eat_int()) is not None:
            return result

        raise ParseException(f"expected integer number, got {repr(self.remaining)}")

    def try_eat_float(self) -> float | None:
        if result := self.try_eat_pattern(rb"[\+\-]?([0-9]*\.[0-9]+|[0-9]+)"):
            return float(result.decode())

        return None

    def eat_float(self) -> float:
        if (result := self.try_eat_float()) is not None:
            return result

        raise ParseException(f"expected floating-point number, got {repr(self.remaining)}")

    def try_eat_space(self) -> bytes | None:
        result = b""

        while (current := self.peek()) and current.isspace():
            self.next()
            result += current

        if not result:
            return None

        return result

    def eat_space(self) -> bytes:
        if (result := self.try_eat_space()) is not None:
            return result

        raise ParseException(f"expected whitespace, got {repr(self.remaining)}")


@lru_cache(maxsize=5000, typed=True)
def _get_regex(pattern: bytes) -> Pattern[bytes]:
    return re.compile(pattern)
