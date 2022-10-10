from __future__ import annotations

import inspect
import json
import signal
from contextlib import contextmanager
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterator,
    MutableMapping,
    NoReturn,
    Sequence,
    TypeVar,
    cast,
)

from pydantic.json import pydantic_encoder

T = TypeVar("T")


async def awaitify(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


def jsonify(object: object, *, indent: int | str | None = None, **kwargs: Any) -> str:
    return json.dumps(pydantic_encoder(object), indent=indent, **kwargs)


def simplify(object: object) -> Any:
    return pydantic_encoder(object)


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
