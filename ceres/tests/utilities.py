from asyncio import sleep
from typing import Awaitable, Callable

from ceres.datetime import utc
from ceres.internal.utilities import awaitify


async def wait_for_condition(
    description: str,
    condition: Callable[[], bool | Awaitable[bool]],
    timeout: float,
) -> None:
    start = utc()
    while True:
        if await awaitify(condition()):
            return
        if (utc() - start).total_seconds() >= timeout:
            raise TimeoutError(description)

        await sleep(0.05)
