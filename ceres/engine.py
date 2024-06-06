from __future__ import annotations

import asyncio
import os
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from pathlib import Path
from typing import TYPE_CHECKING, Self, Sequence, Unpack, final, override

from ceres._internal import util
from ceres._internal.app.main import App
from ceres._internal.project import Project
from ceres._internal.server import Server
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.component import Component, ComponentFilter, ComponentFilterArgs, ComponentSystem
from ceres.config import Config, ServerSSLConfig
from ceres.data import ImmutableDataObject, PasswordHash, StrEnum, jsonify
from ceres.directory import Directory
from ceres.error import (
    ConfigError,
    ConfigNotProvidedError,
    Failure,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
)
from ceres.event import StoppedEvent, StoppingEvent
from ceres.node import Node
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from ceres.database.database import Database
else:
    Database = object


class ReloadActionType(StrEnum):
    CREATE = "create"
    RECREATE = "recreate"
    REMOVE = "remove"


class ReloadAction(ImmutableDataObject):
    type: ReloadActionType
    address: Address


@final
class Engine(Node):
    def __init__(self, source: Path | Config | None = None) -> None:
        super().__init__()

        if source is None:
            self._config = Config()
            self._config_path = None
        elif isinstance(source, Path):
            self._config_path = source
            match Config.read(source):
                case Ok(config):
                    self._config = config
                case Fail(errors):
                    raise ValueError(str(errors))
        else:
            self._config = source
            self._config_path = None

        from ceres.database.database import Database

        self._database = Database(self._config.database)
        self._reloading = AsyncEvent()
        self._reloaded_config: Config | None = None
        self._server: Server | None = None
        self.root = Component(__with_name__="root").system

        if self._config_path is not None:
            self._project_directory = Directory(self._config_path.parent)
        else:
            self._project_directory = Directory(os.getcwd())

        self.__setup__()

    def __setup__(self) -> None:
        pass

    @property
    @override
    def __container__(self) -> None:
        return None

    @property
    @override
    def root(self) -> ComponentSystem | None:
        return self._root

    @root.setter
    def root(self, root: ComponentSystem | Component) -> None:
        self._root = util.as_component_system(root)
        self._root.engine = self

    @property
    @override
    def address(self) -> Address:
        return Address.engine()

    @property
    @override
    def engine(self) -> Self:
        return self

    @property
    @override
    def database(self) -> Database:
        return self._database

    @property
    @override
    def config(self) -> Config:
        return self._config

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def project_directory(self) -> Directory | None:
        return self._project_directory

    @property
    def local_directory(self) -> Directory | None:
        if self.project_directory is None:
            return None

        return self.project_directory.subdir("local")

    @override
    async def __run__(self) -> None:
        if self.local_directory is not None:
            self.local_directory.create()

        await self.__load_database()
        await self.__node_sync__()

        async def process() -> None:
            started = False

            while True:
                if started:
                    await self._reloading.wait()
                    await self.__execute_reload()

                started = True
                self._reloading.clear()

                self.__start_server()

                async def start_enabled() -> None:
                    await asyncio.sleep(0)
                    async with await self.database.init() as session:
                        for component in self.get_components():
                            await component.system.__node_sync__(session)
                            if component.system.enabled and not component.system.running:
                                component.system.start()

                    await util.sleep_forever()

                tasks = [
                    asyncio.create_task(start_enabled(), name="start-enabled"),
                    asyncio.create_task(self._reloading.wait(), name="reload-wait"),
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
                            else:
                                task.cancel()
                    if self.stopping:
                        self.log.info("Exit signal received, stopping...")
                        break

        await asyncio.gather(super().__run__(), process())

    @override
    async def __stop__(self) -> None:
        self.events.emit(StoppingEvent)
        await self.__stop_server()
        await self._root.stop()

    @override
    async def __post_stop__(self) -> None:
        await super().__post_stop__()
        self.events.emit(StoppedEvent)
        await self.flush()
        await self._database.dispose()

    async def load(self, config: Config | None = None) -> Result[Config, list[ConfigError]]:
        if config is not None:
            match await config.check(log=self.log.info):
                case Ok(config):
                    self._config = config
                case Fail() as fail:
                    return fail
        elif self._config_path is not None:
            match await Config.load(self._config_path, log=self.log.info):
                case Ok(config):
                    self._config = config
                case Fail() as fail:
                    return fail
        else:
            return Fail([ConfigNotProvidedError(message="No configuration source provided.")])

        await self.__load_database()
        await self.__load_components()
        return Ok(self._config)

    @override
    def get_component(self, address: str | DynamicAddress | None = None) -> Component | None:
        return self._root.get_component(address)

    @override
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Component]:
        return self._root.get_components(filter, inclusive=True, **kwargs)

    async def hash_password(self, password: str) -> PasswordHash:
        return await self._database.hash_password(password)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        return await self._database.verify_password(password, hash)

    async def reload(self, config: Config | None = None) -> Config:
        """
        Reload the engine's configuration. An optional `config` object can be provided directly to
        reload from. If omitted, the configuration will be reloaded from the engine's configuration
        file path.
        """
        if self._reloading.is_set():
            raise Failure(ReloadAlreadyActiveError)

        if config is not None:
            self.log.info("Queueing reload of provided configuration...")
            self._reloading.set()
            self._reloaded_config = config
            return config

        if self._config_path is None:
            self.log.warning("No configuration path provided, ignoring reload.")
            return self.config

        self.log.info(f"Reloading configuration from '{self._config_path}'...")
        match await Config.load(self._config_path, log=self.log.info):
            case Ok(config):
                self.log.info("Configuration parsed successfully, queueing reload...")
                self._reloading.set()
                self._reloaded_config = config
                return config
            case Fail(errors):
                self.log.error("Reload failed, found errors in configuration.")
                raise Failure(ReloadConfigInvalidError(errors=errors))

    async def __load_database(self) -> None:
        if not await self.database.initialized():
            self.log.info("Database appears empty, initializing database...")
            try:
                await self.database.init()
                self.log.info("Database initialized successfully.")
            except Failure:
                self.log.error("Database initialization failed.")
                raise

    async def __execute_reload(self) -> None:
        self.log.info("Reloading configuration...")
        previous = self.config

        if self._reloaded_config is None:
            self.log.warning("No queued configuration was found, ignoring reload.")
            return

        self._config = self._reloaded_config

        changed = False

        if self.config.server != previous.server:
            self.log.info("Server configuration modified, reloading...")
            try:
                await self.__stop_server()
                self.__start_server()
            except Exception:
                self.log.error(
                    f"An issue occurred while reloading the server: {traceback.format_exc()}"
                )
            finally:
                changed = True
        else:
            self.log.info("No changes to server configuration.")

        try:
            if self.config.database != previous.database:
                self.log.info("Database configuration modified, reloading database and systems...")
                try:
                    running = self.get_components(running=True)
                    await self._root.stop()
                    await self._database.dispose()
                    from ceres.database.database import Database

                    self._database = Database(self.config.database)
                    for component in running:
                        component.system.start()
                except Exception:
                    self.log.error(
                        f"An issue occurred while reloading components and database: "
                        f"{traceback.format_exc()}"
                    )
                finally:
                    changed = True
            else:
                self.log.info("No changes to database configuration.")

            if actions := self.__get_component_reload_actions():
                try:
                    self.log.info("Syncing component configurations...")
                    self.log.info(f"Pending actions: {jsonify(actions, indent=2)}")
                    try:
                        await self.__execute_actions(actions)
                    except Exception:
                        self.log.error(f"An issue occurred while syncing: {traceback.format_exc()}")
                finally:
                    changed = True
            else:
                self.log.info("No changes to component configurations.")
        finally:
            self._reloaded_config = None
            self._reloading.clear()

        if not changed:
            self.log.info("No changes to configuration. Nothing to do.")

        self.log.info("Reload completed.")

    async def __load_components(self) -> None:
        await self.__node_sync__()
        await self.__load_component(Address.root())

    async def __load_component(self, address: Address) -> Component | None:
        if address.is_root:
            config = self.config
        else:
            config = self.config.get_component(address)
            if config is None:
                return None

        component = self.get_component(address)

        if component is None:
            try:
                component = config.create()
            except Failure as failure:
                self.log.error(f"Failed to load '{address}': {failure.error}")
                return None

            if address.is_root:
                self.root = component.system
                assert component.system.engine is self
                assert component.system.database is self.database
            else:
                parent = util.as_component_system(self.get_component(address.parent))
                if parent is not None:
                    parent.attach(component)

        await component.system.__node_sync__()
        self.log.info(f"Loaded '{address}' with component type {util.strify(type(component))}.")

        for child in config.components:
            await self.__load_component(address / child.name)

        return component

    async def __execute_actions(self, actions: Sequence[ReloadAction]) -> None:
        running = [other.system.address for other in self.get_components() if other.system.running]
        for action in actions:
            component = self.get_component(action.address)

            if action.type == ReloadActionType.REMOVE:
                if component is not None:
                    self.log.info(f"Removing '{action.address}'...")
                    await component.system.stop()
                    component.system.detach()
                    self.log.info(f"Removed '{action.address}'.")
            else:
                if action.type == ReloadActionType.CREATE:
                    if component is None:
                        self.log.info(f"Creating '{action.address}'...")
                        await self.__load_component(action.address)
                        self.log.info(f"Created '{action.address}'.")
                elif action.type == ReloadActionType.RECREATE:
                    if component is not None:
                        self.log.info(f"Recreating '{action.address}'...")
                        await component.system.stop()
                        component.system.detach()
                        await self.__load_component(action.address)
                        self.log.info(f"Recreated '{action.address}'.")

        for address in running:
            component = self.get_component(address)
            if component is not None and not component.system.running:
                self.log.info(f"Starting '{address}'...")
                component.system.start()

        created = [
            action
            for action in actions
            if action.type == ReloadActionType.CREATE and self.get_node(action.address) is not None
        ]
        recreated = [
            action
            for action in actions
            if action.type == ReloadActionType.RECREATE
            and self.get_node(action.address) is not None
        ]
        removed = [
            action
            for action in actions
            if action.type == ReloadActionType.REMOVE and self.get_node(action.address) is None
        ]

        if created:
            self.log.info(f"{len(created)} components(s) created.")
        if recreated:
            self.log.info(f"{len(recreated)} components(s) reloaded.")
        if removed:
            self.log.info(f"{len(removed)} components(s) removed.")

    def __get_component_reload_actions(self) -> list[ReloadAction]:
        return self.__get_component_reload_actions_for(Address.root())

    def __get_component_reload_actions_for(self, address: Address) -> list[ReloadAction]:
        component = self.get_component(address)
        config = self.config.get_component(address)

        match (component, config):
            case (None, None):
                return []
            case (None, config):
                return [ReloadAction(type=ReloadActionType.CREATE, address=address)]
            case (component, None):
                return [ReloadAction(type=ReloadActionType.REMOVE, address=address)]
            case (component, config):
                pass

        include = {"name", "cls_path", "class", "arguments"}
        old = (
            {}
            if component.system.config is None
            else component.system.config.model_dump(include=include)
        )
        new = config.model_dump(include=include)

        if old != new:
            affected = [address]
            for referencer in component.system.get_referencing_components(recursive=True):
                if not address.contains(referencer.system.address):
                    affected.append(referencer.system.address)

            return [
                ReloadAction(type=ReloadActionType.RECREATE, address=address)
                for address in affected
            ]

        actions: list[ReloadAction] = []
        children = util.uniquify(
            [child.address for child in component.system.children]
            + [component.system.address / child.name for child in config.components]
        )

        for child in children:
            actions.extend(self.__get_component_reload_actions_for(child))

        return actions

    def __create_server(self) -> Server | None:
        socket: Path | None = None
        if self._config.server.socket is not None:
            socket = self._config.server.socket
        elif self._config_path is not None:
            project = Project(self._config_path, self._config)
            socket = project.socket_path
        elif self._config.server.port is None:
            return None

        from ceres._internal.server import HypercornConfig

        config = HypercornConfig()
        config.loglevel = "CRITICAL"

        # SSL / HTTPS
        ssl = self._config.server.ssl or ServerSSLConfig()
        config.keyfile = str(ssl.key) if ssl.key is not None else None
        config.keyfile_password = ssl.key_password
        config.certfile = str(ssl.cert) if ssl.cert is not None else None
        config.ca_certs = str(ssl.ca_certs) if ssl.ca_certs is not None else None

        bind: list[str] = []
        insecure_bind: list[str] = []

        if self._config.server.port is not None:
            bind.append(f"{self._config.server.host}:{self._config.server.port}")
        if socket is not None:
            if config.ssl_enabled:
                insecure_bind.append(f"unix:{socket}")
            else:
                bind.append(f"unix:{socket}")

        config.bind = bind
        config.insecure_bind = insecure_bind

        return Server(config, App(self))

    def __start_server(self) -> Server | None:
        if self._server is None:
            self._server = self.__create_server()

        if self._server is not None and not self._server.running:
            bind = [*self._server._config.bind, *self._server._config.insecure_bind]
            self.log.info(f"Listening on {bind}...")
            self._server.start(on_exception=self.__on_server_exception)

        return self._server

    async def __stop_server(self) -> None:
        if self._server is not None:
            bind = [*self._server._config.bind, *self._server._config.insecure_bind]
            self.log.info(f"Removing listeners from {bind}...")
            await self._server.stop()
            self._server = None

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.log.error(
            f"An exception occurred while running server on {server._config.bind}: {exception}"
        )
