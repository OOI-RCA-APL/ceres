from asyncio import sleep
from typing import Awaitable, Callable

from ceres._internal import util
from ceres.timing import utc


async def wait_for_condition(
    description: str,
    condition: Callable[[], bool | Awaitable[bool]],
    timeout: float,
) -> None:
    start = utc()
    while True:
        if await util.awaitify(condition()):
            return
        if (utc() - start).total_seconds() >= timeout:
            raise TimeoutError(description)

        await sleep(0.05)
