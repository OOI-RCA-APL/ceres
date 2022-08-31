from __future__ import annotations

from abc import ABC
from uuid import UUID

import anyio

from .component import Component, ComponentContext
from .path import DriverPath


class DriverContext(ComponentContext):
    id: UUID
    path: DriverPath


class Driver(Component[DriverContext], ABC):
    async def update(self) -> None:
        await anyio.sleep(1)
