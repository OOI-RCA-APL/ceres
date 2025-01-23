import asyncio
from asyncio import sleep
from datetime import timedelta
from random import randint

from ceres import Component, routine
from ceres.data import TimeDelta


class Random(Component):
    low: int
    high: int
    interval: TimeDelta = timedelta(seconds=1)

    @routine
    async def routine__print_random(self) -> None:
        while True:
            # Print a random integer within the configured range.
            self.system.log.info(randint(self.low, self.high))
            # Wait the configured interval.
            await sleep(self.interval.total_seconds())


# This section is only included for example.
if __name__ == "__main__":

    async def main() -> None:
        component = Random(low=1, high=100)
        await component.system.run()

    # Log a random number between 1 and 100 every second until cancelled.
    asyncio.run(main())
