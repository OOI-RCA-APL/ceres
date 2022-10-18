from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

import anyio

from .component import Component, ComponentContext
from .path import DriverPath, LocalDriverPath
from .protocols import ReferencedDriverHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    path: DriverPath


class Driver(Component[DriverContext], ABC):
    async def update(self) -> None:
        await anyio.sleep(1)


class DriverReference(Reference[ReferencedDriverHandle]):
    @property
    def path(self) -> LocalDriverPath:
        return LocalDriverPath(self.name)
