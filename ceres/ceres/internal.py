import asyncio
import inspect
from functools import wraps
from typing import Awaitable, TypeVar, cast

import uvloop

T = TypeVar("T")


async def awaitify(value: "T | Awaitable[T]") -> T:
    if inspect.isawaitable(value):
        return await value

    return cast(T, value)


def entrypoint(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        uvloop.install()
        return asyncio.run(function(*args, **kwargs))

    return wrapper
