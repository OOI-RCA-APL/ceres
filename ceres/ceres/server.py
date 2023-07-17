import asyncio
import socket
import traceback
from asyncio import FIRST_COMPLETED, Task, gather
from asyncio import Event as AsyncEvent
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import (
    TYPE_CHECKING,
    Any,
    final,
)

from typing_extensions import override
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn

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
from ceres.exceptions import DatabaseInitException
from ceres.internal import logs
from ceres.internal.context import ProjectContext
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import sleep_forever, strify
from ceres.logs import Log
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from uvicorn.server import Protocols
else:
    Protocols = "Protocols"


class ActionKind(str, Enum):
    CREATE = "create"
    RECREATE = "recreate"
    REMOVE = "remove"


class Action(ImmutableDataObject):
    kind: ActionKind
    address: Address


@final
class Server(Tasklet):
    def __init__(self, config_path: Path) -> None:
        self.__config_path = config_path
        match Config.read(config_path):
            case Ok(config):
                self.__config = config
            case Fail(errors):
                raise ValueError(str(errors))

        self.__config_queue: Queue[Config] = Queue()
        self.__database = Database(self.__config.database)
        self.__root = self.__config.create()
        self.__root.bind_server(self)
        self.__reloading = AsyncEvent()

        self.__port_uvicorn: _Uvicorn | None = None
        self.__uds_uvicorn: _Uvicorn | None = None

        from ceres.internal.app import App

        self.__app = App(self)

    @property
    def config(self) -> Config:
        return self.__config

    @property
    def project_directory(self) -> Directory:
        return Directory(self.__config_path.parent)

    @property
    def local_directory(self) -> Directory:
        return self.project_directory.subdir("local")

    @property
    def database(self) -> Database:
        return self.__database

    @property
    def root(self) -> Component:
        return self.__root

    @property
    def log(self) -> Log:
        return self.__root.log

    @override
    async def __run__(self) -> None:
        context = ProjectContext(self.__config)
        self.local_directory.create()

        await self.load_database()

        started = False

        async def serve() -> None:
            self.__uds_uvicorn = _Uvicorn(
                UvicornConfig(
                    app=self.__app,
                    uds=str(context.socket),
                    loop="none",
                )
            )

            if self.__config.server.port is not None:
                self.__port_uvicorn = _Uvicorn(
                    UvicornConfig(
                        app=self.__app,
                        port=self.__config.server.port,
                        loop="none",
                    )
                )

            await gather(
                self.__uds_uvicorn.serve(),
                self.__port_uvicorn.serve() if self.__port_uvicorn is not None else sleep_forever(),
            )

        async def start_enabled() -> None:
            await asyncio.sleep(0)
            for component in self.root.get_components(inclusive=True):
                await component.sync_with_database()
                if component.enabled:
                    self.log.info(f"Starting enabled component '{component.address}'...")
                    component.start()

        while True:
            if started:
                await self.__reloading.wait()
                await self.__execute_reload()

            started = True
            self.__reloading.clear()

            tasks = [
                asyncio.create_task(serve(), name="serve"),
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
        if self.__port_uvicorn is not None:
            await self.__port_uvicorn.shutdown()
            self.__port_uvicorn = None
        if self.__uds_uvicorn is not None:
            await self.__uds_uvicorn.shutdown()
            self.__uds_uvicorn = None

        await self.root.stop()

    async def load(self) -> "Result[Config, list[ConfigError]]":
        match await Config.load(self.__config_path, log=self.log):
            case Ok(config) as ok:
                self.__config = config
                await self.load_database()
                await self.load_components()
                return ok
            case Fail() as fail:
                return fail

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
                raise DatabaseInitException(str(exception))

    async def __execute_reload(self) -> None:
        self.log.info("Reloading...")
        config_previous = self.config

        try:
            self.__config = self.__config_queue.get_nowait()
        except Empty:
            self.log.warning("No new configuration was found, ignoring reload.")
            return

        if self.config == config_previous:
            self.log.info("Configuration was not modified. Nothing to reload.")
            return

        # if self.config.server != config_previous.server:
        #     self.log.info("Server configuration modified, reloading server...")
        #     try:
        #         await self.__reload_server()
        #     except Exception:
        #         self.log.error(
        #             f"An issue occurred while reloading the server: {traceback.format_exc()}"
        #         )

        if self.config.database != config_previous.database:
            self.log.info(
                "Database configuration modified, reloading all components and database..."
            )
            try:
                await self.root.stop()
                await self.__database.dispose()
                self.__database = Database(self.config.database)
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
        await self.__load_subcomponents_for(self.root)

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
            id = await self.root.assign_component_id(address)

            if child is None:
                try:
                    child = subconfig.create()
                    component.add_component(child)
                    await child.sync_with_database()
                    child.assign_references(references)
                    await self.__load_subcomponents_for(child)
                    self.log.info(
                        f"Loaded '{child.address}' as {strify(type(child))} with ID '{id}'."
                    )
                except Exception:
                    component.log.error(f"Failed to load '{address}': {traceback.format_exc()}")
                    continue

            references[child.name] = child

    async def sync_components(self) -> None:
        actions = self.get_reload_actions()

        for action in actions:
            component = self.root.get_component(action.address)

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

        await self.__load_subcomponents_for(self.root)

        created = [
            action
            for action in actions
            if action.kind == ActionKind.CREATE and action.address in self.root.components
        ]
        recreated = [
            action
            for action in actions
            if action.kind == ActionKind.RECREATE and action.address in self.root.components
        ]
        removed = [
            action
            for action in actions
            if action.kind == ActionKind.REMOVE and action.address not in self.root.components
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
            component = self.root.get_component(name)
            address = self.root.address / name
            if component is None:
                actions.append(Action(kind=ActionKind.CREATE, address=address))
            elif component.__config__ != config:
                actions.append(Action(kind=ActionKind.RECREATE, address=address))

        for component in self.root.components:
            if component.name not in configs:
                actions.append(Action(kind=ActionKind.REMOVE, address=component.address))

        return actions


class _Uvicorn(BaseUvicorn):
    @override
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        try:
            await super().serve(sockets)
        except SystemExit:
            # TODO: This occurs when the server's port couldn't be opened. We should probably try to
            # reconnect when this happens. For now, Uvicorn logs the error which should help
            # diagnose the problem.
            pass

    @override
    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass

    @override
    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        async def stop_connection(connection: Protocols) -> None:
            try:
                await connection.close()  # type: ignore
            except Exception:
                connection.shutdown()

        async def stop_task(task: Task[Any]) -> None:
            task.cancel()

        await asyncio.gather(
            *(stop_connection(connection) for connection in self.server_state.connections),
            *(stop_task(task) for task in self.server_state.tasks),
            return_exceptions=True,
        )

        if hasattr(self, "servers"):
            await super().shutdown(sockets)
