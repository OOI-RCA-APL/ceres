from __future__ import annotations

import asyncio
import inspect
import json
import re
import signal
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterator,
    MutableMapping,
    NoReturn,
    Sequence,
    TypeVar,
    Union,
    cast,
)

import anyio
import uvloop
from anyio import CapacityLimiter
from pydantic import ConstrainedStr
from pydantic.json import pydantic_encoder
from sqlalchemy.orm import Mapped

T = TypeVar("T")

MaybeMapped = Union[T, Mapped[T]]


async def awaitify(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


def jsonify(object: object, *, indent: int | str | None = None, **kwargs: Any) -> str:
    return json.dumps(pydantic_encoder(object), indent=indent, **kwargs)


def simplify(object: object) -> Any:
    return pydantic_encoder(object)


FunctionT = TypeVar("FunctionT", bound=Callable[..., Any])


def syncify(function: FunctionT) -> FunctionT:
    if not inspect.iscoroutinefunction(function):
        return function

    @wraps(function)
    def wrapper(*args: list[Any], **kwargs: dict[str, Any]) -> Any:
        uvloop.install()
        return asyncio.run(function(*args, **kwargs))

    return cast(FunctionT, wrapper)


async def run_in_thread(
    function: Callable[..., T],
    *args: Any,
    cancellable: bool = False,
    limiter: CapacityLimiter | None = None,
) -> T:
    return await anyio.to_thread.run_sync(
        function,
        *args,
        cancellable=cancellable,
        limiter=limiter,
    )


def get_now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def use_signal_handler(signums: Sequence[int], handler: Callable[..., Any]) -> Iterator[None]:
    originals: dict[int, Any] = {}
    for signum in signums:
        if original := signal.getsignal(signum):
            originals[signum] = original
        signal.signal(signum, handler)

    try:
        yield
    finally:
        for signum, original in originals.items():
            signal.signal(signum, original)


class UnreachableException(Exception):
    def __init__(self) -> None:
        self.message = "Unexpected code was reached. This is a bug."


def unreachable() -> NoReturn:
    raise UnreachableException()


def get_or_create(mapping: MutableMapping[str, T], key: str, factory: Callable[[], T]) -> T:
    if key in mapping:
        return mapping[key]

    value = factory()
    mapping[key] = value
    return value


def encode_td(value: timedelta) -> str:
    if value < timedelta(milliseconds=1):
        encoded_value, encoded_unit = float(value.microseconds), "us"
    elif value < timedelta(seconds=1):
        encoded_value, encoded_unit = value.microseconds / 1000, "ms"
    elif value < timedelta(minutes=1):
        encoded_value, encoded_unit = value.total_seconds(), "s"
    elif value < timedelta(hours=1):
        encoded_value, encoded_unit = value.total_seconds() / 60, "m"
    elif value < timedelta(days=1):
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60), "h"
    else:
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60 * 24), "d"

    return f"{str(encoded_value).rstrip('0').rstrip('.')}{encoded_unit}"


def show_td(value: timedelta) -> str:
    if value < timedelta(milliseconds=1):
        encoded_value, encoded_unit = float(value.microseconds), "microseconds"
    elif value < timedelta(seconds=1):
        encoded_value, encoded_unit = value.microseconds / 1000, "milliseconds"
    elif value < timedelta(minutes=1):
        encoded_value, encoded_unit = value.total_seconds(), "seconds"
    elif value < timedelta(hours=1):
        encoded_value, encoded_unit = value.total_seconds() / 60, "minutes"
    elif value < timedelta(days=1):
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60), "hours"
    else:
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60 * 24), "days"

    return f"{str(encoded_value).rstrip('0').rstrip('.')} {encoded_unit}"


def decode_td(value: str | timedelta | Any) -> timedelta:
    if isinstance(value, timedelta):
        return value

    def get_exception() -> ValueError:
        return ValueError(
            "invalid timedelta value, must be a number with suffix 'us', 'ms', 's', 'm', 'h' or 'd'."
        )

    if not isinstance(value, str):
        raise get_exception()

    if value.endswith("us"):
        decoded_unit = "us"
    elif value.endswith("ms"):
        decoded_unit = "ms"
    elif value.endswith("s"):
        decoded_unit = "s"
    elif value.endswith("m"):
        decoded_unit = "m"
    elif value.endswith("h"):
        decoded_unit = "h"
    elif value.endswith("d"):
        decoded_unit = "d"
    else:
        raise get_exception()

    try:
        decoded_value = float(value[: -len(decoded_unit)])
    except Exception:
        raise get_exception()

    match decoded_unit:
        case "us":
            return timedelta(microseconds=decoded_value)
        case "ms":
            return timedelta(milliseconds=decoded_value)
        case "s":
            return timedelta(seconds=decoded_value)
        case "m":
            return timedelta(minutes=decoded_value)
        case "h":
            return timedelta(hours=decoded_value)
        case "d":
            return timedelta(days=decoded_value)

    raise get_exception()


def literals(literal: type[Enum] | object) -> tuple[str, ...]:
    if isinstance(literal, type) and issubclass(literal, Enum):
        return tuple(value.value for value in literal if isinstance(value, str))

    __args__ = getattr(literal, "__args__", None)

    if isinstance(__args__, tuple):
        return tuple(value for value in __args__ if isinstance(value, str))

    return tuple()


class NameStr(ConstrainedStr):
    regex = re.compile(r"[a-zA-Z\-\_][a-zA-Z0-9\-\_]*")


class EmailStr(ConstrainedStr):
    regex = re.compile(r".+@.+")


class NonEmptyStr(ConstrainedStr):
    regex = re.compile(r".+")
