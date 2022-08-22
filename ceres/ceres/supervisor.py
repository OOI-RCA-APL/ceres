import traceback
from logging import Logger
from multiprocessing.managers import BaseManager
from typing import Any, Dict, Optional, cast
from uuid import UUID

import anyio

from . import logs
from .config import AppConfig
from .database import Database
from .path import UnitPath
from .tasks import Tasklet
from .unit import Unit, UnitContext, UnitProxy


class UnitManager(BaseManager):
    pass


UnitManager.register("Unit", Unit)


class UnitHandle:
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._manager: Optional[UnitManager] = None
        self._instance: Optional[UnitProxy] = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> UnitPath:
        return self._context.path

    @property
    def instance(self) -> Optional[UnitProxy]:
        return self._instance

    def start(self) -> None:
        self._manager = UnitManager()
        self._manager.start()
        instance = cast(UnitProxy, cast(Any, self._manager).Unit(self._context))
        self._instance = instance
        instance.rpc_start()

    def stop(self) -> None:
        if self._instance:
            self._instance.rpc_stop()
            self._instance = None
        if self._manager:
            self._manager.shutdown()
            self._manager = None


class Supervisor(Tasklet):
    def __init__(self, config: AppConfig, database: Database) -> None:
        super().__init__()
        self._config = config
        self._database = database
        self._units: Dict[UnitPath, UnitHandle] = {}

    @property
    def logger(self) -> Logger:
        return logs.get("supervisor")

    async def execute(self) -> None:
        self.logger.info("Supervisor starting...")

        await self._create_units()

        async def process_unit(unit: UnitHandle) -> None:
            await anyio.to_thread.run_sync(unit.start, cancellable=True)

        try:
            async with anyio.create_task_group() as group:
                for unit in self._units.values():
                    self.logger.info(f"Starting unit '{unit.path}'...")
                    group.start_soon(process_unit, unit)
        except Exception:
            print(traceback.format_exc())
            await self.stop()

    async def stop(self) -> None:
        if not self._units:
            return

        self.logger.info("Stopping all units...")

        for unit in self._units.values():
            if unit.instance:
                self.logger.info(f"Stopping unit '{unit.path}'...")
                unit.stop()

        self._units = {}
        self.logger.info("All units were stopped successfully.")

        await super().stop()

    async def _create_units(self) -> None:
        self._units.clear()

        for unit in self._config.units:
            path = UnitPath.create(unit.name)
            id = await self._database.entities.get_unit_id(path)

            context = UnitContext(
                id=id,
                path=path,
                connections=unit.connections,
                database=self._config.database,
            )

            self._units[path] = UnitHandle(context)
