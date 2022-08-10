from logging import Logger
from multiprocessing.managers import BaseManager
from typing import Any, Dict, Optional, Sequence, cast

import anyio

from . import logs
from .app import App
from .config import Config
from .connection import ConnectionDescriptor
from .tasks import Tasklet
from .unit import Unit, UnitDescriptor, UnitProxy


class UnitManager(BaseManager):
    pass


UnitManager.register("Unit", Unit)


class UnitHandle:
    def __init__(self, descriptor: UnitDescriptor) -> None:
        self._descriptor = descriptor
        self._manager: Optional[UnitManager] = None
        self._instance: Optional[UnitProxy] = None

    @property
    def setup(self) -> UnitDescriptor:
        return self._descriptor

    @property
    def instance(self) -> Optional[UnitProxy]:
        return self._instance

    def start(self) -> None:
        self._manager = UnitManager()
        self._manager.start()
        instance = cast(UnitProxy, cast(Any, self._manager).Unit(self._descriptor))
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
    def __init__(self, config: Optional[Config], app: Optional[App]) -> None:
        super().__init__()
        self._config = config or Config()
        self._app = app
        self._units: Dict[str, UnitHandle] = {}

    @property
    def logger(self) -> Logger:
        return logs.get("supervisor")

    async def execute(self) -> None:
        self.logger.info("Supervisor starting...")

        for descriptor in self._get_unit_descriptors():
            self._units[descriptor.name] = UnitHandle(
                UnitDescriptor(
                    name=descriptor.name,
                    database=self._config.database,
                    connections=descriptor.connections,
                )
            )

        async def process_unit(unit: UnitHandle) -> None:
            await anyio.to_thread.run_sync(unit.start, cancellable=True)

        try:
            async with anyio.create_task_group() as group:
                for unit in self._units.values():
                    self.logger.info(f"Starting unit '{unit.setup.name}'...")
                    group.start_soon(process_unit, unit)

        except:
            await self.stop()

    async def stop(self) -> None:
        if not self._units:
            return

        self.logger.info("Stopping all units...")

        for unit in self._units.values():
            if unit.instance:
                self.logger.info(f"Stopping unit '{unit.setup.name}'...")
                unit.stop()

        self._units = {}
        self.logger.info("All units were stopped successfully.")

        await super().stop()

    def _get_unit_descriptors(self) -> Sequence[UnitDescriptor]:
        return [
            UnitDescriptor(
                name=name,
                database=self._config.database,
                connections=[
                    ConnectionDescriptor(
                        name=name,
                        module=connection.module,
                        reconnect=connection.reconnect,
                    )
                    for name, connection in unit.connections.items()
                ],
            )
            for name, unit in self._config.units.items()
        ]
