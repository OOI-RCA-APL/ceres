from __future__ import annotations

from abc import ABC
from typing import Any

import anyio

from .component import Component, ComponentContext, ContextT
from .path import DriverPath
from .protocols import ReferencedDriverHandleProtocol
from .reference import Reference, SelfT


class DriverContext(ComponentContext):
    path: DriverPath


class Driver(Component[DriverContext], ABC):
    async def update(self) -> None:
        await anyio.sleep(1)


class DriverReference(Reference[ReferencedDriverHandleProtocol]):
    def __get__(  # type: ignore
        self: SelfT,
        component: Component[ContextT] | None,
        owner: Any,
    ) -> SelfT | ReferencedDriverHandleProtocol:
        if component is None:
            return self

        if not (real_name := component.context.references.drivers.get(self.name)):
            raise ValueError(f"driver '{self.name}' is not defined in driver references")

        if driver := component.context.unit.get_driver(real_name):
            return driver

        raise ValueError(f"no driver '{real_name}' in current unit")
