from __future__ import annotations

from typing import TYPE_CHECKING

from ceres._internal import util
from ceres._internal.lazy import lazy_imports

if TYPE_CHECKING:
    from collections.abc import Callable

with lazy_imports(__name__):
    from concurrent.futures import ThreadPoolExecutor


async def spawn[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    def run() -> T:
        return function(*args, **kwargs)

    with ThreadPoolExecutor() as executor:
        return await util.ensure_event_loop().run_in_executor(executor, run)
