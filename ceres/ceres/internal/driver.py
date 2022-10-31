from __future__ import annotations

import asyncio

from ..driver import Driver
from ..protocols import ReferencedDriverHandle
from .component import ComponentHandle


class DriverHandle(ComponentHandle[Driver], ReferencedDriverHandle):
    @classmethod
    def _get_component_type(cls) -> type[Driver]:
        return Driver

    async def _tasklet_run(self) -> None:
        await asyncio.gather(
            super()._tasklet_run(),
            self._process_update(),
        )

    async def _process_update(self) -> None:
        while True:
            if not self.instance:
                await asyncio.sleep(1)
                continue

            await self.instance.update()
