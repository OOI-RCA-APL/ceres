import asyncio
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from enum import Enum
from logging import Logger
from pathlib import Path
from queue import Empty, Queue
from typing import AsyncIterable, Sequence, final

from typing_extensions import override

from .address import Address
from .component import Component
from .config import Config, UnitConfig
from .data import ImmutableDataObject, Name, jsonify
from .database import Database
from .directory import Directory
from .environment import Environment
from .errors import (
    ProcedureUnitDoesNotExistError,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
    ReloadError,
)
from .events import Event
from .exceptions import (
    EngineConfigCheckFailedException,
    EngineDatabaseInitException,
    ProcedureException,
)
from .internal import logs
from .internal.app import App
from .internal.config import load_config
from .internal.server import Server
from .internal.tasklet import Tasklet
from .result import Fail, Ok, Result
from .stream import Stream
from .unit import Unit, UnitPaths


class _UnitSyncActionKind(str, Enum):
    START = "start"
    RELOAD = "reload"
    REMOVE = "remove"


class _UnitSyncAction(ImmutableDataObject):
    kind: _UnitSyncActionKind
    unit: Name


@final
class Engine(Tasklet):
    def __init__(self, config: Config) -> None:
        self.__config = config
        self.__config_queue: Queue[Config] = Queue()

        if self.__config.server:
            self.__server = Server(App(self), self.__config.server)
        else:
            self.__server = None

        self.__environment = Environment(
            database=Database(self.__config.database),
        )

        self.__units: dict[Name, Unit] = {}
        self.__events: Stream[Event] = Stream()
        self.__reloading = AsyncEvent()

    @property
    def logger(self) -> Logger:
        return logs.get("engine")

    @property
    def config(self) -> Config:
        return self.__config

    @property
    def environment(self) -> Environment:
        return self.__environment

    @property
    def events(self) -> AsyncIterable[Event]:
        return self.__events.view()

    @property
    def units(self) -> Sequence[Unit]:
        return list(self.__units.values())

    def emit_event(self, event: Event) -> None:
        self.__events.put(event)

    def get_unit(self, name: Name) -> Unit | None:
        return self.__units.get(name)

    def get_component(self, address: Address) -> Component | None:
        unit = self.__units.get(address.unit)
        if unit is None:
            return None

        return unit.get_component(address.component)

    def __attach_unit(self, unit: Unit) -> None:
        self.__units[unit.name] = unit
        unit.attach_to_engine(self)

    def __detach_unit(self, unit: Unit) -> None:
        self.__units.pop(unit.name, None)
        if unit.engine is self:
            unit.detach_from_engine()

    async def reload(self) -> Result[Config, ReloadError]:
        if self.__reloading.is_set():
            return Fail(ReloadAlreadyActiveError())

        source: Path | Config

        if self.__config.path:
            self.logger.info(f"Reloading configuration from '{self.__config.path}'...")
            source = self.__config.path
        else:
            self.logger.info("No configuration path is set. Reloading current configuration...")
            source = self.__config

        match await load_config(source, logger=self.logger):
            case Ok(config):
                self.logger.info("Queueing reload...")
                self.__reloading.set()
                self.__config_queue.put(config)
                return Ok(config)
            case Fail(errors):
                self.logger.error("Reload failed, found errors in configuration.")
                return Fail(ReloadConfigInvalidError(errors=errors))

    @override
    async def __run__(self) -> None:
        match await load_config(self.__config, logger=self.logger):
            case Ok():
                pass
            case Fail() as fail:
                raise EngineConfigCheckFailedException(
                    f"initial configuration check failed: {jsonify(fail, indent=2)}"
                )

        if not await self.__environment.database.tables():
            self.logger.info("Database appears empty, initializing database...")
            try:
                await self.__environment.database.init()
                self.logger.info("Database initialized successfully.")
            except Exception as exception:
                self.logger.error("Database initialization failed.")
                raise EngineDatabaseInitException(str(exception))

        started = False

        while True:
            if started:
                await self.__reloading.wait()
                await self.__reload()

            await self.__sync_units()
            await self.__start_server()

            started = True
            self.__reloading.clear()

            tasks = [
                asyncio.create_task(self.__reloading.wait(), name="reload-wait"),
                asyncio.create_task(self.wait_until_stopping(), name="wait-until-stopping"),
            ]

            try:
                await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                if self.stopping:
                    self.logger.info("Exit signal received, stopping...")
                    break

    @override
    async def __stop__(self) -> None:
        async def stop() -> None:
            await self.__stop_server()
            await self.__stop_units()
            await self.__environment.database.dispose()

        await asyncio.shield(asyncio.create_task(stop()))

    async def call(
        self,
        component: Address,
        procedure: str,
        input: object | None = None,
    ) -> object | None:
        if (unit := self.get_unit(component.unit)) is None:
            raise ProcedureException(ProcedureUnitDoesNotExistError())

        return await unit.call(component.name, procedure, input)

    def subscribe(
        self,
        component: Address,
        procedure: str,
        input: object | None = None,
    ) -> AsyncIterable[object]:
        if (unit := self.__units.get(component.unit)) is None:
            raise ProcedureException(ProcedureUnitDoesNotExistError())

        return unit.subscribe(component.name, procedure, input)

    async def __reload(self) -> None:
        self.logger.info("Reloading...")
        config_previous = self.__config

        try:
            self.__config = self.__config_queue.get_nowait()
        except Empty:
            self.logger.warning("No new configuration was found, ignoring reload.")
            return

        if self.__config == config_previous:
            self.logger.info("Configuration was not modified. Nothing to reload.")
            return

        if self.__config.server != config_previous.server:
            self.logger.info("Server configuration modified, reloading server...")
            try:
                await self.__reload_server()
            except Exception:
                self.logger.error(
                    f"An issue occurred while reloading the server: {traceback.format_exc()}"
                )

        if self.__config.database != config_previous.database:
            self.logger.info("Database configuration modified, reloading all units and database...")
            try:
                await self.__stop_units()
                await self.__database.dispose()
                self.__database = Database(self.__config.database)
            except Exception:
                self.logger.error(
                    f"An issue occurred while reloading units and database: {traceback.format_exc()}"
                )

        if self.__get_unit_sync_actions():
            self.logger.info("Syncing units...")
            try:
                await self.__sync_units()
            except Exception:
                self.logger.error(
                    f"An issue occurred while syncing units: {traceback.format_exc()}"
                )

        self.logger.info("Reload completed.")

    async def __start_server(self) -> None:
        if not self.__server or self.__server.running:
            return

        self.logger.info("Starting server...")
        self.__server.start(
            on_completed=self.__on_server_completed,
            on_exception=self.__on_server_exception,
        )

    async def __stop_server(self) -> None:
        if not self.__server or not self.__server.running:
            return

        self.logger.info("Stopping server...")
        await self.__server.stop()

    async def __reload_server(self) -> None:
        await self.__stop_server()
        await self.__start_server()

    async def __sync_units(self) -> None:
        configs: dict[Name, UnitConfig] = {current.name: current for current in self.__config.units}

        actions = self.__get_unit_sync_actions()

        for action in actions:
            unit = self.__units.get(action.unit)

            if action.kind == _UnitSyncActionKind.REMOVE:
                if unit:
                    self.logger.info(f"Removing unit '{action.unit}'...")
                    await unit.stop()
                    self.__detach_unit(unit)
            else:
                if action.kind == _UnitSyncActionKind.START:
                    if unit and unit.running:
                        continue

                    self.logger.info(f"Starting unit '{action.unit}'...")
                elif action.kind == _UnitSyncActionKind.RELOAD:
                    if not unit:
                        continue

                    self.logger.info(f"Reloading unit '{action.unit}'...")
                    await unit.stop()
                    self.__detach_unit(unit)

                if config := configs.get(action.unit):
                    if self.config.path is None:
                        paths = UnitPaths(
                            local=Directory(),
                            data=Directory(),
                        )
                    else:
                        paths = UnitPaths(
                            local=Directory(
                                self.config.path.parent / self.config.paths.local / config.name
                            ),
                            data=Directory(
                                self.config.path.parent / self.config.paths.data / config.name
                            ),
                        )

                    unit = Unit(
                        config=config,
                        environment=self.__environment,
                        paths=paths,
                    )

                    self.__attach_unit(unit)
                    unit.start(
                        on_completed=self.__on_unit_completed,
                        on_exception=self.__on_unit_exception,
                    )

        started = [
            action
            for action in actions
            if action.kind == _UnitSyncActionKind.START and action.unit in self.__units
        ]
        reloaded = [
            action
            for action in actions
            if action.kind == _UnitSyncActionKind.RELOAD and action.unit in self.__units
        ]
        removed = [
            action
            for action in actions
            if action.kind == _UnitSyncActionKind.REMOVE and action.unit not in self.__units
        ]

        if started:
            self.logger.info(f"{len(started)} unit(s) started.")
        if reloaded:
            self.logger.info(f"{len(reloaded)} unit(s) reloaded.")
        if removed:
            self.logger.info(f"{len(removed)} unit(s) removed.")

    async def __stop_units(self) -> None:
        if not self.__units:
            return

        self.logger.info("Stopping all units...")

        async def stop(unit: Unit) -> None:
            if unit.running:
                self.logger.info(f"Stopping unit '{unit.name}'...")
                await unit.stop()

            self.__detach_unit(unit)

        await asyncio.gather(*(stop(unit) for unit in self.units))

        self.logger.info("All units were stopped successfully.")

    def __get_unit_sync_actions(self) -> list[_UnitSyncAction]:
        configs: dict[Name, UnitConfig] = {current.name: current for current in self.__config.units}

        actions: list[_UnitSyncAction] = []

        for name, config in configs.items():
            unit = self.get_unit(name)
            if unit and unit.running and unit.config == config:
                continue

            if not unit or not unit.running:
                actions.append(_UnitSyncAction(kind=_UnitSyncActionKind.START, unit=name))
            elif unit.config != config:
                actions.append(_UnitSyncAction(kind=_UnitSyncActionKind.RELOAD, unit=name))

        for name, unit in self.__units.items():
            if name not in configs:
                actions.append(_UnitSyncAction(kind=_UnitSyncActionKind.REMOVE, unit=name))

        return actions

    def __on_server_completed(self, server: Server) -> None:
        self.logger.info(f"Server stopped.")

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in server: {traceback.format_exception(exception)}"
        )

    def __on_unit_completed(self, unit: Unit) -> None:
        self.logger.info(f"Unit '{unit.name}' stopped.")
        self.__detach_unit(unit)

    def __on_unit_exception(self, unit: Unit, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in unit '{unit.name}': {traceback.format_exception(exception)}"
        )
        self.__detach_unit(unit)
