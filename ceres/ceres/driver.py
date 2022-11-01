import asyncio

from pydantic.dataclasses import dataclass as validated_dataclass

from .component import (
    Component,
    ComponentContext,
    ComponentParameters,
    ComponentReferences,
)


@validated_dataclass(kw_only=True, frozen=True)
class DriverParameters(ComponentParameters):
    pass


@validated_dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    pass


class Driver(Component[DriverParameters, DriverContext, ComponentReferences]):
    def __init__(
        self,
        parameters: DriverParameters,
        context: DriverContext,
        references: ComponentReferences,
    ) -> None:
        super().__init__(parameters, context, references)

    async def update(self) -> None:
        await asyncio.sleep(1)
