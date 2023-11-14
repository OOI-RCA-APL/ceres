from asyncio import sleep

from ceres import Component, routine


class Counter(Component):
    # Components are dataclasses, so attributes are per-instance, and can be passed via the
    # component's constructor, or more commonly, through the component's `arguments` configuration
    # in `ceres.yaml` as shown below.
    initial: int
    delta: int = 1

    # Components can declare one or more "routines," which execute concurrently when a component
    # is started, and are cancelled when the component is stopped.
    @routine
    async def count(self) -> None:
        count = self.initial  # Start counting from `initial`.
        while True:
            self.log.info(count)  # Print the current count.
            await sleep(1)  # Wait one second.
            count += self.delta  # Increment `count` by the configured `delta`.
