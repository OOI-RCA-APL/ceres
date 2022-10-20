from __future__ import annotations

import asyncio
from abc import ABC
from dataclasses import dataclass

from .component import Component, ComponentContext
from .path import DriverPath, LocalDriverPath
from .protocols import ReferencedDriverHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    path: DriverPath


class Driver(Component[DriverContext], ABC):
    async def update(self) -> None:
        await asyncio.sleep(1)


class DriverReference(Reference[ReferencedDriverHandle]):
    @property
    def path(self) -> LocalDriverPath:
        return LocalDriverPath(self.name)
