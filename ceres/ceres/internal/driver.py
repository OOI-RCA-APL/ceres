from __future__ import annotations

from dataclasses import dataclass

from ..driver import Driver, DriverContext
from ..path import DriverPath
from ..protocols import ReferencedDriverHandle
from .component import ComponentHandle, ComponentHandleContext
from .tasks import Tasklet


@dataclass(kw_only=True, frozen=True)
class DriverHandleContext(ComponentHandleContext):
    path: DriverPath


class DriverHandle(
    ComponentHandle[
        DriverHandleContext,
        Driver,
        DriverContext,
    ],
    Tasklet,
    ReferencedDriverHandle,
):
    @property
    def path(self) -> DriverPath:
        return self._context.path

    def _get_component_type(self) -> type[Driver]:  # type: ignore
        return Driver

    def _get_component_context(self) -> DriverContext:
        return DriverContext(
            id=self._context.id,
            path=self._context.path,
            unit=self._context.unit,
            references=self._context.references,
        )

    async def _tasklet_run(self) -> None:
        while True:
            await self._update()

    async def _tasklet_stop(self) -> None:
        pass

    async def _update(self) -> None:
        if not self._instance:
            return

        await self._instance.update()
