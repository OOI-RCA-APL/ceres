from __future__ import annotations

from typing import Callable, ParamSpec, TypeVar

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from concurrent.futures import ThreadPoolExecutor

    from ceres._internal import util

_P = ParamSpec("_P")
_T = TypeVar("_T")


async def spawn(function: Callable[_P, _T], *args: _P.args, **kwargs: _P.kwargs) -> _T:
    def run() -> _T:
        return function(*args, **kwargs)

    with ThreadPoolExecutor() as executor:
        return await util.ensure_event_loop().run_in_executor(executor, run)
