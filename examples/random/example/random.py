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
    async def do__print_random(self) -> None:
        while True:
            self.log.info(randint(self.low, self.high))  # Print the current count.
            await sleep(self.interval.total_seconds())  # Wait the configured interval.


if __name__ == "__main__":

    async def main() -> None:
        component = Random(low=1, high=100)
        await component.run()

    asyncio.run(main())  # Logs a random number between 1 and 100 every second until cancelled.
