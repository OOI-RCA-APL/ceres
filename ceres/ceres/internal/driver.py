from __future__ import annotations

from typing import Any
from uuid import UUID

import anyio
from pydantic import BaseModel

from ..driver import Driver, DriverContext
from ..errors import ComponentError
from ..path import DriverPath
from ..protocols import GlobalUnitProtocol
from ..result import Ok, Result
from .component import load_component
from .database.manager import DatabaseManager
from .tasks import Tasklet


class DriverHandle(Tasklet):
    def __init__(self, context: DriverHandleContext) -> None:
        self._context = context
        self._instance: Driver | None = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> DriverPath:
        return self._context.path

    @property
    def instance(self) -> Driver | None:
        return self._instance

    async def load(self) -> Result[Driver, ComponentError]:
        if not self._instance:
            match load_component(Driver, self._context.component, self._context.parameters):
                case Ok(instance):
                    self._instance = instance
                    self._instance.setup(
                        DriverContext(
                            unit=self._context.unit,
                            id=self._context.id,
                            path=self._context.path,
                        )
                    )
                case fail:
                    return fail

        return Ok(self._instance)

    async def _tasklet_run(self) -> None:
        async def process_update() -> None:
            while True:
                await self._update()

        async with anyio.create_task_group() as group:
            group.start_soon(process_update)

    async def _tasklet_stop(self) -> None:
        pass

    async def _update(self) -> None:
        if not self._instance:
            return

        await self._instance.update()


class DriverHandleContext(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    unit: GlobalUnitProtocol
    id: UUID
    path: DriverPath
    component: str | object
    parameters: dict[str, Any]
    database: DatabaseManager
