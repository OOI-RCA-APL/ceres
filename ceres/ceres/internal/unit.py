from __future__ import annotations

import asyncio
import itertools
import traceback
from dataclasses import dataclass
from logging import ERROR, INFO, WARNING, Logger
from multiprocessing.managers import BaseManager
from threading import Event as ThreadEvent
from threading import Lock
from typing import Any, Iterable, Protocol, cast, overload
from uuid import UUID

from ..alert import Alert, AlertLevel
from ..config import Config, UnitConfig
from ..events import Event
from ..path import (
    ConnectionPath,
    DriverPath,
    LocalComponentPath,
    LocalConnectionPath,
    LocalDriverPath,
    LocalNotifierPath,
    NotifierPath,
    UnitPath,
)
from ..protocols import GlobalUnitProtocol
from ..result import Fail, Ok
from . import logs
from .component import ComponentHandle
from .connection import ConnectionHandle, ConnectionHandleContext
from .database.entity import AlertEntity
from .database.manager import DatabaseManager
from .driver import DriverHandle, DriverHandleContext
from .notifier import NotifierHandle, NotifierHandleContext
from .tasks import Tasklet, ensure_event_loop
from .utilities import jsonify, run_in_thread, unwrap


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    id: UUID
    path: UnitPath
    config: Config


class UnitProxyProtocol(Protocol):
    def rpc_run(self) -> BaseException | None:
        ...

    def rpc_stop(self) -> BaseException | None:
        ...


class Unit(UnitProxyProtocol, GlobalUnitProtocol, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._database = DatabaseManager(self._context.config.database)

        self._connections: dict[str, ConnectionHandle] = {}
        self._drivers: dict[str, DriverHandle] = {}
        self._notifiers: dict[str, NotifierHandle] = {}

        self._loop = ensure_event_loop()
        self._stopping = ThreadEvent()
        self._stopped = ThreadEvent()

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> UnitPath:
        return self._context.path

    @property
    def config(self) -> UnitConfig:
        return unwrap(self._context.config.get_unit(self.path))

    @property
    def database(self) -> DatabaseManager:
        return self._database

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.path))

    @property
    def components(self) -> Iterable[ConnectionHandle | DriverHandle | NotifierHandle]:
        return itertools.chain(self.connections, self.drivers, self.notifiers)

    @property
    def connections(self) -> Iterable[ConnectionHandle]:
        return self._connections.values()

    @property
    def drivers(self) -> Iterable[DriverHandle]:
        return self._drivers.values()

    @property
    def notifiers(self) -> Iterable[NotifierHandle]:
        return self._notifiers.values()

    @overload
    def get_component(self, path: LocalConnectionPath) -> ConnectionHandle | None:
        ...

    @overload
    def get_component(self, path: LocalDriverPath) -> DriverHandle | None:
        ...

    @overload
    def get_component(self, path: LocalNotifierPath) -> NotifierHandle | None:
        ...

    def get_component(self, path: LocalComponentPath) -> object:
        match path:
            case LocalConnectionPath():
                return self.get_connection(path.name)
            case LocalDriverPath():
                return self.get_driver(path.name)
            case LocalNotifierPath():
                return self.get_notifier(path.name)

    async def broadcast(self, event: Event) -> None:
        for component in self.components:
            if component.instance:
                try:
                    await component.instance.handle(event)
                except Exception:
                    self.logger.error(
                        f"{component.path} raised exception while handling event {event}: {traceback.format_exc()}"
                    )

    async def alert(self, alert: Alert) -> None:
        match alert.level:
            case AlertLevel.INFO:
                log_level = INFO
            case AlertLevel.WARNING:
                log_level = WARNING
            case AlertLevel.ERROR:
                log_level = ERROR
            case _:
                raise ValueError(alert.level)

        origin = next(
            (component for component in self.components if component.id == alert.origin_id), None
        )

        logger = origin.logger if origin else self.logger
        logger.log(
            log_level,
            f"ALERT({alert.kind}{' ' + jsonify(alert.info) if alert.info else ''})",
        )

        async with self._database.session() as session:
            entity = AlertEntity(
                id=alert.id,
                origin_id=alert.origin_id,
                timestamp=alert.timestamp,
                level=alert.level,
                kind=alert.kind,
                info=alert.info,
            )

            session.add(entity)
            await session.commit()

    def rpc_run(self) -> BaseException | None:
        try:
            self._loop.run_until_complete(self.run())
        except BaseException as exception:
            return exception

        return None

    def rpc_stop(self) -> BaseException | None:
        self._stopping.set()
        self._stopped.wait()
        return None

    async def _tasklet_run(self) -> None:
        self._stopping.clear()
        self._stopped.clear()

        await self._load_connections()
        await self._load_drivers()
        await self._load_notifiers()

        for component in self.components:
            component.start(
                on_exception=self._on_component_exception,
                on_completed=self._on_component_completed,
            )

        while not self._stopping.is_set():
            await asyncio.sleep(0.1)

        for component in self.components:
            await component.stop()

    async def _tasklet_stop(self) -> None:
        try:
            for connection in self._connections.values():
                await connection.disconnect()

            await self._database.dispose()
        finally:
            self._stopped.set()

    async def _load_connections(self) -> None:
        for config in self.config.connections:
            path = ConnectionPath(self.path.name, config.name)

            if config.name in self._connections:
                continue

            id = await self._database.entities.get_id(path)

            self._connections[config.name] = ConnectionHandle(
                ConnectionHandleContext(
                    id=id,
                    path=path,
                    unit=self,
                    config=self._context.config,
                    database=self._database,
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
        for config in self.config.drivers:
            path = DriverPath(self.path.name, config.name)

            if config.name in self._drivers:
                continue

            id = await self._database.entities.get_id(path)

            self._drivers[config.name] = DriverHandle(
                DriverHandleContext(
                    id=id,
                    path=path,
                    unit=self,
                    config=self._context.config,
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
        for config in self.config.notifiers:
            path = NotifierPath(
                self._context.path.name,
                config.name,
            )

            if config.name in self._notifiers:
                continue

            id = await self._database.entities.get_id(path)

            self._notifiers[config.name] = NotifierHandle(
                NotifierHandleContext(
                    id=id,
                    path=path,
                    unit=self,
                    config=self._context.config,
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

    def _on_component_exception(self, component: ComponentHandle, exception: BaseException) -> None:
        self.logger.error(f"An exception occurred in component '{component.path}'. {exception}")

    def _on_component_completed(self, component: ComponentHandle) -> None:
        self.logger.info(f"Component '{component.path}' completed execution.")


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
        return next(unit for unit in self._context.config.units if unit.name == self.path.name)

    @property
    def instance(self) -> UnitProxyProtocol | None:
        return self._instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.path))

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
                self.logger.error(f"An exception occurred in unit '{self.path}': {exception}")

        await run_in_thread(execute, cancellable=True)

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

        await run_in_thread(execute)
