import asyncio

from .component import Component, ComponentContext, ComponentParameters
from .utilities import vdc


@vdc(frozen=True)
class DriverParameters(ComponentParameters):
    pass


@vdc(frozen=True)
class DriverContext(ComponentContext):
    pass


class Driver(Component):
    parameters: DriverParameters
    context: DriverContext

    async def update(self) -> None:
        await asyncio.sleep(1)
