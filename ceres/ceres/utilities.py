from concurrent.futures import ThreadPoolExecutor
from typing import Callable, ParamSpec, TypeVar

from .internal.utilities import ensure_event_loop

_P = ParamSpec("_P")
_T = TypeVar("_T")


async def spawn(function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    def run() -> _T:
        return function(*args, **kwargs)

    executor = ThreadPoolExecutor()
    return await ensure_event_loop().run_in_executor(executor, run)
