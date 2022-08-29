from __future__ import annotations

import traceback
from logging import Logger
from multiprocessing.managers import BaseManager
from typing import Any, Protocol, cast
from uuid import UUID

import anyio
from anyio.abc import TaskGroup

from . import logs
from .config import ConnectionConfig, DatabaseConfig, UnitConfig
from .connection import ConnectionContext, ConnectionHandle
from .data import DataObject
from .database import create_database_manager
from .exceptions import ComponentLoadException
from .path import ConnectionPath, UnitPath
from .tasks import Tasklet, ensure_event_loop


class UnitContext(DataObject):
    id: UUID
    path: UnitPath
    connections: list[ConnectionConfig]
    database: DatabaseConfig
    config: UnitConfig


class UnitProxyProtocol(Protocol):
    def rpc_run(self) -> BaseException | None:
        ...

    def rpc_stop(self) -> BaseException | None:
        ...


class Unit(UnitProxyProtocol, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._database = create_database_manager(self._context.database)
        self._connections: dict[str, ConnectionHandle] = {}
        self._tasks: TaskGroup | None = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> UnitPath:
        return self._context.path

    @property
    def config(self) -> UnitConfig:
        return self._context.config

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.path))

    def rpc_run(self) -> BaseException | None:
        async def execute() -> None:
            try:
                await self.run()
            except Exception:
                self.logger.error(traceback.format_exc())
                raise

        try:
            ensure_event_loop().run_until_complete(execute())
        except BaseException as exception:
            return exception

        return None

    def rpc_stop(self) -> BaseException | None:
        async def execute() -> None:
            try:
                await self.stop()
            except Exception:
                self.logger.error(traceback.format_exc())
                raise

        try:
            ensure_event_loop().run_until_complete(execute())
        except BaseException as exception:
            return exception

        return None

    async def _tasklet_run(self) -> None:
        await self._tasklet_stop()

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
                    parameters=connection_config.parameters,
                    database=self._database,
                    reconnect=connection_config.reconnect,
                )
            )

        for connection in self._connections.values():
            try:
                connection.load()
                self.logger.info(f"Loaded connection '{connection.path}'.")
            except ComponentLoadException as exception:
                self.logger.error(
                    f"Failed to load connection '{connection.path}'. {exception.message}"
                )

        async with anyio.create_task_group() as group:
            for connection in self._connections.values():
                group.start_soon(connection.run)

            self._tasks = group

    async def _tasklet_stop(self) -> None:
        for connection in self._connections.values():
            await connection._disconnect()

        await self._database.dispose()


class UnitManager(BaseManager):
    pass


UnitManager.register("Unit", Unit)


class UnitHandle(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._manager: UnitManager | None = None
        self._instance: UnitProxyProtocol | None = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> UnitPath:
        return self._context.path

    @property
    def config(self) -> UnitConfig:
        return self._context.config

    @property
    def instance(self) -> UnitProxyProtocol | None:
        return self._instance

    async def _tasklet_run(self) -> None:
        def execute() -> None:
            self._manager = UnitManager()
            self._manager.start()
            instance = cast(UnitProxyProtocol, cast(Any, self._manager).Unit(self._context))
            self._instance = instance

            try:
                exception = instance.rpc_run()
            except EOFError:
                return

            if exception:
                raise exception

        await anyio.to_thread.run_sync(execute, cancellable=True)

    async def _tasklet_stop(self) -> None:
        def execute() -> None:
            if self._instance:
                exception = self._instance.rpc_stop()
                self._instance = None
            else:
                exception = None

            if self._manager:
                self._manager.shutdown()

            if exception:
                raise exception

        await anyio.to_thread.run_sync(execute)
