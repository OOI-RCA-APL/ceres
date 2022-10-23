from __future__ import annotations

from dataclasses import dataclass

from ..config import DriverConfig
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
    @property
    def path(self) -> DriverPath:
        return self._context.path

    @property
    def config(self) -> DriverConfig:
        return super().config  # type: ignore

    def _get_component_type(self) -> type[Driver]:  # type: ignore
        return Driver

    def _get_component_context(self) -> DriverContext:
        return DriverContext(
            id=self._context.id,
            path=self._context.path,
            config=self._context.config,
            unit=self._context.unit,
        )

    async def _tasklet_run(self) -> None:
        await super()._tasklet_run()
        while True:
            await self._update()

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

    async def _update(self) -> None:
        if not self._instance:
            return

        await self._instance.update()
