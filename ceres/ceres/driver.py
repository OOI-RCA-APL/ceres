from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any

import anyio

from .component import Component, ComponentContext, ContextT
from .path import DriverPath, LocalDriverPath
from .protocols import ReferencedDriverHandleProtocol
from .reference import Reference, SelfT


@dataclass(kw_only=True, frozen=True)
class DriverContext(ComponentContext):
    path: DriverPath


class Driver(Component[DriverContext], ABC):
    async def update(self) -> None:
        await anyio.sleep(1)


class DriverReference(Reference[ReferencedDriverHandleProtocol]):
    @property
    def path(self) -> LocalDriverPath:
        return LocalDriverPath.create(self.name)

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
