from __future__ import annotations

import asyncio
import inspect
import signal
from contextlib import contextmanager
from functools import wraps
from typing import Any, Awaitable, Callable, Iterator, Sequence, TypeVar, cast

import uvloop
from pydantic import ValidationError

T = TypeVar("T")


async def awaitify(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


def syncify(function: Callable[..., Any]) -> Any:
    @wraps(function)
    def wrapper(*args: list[Any], **kwargs: dict[str, Any]) -> Any:
        uvloop.install()
        return asyncio.run(function(*args, **kwargs))

    return wrapper


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


def format_validation_error(error: ValidationError) -> dict[str, Any]:
    return {
        ".".join(str(value) for value in error["loc"]): error["msg"] for error in error.errors()
    }
