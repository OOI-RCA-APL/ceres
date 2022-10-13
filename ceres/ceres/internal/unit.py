from __future__ import annotations

import itertools
import traceback
from dataclasses import dataclass
from logging import Logger
from multiprocessing.managers import BaseManager
from threading import Lock
from typing import Any, Iterable, Protocol, cast
from uuid import UUID

import anyio
from anyio.abc import TaskGroup

from ..config import (
    ConnectionConfig,
    DatabaseConfig,
    DriverConfig,
    NotifierConfig,
    UnitConfig,
)
from ..events import Event
from ..path import ConnectionPath, DriverPath, NotifierPath, UnitPath
from ..protocols import GlobalUnitProtocol
from ..result import Fail, Ok
from . import logs
from .connection import ConnectionHandle, ConnectionHandleContext
from .database.manager import DatabaseManager
from .driver import DriverHandle, DriverHandleContext
from .notifier import NotifierHandle, NotifierHandleContext
from .tasks import Tasklet, ensure_event_loop
from .utilities import jsonify


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    id: UUID
    path: UnitPath
    connections: list[ConnectionConfig]
    drivers: list[DriverConfig]
    notifiers: list[NotifierConfig]
    database: DatabaseConfig
    config: UnitConfig


class UnitProxyProtocol(Protocol):
    def rpc_run(self) -> BaseException | None:
        ...

    def rpc_stop(self) -> BaseException | None:
        ...


class Unit(UnitProxyProtocol, GlobalUnitProtocol, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._database = DatabaseManager.create(self._context.database)
        self._connections: dict[str, ConnectionHandle] = {}
        self._drivers: dict[str, DriverHandle] = {}
        self._notifiers: dict[str, NotifierHandle] = {}
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

    @property
    def components(self) -> Iterable[ConnectionHandle | DriverHandle]:
        return itertools.chain(self.connections, self.drivers)

    @property
    def connections(self) -> Iterable[ConnectionHandle]:
        return self._connections.values()

    @property
    def drivers(self) -> Iterable[DriverHandle]:
        return self._drivers.values()

    @property
    def notifiers(self) -> Iterable[NotifierHandle]:
        return self._notifiers.values()

    def get_connection(self, name: str) -> ConnectionHandle | None:
        return self._connections.get(name)

    def get_driver(self, name: str) -> DriverHandle | None:
        return self._drivers.get(name)

    def get_notifier(self, name: str) -> NotifierHandle | None:
        return self._notifiers.get(name)

    async def broadcast(self, event: Event) -> None:
        for component in self.components:
            if component.instance:
                try:
                    await component.instance.handle(event)
                except Exception:
                    self.logger.error(
                        f"{component.path} raised exception while handling event {event}: {traceback.format_exc()}"
                    )

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
        await self._load_connections()
        await self._load_drivers()
        await self._load_notifiers()

        async with anyio.create_task_group() as group:
            for connection in self._connections.values():
                group.start_soon(connection.run)
            for driver in self._drivers.values():
                group.start_soon(driver.run)
            for notifier in self._notifiers.values():
                group.start_soon(notifier.run)

            self._tasks = group

    async def _tasklet_stop(self) -> None:
        for connection in self._connections.values():
            await connection.disconnect()

        await self._database.dispose()

    async def _load_connections(self) -> None:
        for config in self._context.connections:
            path = ConnectionPath.create(
                self._context.path.name,
                config.name,
            )

            if config.name in self._connections:
                continue

            id = await self._database.entities.get_connection_id(path)

            self._connections[config.name] = ConnectionHandle(
                ConnectionHandleContext(
                    id=id,
                    path=path,
                    unit=self,
                    component=config.component,
                    parameters=config.parameters,
                    references=config.references,
                    database=self._database,
                    reconnect=config.reconnect,
                )
            )

        for handle in self._connections.values():
            match await handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{handle.path}' as {type(handle.instance)} with id '{handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load connection '{handle.path}'. Error: {jsonify(error, indent=2)}"
                    )

    async def _load_drivers(self) -> None:
        for config in self._context.drivers:
            path = DriverPath.create(
                self._context.path.name,
                config.name,
            )

            if config.name in self._drivers:
                continue

            id = await self._database.entities.get_driver_id(path)

            self._drivers[config.name] = DriverHandle(
                DriverHandleContext(
                    id=id,
                    path=path,
                    unit=self,
                    component=config.component,
                    parameters=config.parameters,
                    references=config.references,
                    database=self._database,
                )
            )

        for handle in self._drivers.values():
            match await handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{handle.path}' as {type(handle.instance)} with id '{handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load '{handle.path}'. Error: {jsonify(error, indent=2)}"
                    )

    async def _load_notifiers(self) -> None:
        for config in self._context.notifiers:
            path = NotifierPath.create(
                self._context.path.name,
                config.name,
            )

            if config.name in self._notifiers:
                continue

            id = await self._database.entities.get_notifier_id(path)

            self._notifiers[config.name] = NotifierHandle(
                NotifierHandleContext(
                    id=id,
                    path=path,
                    unit=self,
                    component=config.component,
                    parameters=config.parameters,
                    references=config.references,
                    database=self._database,
                )
            )

        for handle in self._notifiers.values():
            match await handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{handle.path}' as {type(handle.instance)} with id '{handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load '{handle.path}'. Error: {jsonify(error, indent=2)}"
                    )


class UnitManager(BaseManager):
    pass


UnitManager.register("Unit", Unit)


class UnitHandle(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._manager: UnitManager | None = None
        self._instance: UnitProxyProtocol | None = None
        self._lock = Lock()

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
            with self._lock:
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
            with self._lock:
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
