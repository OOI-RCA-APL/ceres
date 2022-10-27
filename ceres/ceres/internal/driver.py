from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..driver import Driver, DriverContext
from ..path import DriverPath
from ..protocols import ReferencedDriverHandle
from .component import ComponentHandle, ComponentHandleContext


@dataclass(kw_only=True, frozen=True)
class DriverHandleContext(ComponentHandleContext):
    path: DriverPath


class DriverHandle(
    ComponentHandle[
        DriverHandleContext,
        Driver,
        DriverContext,
    ],
    ReferencedDriverHandle,
):
    @classmethod
    def _get_component_type(cls) -> type[Driver]:
        return Driver

    @property
    def path(self) -> DriverPath:
        return self._context.path

    async def _tasklet_run(self) -> None:
        await asyncio.gather(
            super()._tasklet_run(),
            self._process_update(),
        )

    async def _process_update(self) -> None:
        while True:
            if not self._instance:
                await asyncio.sleep(1)
                continue

            await self._instance.update()
