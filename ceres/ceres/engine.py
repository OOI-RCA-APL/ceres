import asyncio
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Mapping, final

from typing_extensions import override

from ceres.address import Address
from ceres.component import Component
from ceres.config import ComponentConfig, Config
from ceres.data import ImmutableDataObject, Name
from ceres.database import Database
from ceres.directory import Directory
from ceres.errors import (
    ConfigError,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
    ReloadError,
)
from ceres.exceptions import EngineDatabaseInitException
from ceres.internal.server import Server
from ceres.internal.utilities import setattr_internal, strify
from ceres.procedure import action
from ceres.result import Fail, Ok, Result


class ActionKind(str, Enum):
    CREATE = "create"
    RECREATE = "recreate"
    REMOVE = "remove"


class Action(ImmutableDataObject):
    kind: ActionKind
    address: Address


@final
class Engine(Component):
    def __setup__(self) -> None:
        self.__config: Config | None = None
        self.__config_queue: Queue[Config] = Queue()
        self.__reloading = AsyncEvent()
        self.__server: Server | None = None
        self.__saved_project_directory: Directory | None = None

    @property
    def config(self) -> Config:
        if self.__config is None:
            self.__config = Config()

        return self.__config

    @property
    def project_directory(self) -> Directory:
        if self.config.path is None:
            if self.__saved_project_directory is None:
                self.__saved_project_directory = Directory()
        else:
            if (
                self.__saved_project_directory is None
                or self.__saved_project_directory.path != self.config.path.parent
            ):
                self.__saved_project_directory = Directory(self.config.path.parent)

        return self.__saved_project_directory

    @property
    def local_directory(self) -> Directory:
        return self.project_directory.subdir("local")

    @property
    @override
    def database(self) -> Database:
        if self.local_database is None:
            self.local_database = Database(self.config.database)

        return self.local_database

    async def load(
        self,
        source: Path | Mapping[str, Any] | Config,
    ) -> "Result[Config, list[ConfigError]]":
        match await Config.load(source, log=self.log):
            case Ok(config) as ok:
                self.__config = config
                await self.load_database()
                await self.load_components()
                return ok
            case Fail() as fail:
                return fail

    @action
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

        match await Config.load(source, log=self.log):
            case Ok(config):
                self.log.info("Queueing reload...")
                self.__reloading.set()
                self.__config_queue.put(config)
                return Ok(config)
            case Fail(errors):
                self.log.error("Reload failed, found errors in configuration.")
                return Fail(ReloadConfigInvalidError(errors=errors))

    async def load_database(self) -> None:
        if not await self.database.tables():
            self.log.info("Database appears empty, initializing database...")
            try:
                await self.database.init()
                self.log.info("Database initialized successfully.")
            except Exception as exception:
                self.log.error("Database initialization failed.")
                raise EngineDatabaseInitException(str(exception))

    @override
    async def __run__(self) -> None:
        await self.load_database()

        started = False

        while True:
            if started:
                await self.__reloading.wait()
                await self.__execute_reload()

            await self.__start_server()

            started = True
            self.__reloading.clear()

            async def start_enabled() -> None:
                await asyncio.sleep(0)
                for component in self.get_components():
                    await component.sync_with_database()
                    if component.enabled:
                        self.log.info(f"Starting enabled component {component.address!r}...")
                        component.start()

            tasks = [
                asyncio.create_task(super().__run__(), name="run"),
                asyncio.create_task(start_enabled(), name="start-enabled"),
                asyncio.create_task(self.__reloading.wait(), name="reload-wait"),
                asyncio.create_task(self.wait_until_stopping(), name="wait-until-stopping"),
            ]

            try:
                await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
            finally:
                for task in tasks:
                    if not task.cancelled():
                        if task.done():
                            try:
                                task.result()
                            except Exception:
                                self.log.error(traceback.format_exc())
                if self.stopping:
                    self.log.info("Exit signal received, stopping...")
                    break

    @override
    async def __stop__(self) -> None:
        await self.__stop_server()
        await super().__stop__()

    async def __execute_reload(self) -> None:
        self.log.info("Reloading...")
        config_previous = self.config

        try:
            setattr_internal(Engine, self, "__config", self.__config_queue.get_nowait())
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
            self.log.info(
                "Database configuration modified, reloading all components and database..."
            )
            try:
                for child in self.components:
                    await child.stop()
                await self.flush()
                if self.local_database is not None:
                    await self.local_database.dispose()
                    self.local_database = Database(self.config.database)
            except Exception:
                self.log.error(
                    f"An issue occurred while reloading components and database: "
                    f"{traceback.format_exc()}"
                )

        if self.get_reload_actions():
            self.log.info("Syncing units...")
            try:
                await self.sync_components()
            except Exception:
                self.log.error(f"An issue occurred while syncing units: {traceback.format_exc()}")

        self.log.info("Reload completed.")

    async def load_components(self) -> None:
        await self.__load_subcomponents_for(self)

    async def __load_subcomponents_for(self, component: Component) -> None:
        if component is self:
            config = self.config
        else:
            config = self.config.get_component(component.address)
            if config is None:
                return

        references: dict[Name, Component] = {}

        for subconfig in config.components:
            child = component.get_component(subconfig.name)
            address = component.address / subconfig.name
            id = await self.assign_component_id(address)

            if child is None:
                try:
                    child = subconfig.create()
                    component.add_component(child)
                    await child.sync_with_database()
                    child.assign_references(references)
                    await self.__load_subcomponents_for(child)
                    component.log.info(
                        f"Loaded '{child.address}' as {strify(type(child))} with ID '{id}'."
                    )
                except Exception:
                    component.log.error(f"Failed to load '{address}': {traceback.format_exc()}")
                    continue

            references[child.name] = child

    async def sync_components(self) -> None:
        actions = self.get_reload_actions()

        for action in actions:
            component = self.get_component(action.address)

            if action.kind == ActionKind.REMOVE:
                if component is not None:
                    self.log.info(f"'{action.address}' will be removed...")
                    await component.stop()
                    component.detach()
            else:
                if action.kind == ActionKind.CREATE:
                    if component is None:
                        self.log.info(f"'{action.address}' will be created...")
                elif action.kind == ActionKind.RECREATE:
                    if component is not None:
                        self.log.info(f"'{action.address}'will be recreated...")
                        await component.stop()
                        component.detach()

        await self.__load_subcomponents_for(self)

        created = [
            action
            for action in actions
            if action.kind == ActionKind.CREATE and action.address in self.components
        ]
        recreated = [
            action
            for action in actions
            if action.kind == ActionKind.RECREATE and action.address in self.components
        ]
        removed = [
            action
            for action in actions
            if action.kind == ActionKind.REMOVE and action.address not in self.components
        ]

        if created:
            self.log.info(f"{len(created)} components(s) created.")
        if recreated:
            self.log.info(f"{len(recreated)} components(s) reloaded.")
        if removed:
            self.log.info(f"{len(removed)} components(s) removed.")

    def get_reload_actions(self) -> list[Action]:
        configs: dict[Name, ComponentConfig] = {
            current.name: current for current in self.config.components
        }

        actions: list[Action] = []

        for name, config in configs.items():
            component = self.get_component(name)
            address = self.address / name
            if component is None:
                actions.append(Action(kind=ActionKind.CREATE, address=address))
            elif component.__config__ != config:
                actions.append(Action(kind=ActionKind.RECREATE, address=address))

        for component in self.components:
            if component.name not in configs:
                actions.append(Action(kind=ActionKind.REMOVE, address=component.address))

        return actions

    async def __start_server(self) -> None:
        if self.__server is not None and self.__server.running:
            return

        self.__server = Server(self, self.config)

        self.log.info("Starting server...")
        self.__server.start(
            on_completed=self.__on_server_completed,
            on_exception=self.__on_server_exception,
        )

    async def __stop_server(self) -> None:
        if self.__server is None or not self.__server.running:
            return

        self.log.info("Stopping server...")
        await self.__server.stop()
        self.__server = None

    async def __reload_server(self) -> None:
        await self.__stop_server()
        await self.__start_server()

    def __on_server_completed(self, server: Server) -> None:
        self.log.info("Server stopped.")

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.log.error(f"An exception occurred in server: {traceback.format_exception(exception)}")
