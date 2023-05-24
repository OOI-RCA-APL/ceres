import asyncio
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Literal, final

from typing_extensions import Final, override

from ceres.address import Address
from ceres.component import Component, Paths
from ceres.config import Config, UnitConfig
from ceres.data import ImmutableDataObject, Name, jsonify
from ceres.database import Database
from ceres.directory import Directory
from ceres.environment import Environment
from ceres.errors import (
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
    ReloadError,
)
from ceres.exceptions import (
    EngineConfigCheckFailedException,
    EngineDatabaseInitException,
)
from ceres.internal.app import App
from ceres.internal.config import load_config
from ceres.internal.server import Server
from ceres.internal.utilities import setattr_internal, strify
from ceres.result import Fail, Ok, Result
from ceres.unit import Unit


class ActionKind(str, Enum):
    START = "start"
    RELOAD = "reload"
    REMOVE = "remove"


class Action(ImmutableDataObject):
    kind: ActionKind
    address: Address


@final
class Engine(Component):
    name: Final[Literal[""]] = ""  # type: ignore
    config: Final[Config]

    def __setup__(self) -> None:
        self.__config_queue: Queue[Config] = Queue()

        if self.config.server:
            self.__server = Server(App(self), self.config.server)
        else:
            self.__server = None

        self.bind(Environment(database=Database(self.config.database)))

        self.__unit_configs: dict[Name, UnitConfig] = {}
        self.__reloading = AsyncEvent()

    @override
    def infer_environment(self) -> Environment | None:
        return None

    def __add_unit(self, unit: Unit, config: UnitConfig | None = None) -> None:
        self.add_child(unit)
        if config is not None:
            self.__unit_configs[unit.name] = config

    def remove_child(self, child: Component) -> None:
        super().remove_child(child)
        self.__unit_configs.pop(child.name, None)

    async def reload(self) -> Result[Config, ReloadError]:
        if self.__reloading.is_set():
            return Fail(ReloadAlreadyActiveError())

        source: Path | Config

        if self.config.path:
            self.log.info(f"Reloading configuration from '{self.config.path}'...")
            source = self.config.path
        else:
            self.log.info("No configuration path is set. Reloading current configuration...")
            source = self.config

        match await load_config(source, logger=self.log):
            case Ok(config):
                self.log.info("Queueing reload...")
                self.__reloading.set()
                self.__config_queue.put(config)
                return Ok(config)
            case Fail(errors):
                self.log.error("Reload failed, found errors in configuration.")
                return Fail(ReloadConfigInvalidError(errors=errors))

    @override
    async def __run__(self) -> None:
        match await load_config(self.config, logger=self.log):
            case Ok():
                pass
            case Fail() as fail:
                raise EngineConfigCheckFailedException(
                    f"initial configuration check failed: {jsonify(fail, indent=2)}"
                )

        if not await self.environment.database.tables():
            self.log.info("Database appears empty, initializing database...")
            try:
                await self.environment.database.init()
                self.log.info("Database initialized successfully.")
            except Exception as exception:
                self.log.error("Database initialization failed.")
                raise EngineDatabaseInitException(str(exception))

        started = False

        while True:
            if started:
                await self.__reloading.wait()
                await self.__execute_reload()

            await self.__sync_units()
            await self.__start_server()

            started = True
            self.__reloading.clear()

            tasks = [
                asyncio.create_task(super().__run__(), name="run"),
                asyncio.create_task(self.__reloading.wait(), name="reload-wait"),
                asyncio.create_task(self.wait_until_stopping(), name="wait-until-stopping"),
            ]

            try:
                await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                if self.stopping:
                    self.log.info("Exit signal received, stopping...")
                    break

    @override
    async def __stop__(self) -> None:
        base = super().__stop__

        async def stop() -> None:
            await self.__stop_server()
            await self.__stop_units()
            await base()

        await asyncio.shield(asyncio.create_task(stop()))

    async def __execute_reload(self) -> None:
        self.log.info("Reloading...")
        config_previous = self.config

        try:
            setattr_internal(Engine, self, "config", self.__config_queue.get_nowait())
        except Empty:
            self.log.warning("No new configuration was found, ignoring reload.")
            return

        if self.config == config_previous:
            self.log.info("Configuration was not modified. Nothing to reload.")
            return

        if self.config.server != config_previous.server:
            self.log.info("Server configuration modified, reloading server...")
            try:
                await self.__reload_server()
            except Exception:
                self.log.error(
                    f"An issue occurred while reloading the server: {traceback.format_exc()}"
                )

        if self.config.database != config_previous.database:
            self.log.info("Database configuration modified, reloading all units and database...")
            try:
                await self.__stop_units()
                await self.environment.database.dispose()
                self.bind(Environment(database=Database(self.config.database)))
            except Exception:
                self.log.error(
                    f"An issue occurred while reloading units and database: "
                    f"{traceback.format_exc()}"
                )

        if self.__get_unit_sync_actions():
            self.log.info("Syncing units...")
            try:
                await self.__sync_units()
            except Exception:
                self.log.error(f"An issue occurred while syncing units: {traceback.format_exc()}")

        self.log.info("Reload completed.")

    async def __start_server(self) -> None:
        if not self.__server or self.__server.running:
            return

        self.log.info("Starting server...")
        self.__server.start(
            on_completed=self.__on_server_completed,
            on_exception=self.__on_server_exception,
        )

    async def __stop_server(self) -> None:
        if not self.__server or not self.__server.running:
            return

        self.log.info("Stopping server...")
        await self.__server.stop()

    async def __reload_server(self) -> None:
        await self.__stop_server()
        await self.__start_server()

    async def __load_components(self, unit: Unit) -> None:
        unit_config = self.config.get_unit(unit.name)
        if unit_config is None:
            return

        references: dict[Name, Component] = {}

        for config in unit_config.components:
            if unit.get_child(config.name) is not None:
                continue

            address = unit.address / config.name
            id = await self.environment.assign_component_id(address)

            try:
                component = config.load(
                    args={
                        "paths": Paths(
                            data=unit.paths.data,
                            local=unit.paths.local.subdir(config.name),
                        )
                    }
                )
                component.assign_references(references)
            except Exception:
                unit.log.error(f"Failed to load component '{address}': {traceback.format_exc()}")
                continue

            references[component.name] = component
            unit.add_child(component)
            unit.log.info(
                f"Loaded '{component.address}' as {strify(type(component))} with ID '{id}'."
            )

    async def __sync_units(self) -> None:
        configs: dict[Name, UnitConfig] = {current.name: current for current in self.config.units}

        actions = self.__get_unit_sync_actions()

        for action in actions:
            unit = self.get_child(action.address)

            if action.kind == ActionKind.REMOVE:
                if unit:
                    self.log.info(f"Removing unit '{action.address}'...")
                    await unit.stop()
                    self.remove_child(unit)
            else:
                if action.kind == ActionKind.START:
                    if unit and unit.running:
                        continue

                    self.log.info(f"Starting unit '{action.address}'...")
                elif action.kind == ActionKind.RELOAD:
                    if not unit:
                        continue

                    self.log.info(f"Reloading unit '{action.address}'...")
                    await unit.stop()

                if config := configs.get(action.address):
                    if self.config.path is None:
                        paths = Paths(
                            local=Directory(),
                            data=Directory(),
                        )
                    else:
                        paths = Paths(
                            local=Directory(
                                self.config.path.parent / self.config.paths.local / config.name
                            ),
                            data=Directory(
                                self.config.path.parent / self.config.paths.data / config.name
                            ),
                        )

                    unit = Unit(name=config.name, paths=paths)

                    self.__add_unit(unit, config)
                    await self.__load_components(unit)
                    unit.start(
                        on_completed=self.__on_unit_completed,
                        on_exception=self.__on_unit_exception,
                    )

        started = [
            action
            for action in actions
            if action.kind == ActionKind.START and action.address in self.children
        ]
        reloaded = [
            action
            for action in actions
            if action.kind == ActionKind.RELOAD and action.address in self.children
        ]
        removed = [
            action
            for action in actions
            if action.kind == ActionKind.REMOVE and action.address not in self.children
        ]

        if started:
            self.log.info(f"{len(started)} unit(s) started.")
        if reloaded:
            self.log.info(f"{len(reloaded)} unit(s) reloaded.")
        if removed:
            self.log.info(f"{len(removed)} unit(s) removed.")

    async def __stop_units(self) -> None:
        if not self.children:
            return

        self.log.info("Stopping all units...")

        async def stop(unit: Component) -> None:
            if unit.running:
                self.log.info(f"Stopping unit '{unit.name}'...")
                await unit.stop()

        await asyncio.gather(*(stop(unit) for unit in self.children))

        self.log.info("All units were stopped successfully.")

    def __get_unit_sync_actions(self) -> list[Action]:
        configs: dict[Name, UnitConfig] = {current.name: current for current in self.config.units}

        actions: list[Action] = []

        for name, config in configs.items():
            unit = self.get_child(name)
            address = self.address / name
            if unit and unit.running and self.__unit_configs.get(name) == config:
                continue

            if not unit or not unit.running:
                actions.append(Action(kind=ActionKind.START, address=address))
            elif self.__unit_configs.get(name) != config:
                actions.append(Action(kind=ActionKind.RELOAD, address=address))

        for unit in self.children:
            if unit.name not in configs:
                actions.append(Action(kind=ActionKind.REMOVE, address=unit.address))

        return actions

    def __on_server_completed(self, server: Server) -> None:
        self.log.info("Server stopped.")

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.log.error(f"An exception occurred in server: {traceback.format_exception(exception)}")

    def __on_unit_completed(self, unit: Unit) -> None:
        self.log.info(f"Unit '{unit.name}' stopped.")

    def __on_unit_exception(self, unit: Unit, exception: BaseException) -> None:
        self.log.error(
            f"An exception occurred in unit '{unit.name}': {traceback.format_exception(exception)}"
        )
