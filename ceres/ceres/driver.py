import asyncio
from abc import ABC

from pydantic.dataclasses import dataclass

from .component import Component, ComponentContext, ComponentParameters
from .path import DriverPath, LocalDriverPath
from .protocols import ReferencedDriverHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class DriverParameters(ComponentParameters):
    pass


@dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    path: DriverPath


class Driver(Component[DriverParameters, DriverContext], ABC):
    def __init__(
        self,
        parameters: DriverParameters,
        context: DriverContext,
    ) -> None:
        super().__init__(parameters, context)

    async def update(self) -> None:
        await asyncio.sleep(1)


class DriverReference(Reference[ReferencedDriverHandle]):
    @property
    def path(self) -> LocalDriverPath:
        return LocalDriverPath(self.name)
