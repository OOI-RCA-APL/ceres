from ceres import CancelledError, Component, action, query, sleep


class Device(Component):
    """A component whose procedures the end-to-end tests call from the console."""

    @query
    async def echo(self, text: str = "abc") -> str:
        """Answer with the text it was given."""
        return text

    @action
    async def hold(self, seconds: float = 30) -> str:
        """Wait for a number of seconds, logging whether it finished or was cancelled."""
        self.system.log.info("hold started")
        try:
            await sleep(seconds)
        except CancelledError:
            self.system.log.info("hold cancelled")
            raise

        self.system.log.info("hold finished")
        return "held"
