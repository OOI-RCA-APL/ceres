import traceback
from logging import Logger
from typing import Dict, List, Optional, Protocol
from uuid import UUID

import anyio
from anyio.abc import TaskGroup

from . import logs
from .config import ConnectionConfig, DatabaseConfig
from .connection import ConnectionContext, ConnectionHandle
from .data import DataObject
from .database import Database
from .exceptions import ComponentLoadException
from .path import ConnectionPath, UnitPath
from .tasks import Tasklet, ensure_event_loop


class UnitContext(DataObject):
    id: UUID
    path: UnitPath
    connections: List[ConnectionConfig]
    database: DatabaseConfig


class UnitProxy(Protocol):
    def rpc_get_context(self) -> UnitContext:
        ...

    def rpc_start(self) -> None:
        ...

    def rpc_stop(self) -> None:
        ...


class Unit(UnitProxy, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._database = Database(self._context.database)
        self._connections: Dict[str, ConnectionHandle] = {}
        self._tasks: Optional[TaskGroup] = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> UnitPath:
        return self._context.path

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.path))

    def rpc_get_context(self) -> UnitContext:
        return self._context

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

        for connection_config in self._context.connections:
            path = ConnectionPath.create(
                self._context.path.unit,
                connection_config.name,
            )

            id = await self._database.entities.get_connection_id(path)

            self._connections[connection_config.name] = ConnectionHandle(
                ConnectionContext(
                    id=id,
                    path=path,
                    component=connection_config.component,
                    database=self._database,
                    reconnect=connection_config.reconnect,
                )
            )

        for connection in self._connections.values():
            try:
                await connection.load()
                self.logger.info(f"Loaded connection '{connection.path}'.")
            except ComponentLoadException as exception:
                self.logger.error(
                    f"Failed to load connection '{connection.path}'. {exception.message}"
                )

        async with anyio.create_task_group() as group:
            for connection in self._connections.values():
                group.start_soon(connection.run)

            self._tasks = group
