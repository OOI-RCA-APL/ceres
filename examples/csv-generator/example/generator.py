import csv
from asyncio import sleep
from pathlib import Path
from random import choice

from ceres import Component, routine


class CSVNameGenerator(Component):
    output: Path

    @routine
    async def routine__startup(self) -> None:
        """
        This routine will run once on startup.
        """
        self.log.info("Starting up...")

    @routine(restart="always", restart_delay=5)
    async def routine__write(self) -> None:
        """
        This routine will run on startup and execute forever, restarting if it crashes for any
        reason.
        """
        while True:
            self.output.parent.mkdir(parents=True, exist_ok=True)

            exists = self.output.exists()
            with self.output.open("a+") as stream:
                writer = csv.writer(stream)
                if not exists:
                    writer.writerow(["first", "last"])

                first, last = (
                    self.__get_random_first_name(),
                    self.__get_random_last_name(),
                )

                row = [first, last]
                writer.writerow(row)
                self.log.info(row)

            await sleep(1)

    @routine
    async def routine__log_file_size(self) -> None:
        """
        This routine will also run on startup and execute forever, but will not restart on exit or
        error.
        """
        while True:
            if self.output.exists():
                size = self.output.stat().st_size
                self.log.info(f"'{self.output}' is now {size} bytes.")
            else:
                self.log.info(f"'{self.output}' has not been created yet.")

            await sleep(5)

    def __get_random_first_name(self) -> str:
        return choice(["Alice", "Bob", "Charlie", "Diane"])

    def __get_random_last_name(self) -> str:
        return choice(["Montgomery", "Gonzalez", "Dunsworth", "Paris"])
