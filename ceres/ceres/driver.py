import asyncio
from abc import ABC

from pydantic.dataclasses import dataclass as validated_dataclass

from .component import Component, ComponentContext, ComponentParameters


@validated_dataclass(kw_only=True, frozen=True)
class DriverParameters(ComponentParameters):
    pass


@validated_dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    pass


class Driver(Component[DriverParameters, DriverContext], ABC):
    def __init__(
        self,
        parameters: DriverParameters,
        context: DriverContext,
    ) -> None:
        super().__init__(parameters, context)

    async def update(self) -> None:
        await asyncio.sleep(1)
