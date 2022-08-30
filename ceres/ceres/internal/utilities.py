from __future__ import annotations

import inspect
import signal
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Iterator, Sequence, TypeVar, cast

T = TypeVar("T")


async def awaitify(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


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
