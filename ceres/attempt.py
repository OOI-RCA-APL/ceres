from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator, Literal, NoReturn

from typing_extensions import Self, override

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres._internal.utilities import decode_td


@dataclass
class AttemptFailure:
    reason: str | None = None
    exception: Exception | None = None


class AttemptFailureException(Exception):
    def __init__(self, failure: AttemptFailure) -> None:
        self.failure = failure


class Attempt:
    def __init__(
        self,
        index: int,
        max: int,
        interval: float | timedelta = timedelta(),
    ) -> None:
        self.__index = index
        self.__max = max
        self.__interval = decode_td(interval)
        self.__executed = False
        self.__failure: AttemptFailure | None = None

    @property
    def index(self) -> int:
        return self.__index

    @property
    def number(self) -> int:
        return self.__index + 1

    @property
    def max(self) -> int:
        return self.__max

    @property
    def interval(self) -> timedelta:
        return self.__interval

    @property
    def executed(self) -> bool:
        return self.__executed

    @property
    def failure(self) -> AttemptFailure | None:
        return self.__failure

    @property
    def completed(self) -> bool:
        return self.__executed and self.__failure is None

    @property
    def failed(self) -> bool:
        return self.__executed and self.__failure is not None

    async def __aenter__(self) -> Self:
        if self.__executed:
            raise RuntimeError("attempt already executed")

        return self

    async def __aexit__(
        self,
        type: object,
        exception: Exception | None,
        traceback: object,
    ) -> Literal[True]:
        self.__executed = True
        if isinstance(exception, AttemptFailureException):
            self.__failure = exception.failure
        elif self.__failure is None and exception is not None:
            self.__failure = AttemptFailure(reason=None, exception=exception)

        if self.__index + 1 < self.max:
            await asyncio.sleep(self.interval.total_seconds())

        return True

    def fail(
        self,
        reason: str | None = None,
        exception: Exception | None = None,
    ) -> NoReturn:
        self.__executed = True
        self.__failure = AttemptFailure(reason=reason, exception=exception)
        raise AttemptFailureException(self.__failure)


class Attempts(Iterator[Attempt]):
    def __init__(
        self,
        max: int,
        interval: float | timedelta = timedelta(),
    ) -> None:
        if max < 1:
            raise ValueError("max must be greater than 1")

        self.__max = max
        self.__index = -1
        self.__last: Attempt | None = None
        self.__interval = decode_td(interval)

    @property
    def max(self) -> int:
        return self.__max

    @property
    def index(self) -> int:
        return self.__index

    @property
    def number(self) -> int:
        return self.__index + 1

    @property
    def interval(self) -> timedelta:
        return self.__interval

    @property
    def last(self) -> Attempt | None:
        return self.__last

    @property
    def failure(self) -> AttemptFailure | None:
        if self.__last is None:
            return None

        return self.__last.failure

    @property
    def completed(self) -> bool:
        return self.__last is not None and self.__last.completed

    @property
    def failed(self) -> bool:
        return self.__last is not None and self.__last.failed

    @property
    def exhausted(self) -> bool:
        return self.__index > self.__max

    @override
    def __iter__(self) -> Self:
        return self

    @override
    def __next__(self) -> Attempt:
        if self.completed or self.exhausted:
            raise StopIteration
        self.__index += 1
        self.__last = Attempt(self.__index, self.__max, self.__interval)
        return self.__last
