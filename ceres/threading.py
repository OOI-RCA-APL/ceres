from collections.abc import Callable

from ceres._internal import util


async def spawn[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    def run() -> T:
        return function(*args, **kwargs)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor() as executor:
        return await util.ensure_event_loop().run_in_executor(executor, run)
