import traceback
from logging import Logger
from typing import Dict, Optional, Protocol

import anyio
from anyio.abc import TaskGroup

from . import logs
from .config import DatabaseConfig, UnitConfig
from .connection import ConnectionHandle
from .data import DataObject
from .database import Database
from .exceptions import ComponentLoadException
from .tasks import Tasklet, ensure_event_loop


class UnitSetup(DataObject):
    unit: UnitConfig
    database: DatabaseConfig


class UnitProxy(Protocol):
    def rpc_start(self) -> None:
        ...

    def rpc_stop(self) -> None:
        ...


class Unit(UnitProxy, Tasklet):
    def __init__(self, setup: UnitSetup) -> None:
        self._setup = setup
        self._database = Database(self._setup.database)
        self._connections: Dict[str, ConnectionHandle] = {}
        self._tasks: Optional[TaskGroup] = None

    @property
    def setup(self) -> UnitSetup:
        return self._setup

    @property
    def logger(self) -> Logger:
        return logs.get(f"@{self._setup.unit.name}")

    def rpc_start(self) -> None:
        async def run() -> None:
            try:
                await self.run()
            except Exception:
                self.logger.error(traceback.format_exc())

        ensure_event_loop().run_until_complete(run())

    def rpc_stop(self) -> None:
        async def stop() -> None:
            try:
                await self.stop()
            except Exception:
                self.logger.error(traceback.format_exc())

        ensure_event_loop().run_until_complete(stop())

    async def teardown(self) -> None:
        for connection in self._connections.values():
            await connection.disconnect()

        await self._database.dispose()

    async def execute(self) -> None:
        await self.teardown()

        self._connections.clear()

        for connection_config in self._setup.unit.connections:
            self._connections[connection_config.name] = ConnectionHandle(
                config=connection_config,
                database=self._database,
            )

        for connection in self._connections.values():
            try:
                await connection.load()
                self.logger.info(f"Loaded connection '{connection.config.name}'.")
            except ComponentLoadException as exception:
                self.logger.error(
                    f"Failed to load connection '{connection.config.name}'. {exception.message}"
                )

        async with anyio.create_task_group() as group:
            for connection in self._connections.values():
                group.start_soon(connection.run)

            self._tasks = group
