import asyncio
import inspect
from functools import wraps
from typing import Any, Awaitable, Callable, Dict, List, TypeVar, cast

import uvloop

T = TypeVar("T")


async def awaitify(value: "T | Awaitable[T]") -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


def entrypoint(function: Callable[..., Any]) -> Any:
    @wraps(function)
    def wrapper(*args: List[Any], **kwargs: Dict[str, Any]) -> Any:
        uvloop.install()
        return asyncio.run(function(*args, **kwargs))

    return wrapper
