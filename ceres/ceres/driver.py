import asyncio

from pydantic.dataclasses import dataclass as validated_dataclass

from .component import Component, ComponentContext, ComponentParameters


@validated_dataclass(kw_only=True, frozen=True)
class DriverParameters(ComponentParameters):
    pass


@validated_dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    pass


@validated_dataclass
class Driver(Component):
    parameters: DriverParameters
    context: DriverContext

    async def update(self) -> None:
        await asyncio.sleep(1)
