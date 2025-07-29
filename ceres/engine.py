from __future__ import annotations

import asyncio
import traceback
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, Sequence, Unpack, final, override

import anyio
from pydantic import Field

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.project import LoadedProject
from ceres._internal.server import Server
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.config import ComponentConfig, Config, ConfigCheckType, ConfigSource
from ceres.data import DeferBuild, ImmutableDataObject, Name, PasswordHash, jsonify
from ceres.directory import Directory
from ceres.error import ConfigError, Failure, ReloadConfigInvalidError, ReloadError
from ceres.event import AttachedEvent, StoppedEvent, StoppingEvent
from ceres.node import Node
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from ceres._internal.entity import BaseEntityManager
    from ceres.component import Component, ComponentFilter, ComponentFilterArgs, ComponentSystem
    from ceres.entity import Entity

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.setting import SettingManager
    from ceres.user import UserManager
    from ceres.workspace import WorkspaceEditManager, WorkspaceManager, WorkspaceMembershipManager


SyncActionType = Literal[
    "load-pending-database-config",
    "load-pending-server-config",
    "create-component",
    "recreate-component",
    "remove-component",
]


class __BaseEngineAction(ImmutableDataObject, DeferBuild):
    type: SyncActionType


class LoadPendingDatabaseConfigEngineAction(__BaseEngineAction):
    type: Literal["load-pending-database-config"] = "load-pending-database-config"


class LoadPendingServerConfigEngineAction(__BaseEngineAction):
    type: Literal["load-pending-server-config"] = "load-pending-server-config"


class CreateComponentEngineAction(__BaseEngineAction):
    type: Literal["create-component"] = "create-component"
    address: Address


class RecreateComponentEngineAction(__BaseEngineAction):
    type: Literal["recreate-component"] = "recreate-component"
    address: Address


class RemoveComponentEngineAction(__BaseEngineAction):
    type: Literal["remove-component"] = "remove-component"
    address: Address


EngineDatabaseAction = LoadPendingDatabaseConfigEngineAction

EngineServerAction = LoadPendingServerConfigEngineAction

EngineComponentAction = (
    CreateComponentEngineAction | RecreateComponentEngineAction | RemoveComponentEngineAction
)

EngineAction = EngineDatabaseAction | EngineServerAction | EngineComponentAction


class EngineActions(ImmutableDataObject, DeferBuild):
    database: EngineDatabaseAction | None
    server: EngineServerAction | None
    components: Sequence[EngineComponentAction] = Field(default_factory=list)


@final
class Engine(Node):
    __slots__ = (
        "__loaded",
        "__config",
        "__config_path",
        "__apply_lock",
        "__database",
        "__root",
        "__server",
    )

    def __init__(self) -> None:
        super().__init__()

        self.__loaded = False
        self.__config = Config()
        self.__config_path: Path | None = None
        self.__apply_lock = asyncio.Lock()
        self.__database = Database()
        self.__root: ComponentSystem | None = None
        self.__server: Server | None = None

    @property
    @override
    def __container__(self) -> None:
        return None

    @property
    @override
    def root(self) -> ComponentSystem | None:
        return self.__root

    @root.setter
    def root(self, root: Component | ComponentSystem | None) -> None:
        self.__set_root(root)

    @property
    @override
    def address(self) -> Address:
        return Address.engine()

    @property
    @override
    def engine(self) -> Self:
        return self

    @property
    def server(self) -> Server | None:
        return self.__server

    @property
    @override
    def database(self) -> Database:
        return self.__database

    @property
    @override
    def config(self) -> Config:
        return self.__config

    @cached_property
    def users(self) -> UserManager:
        return UserManager(self)

    @cached_property
    def settings(self) -> SettingManager:
        return SettingManager(self)

    @cached_property
    def workspaces(self) -> WorkspaceManager:
        return WorkspaceManager(self)

    @cached_property
    def workspace_memberships(self) -> WorkspaceMembershipManager:
        return WorkspaceMembershipManager(self)

    @cached_property
    def workspace_edits(self) -> WorkspaceEditManager:
        return WorkspaceEditManager(self)

    def __manager__(self, Entity: type[Entity], /) -> BaseEntityManager:
        return util.get_entity_manager(self, Entity)

    @property
    def config_path(self) -> Path | None:
        return self.__config_path

    @property
    def project_directory(self) -> Directory | None:
        if self.config_path is None:
            return None

        return Directory(self.config_path.parent)

    @property
    def local_directory(self) -> Directory | None:
        if self.project_directory is None:
            return None

        return self.project_directory.subdir("local")

    @override
    async def __run__(self) -> None:
        if self.local_directory is not None:
            self.local_directory.create()

        await self.__apply(self.config_path, self.config)

        await self.__load_database()
        await self.__node_sync__()

        async with await self.database.init() as session:
            components = self.get_components()
            for component in components:
                await component.system.__node_sync__(session)
            if self.root is not None and self.root.enabled:
                self.root.start(all_enabled=True)

        try:
            await super().__run__()
        finally:
            if self.stopping:
                self.log.info("Exit signal received, stopping...")

    @override
    def __stopping__(self) -> None:
        self.events.emit(StoppingEvent)

    @override
    async def __stop__(self) -> None:
        await self.__stop_server()
        if self.__root is not None:
            await self.__root.stop()

    @override
    async def __post_stop__(self) -> None:
        await super().__post_stop__()
        self.events.emit(StoppedEvent)
        await self.flush()
        await self.__database.dispose()

    @override
    def get_component(self, address: str | DynamicAddress | None = None) -> Component | None:
        if self.__root is None:
            return None

        return self.__root.get_component(address)

    @override
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Component]:
        if self.__root is None:
            return []

        return self.__root.get_components(filter, inclusive=True, **kwargs)

    def attach(
        self,
        root: Component | ComponentSystem,
        /,
        name: Name | None = None,
    ) -> Component | None:
        """
        Attach a component as the root component of the engine. If there is already a root component
        set, it will be detached and returned. Otherwise returns `None`.
        """
        return self.__set_root(root, name)

    async def load(
        self,
        source: ConfigSource[Config],
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        silent: bool = False,
    ) -> Result[Config, ConfigError]:
        match await Config.load(source, checks=checks):
            case Ok(config):
                pass
            case Fail(errors):
                return Fail(errors)

        if not silent:
            if isinstance(source, Path):
                self.log.info(f"Loading configuration from '{source}'...")
            else:
                self.log.info("Loading provided configuration.")

        await self.__apply(source if isinstance(source, Path) else None, config, silent=silent)
        return Ok(config)

    async def reload(
        self,
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        silent: bool = False,
    ) -> Result[Config, ReloadError]:
        if self.config_path is not None:
            self.log.info(f"Reloading configuration from '{self.config_path}'...")
            source = self.config_path
        else:
            self.log.info("Reloading current configuration...")
            source = self.config

        match await Config.load(source, checks=checks):
            case Ok(config):
                pass
            case Fail(error):
                return Fail(ReloadConfigInvalidError(error=error))

        await self.__apply(source if isinstance(source, Path) else None, config, silent=silent)
        return Ok(config)

    async def hash_password(self, password: str) -> PasswordHash:
        return await self.__database.hash_password(password)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        return await self.__database.verify_password(password, hash)

    def __set_root(
        self,
        root: Component | ComponentSystem | None,
        name: Name | None = None,
    ) -> Component | None:
        root = util.as_component_system(root)
        previous = self.__root
        if previous is root:
            return

        if previous is not None and previous.container is self:
            previous.detach()

        if root is not None:
            root.detach()
            if name is not None:
                root.name = name

        self.__root = root
        if root is not None and root.container is not self:
            root.container = self
            root.events.emit(AttachedEvent)

        return previous.component if previous is not None else None

    async def __load_database(self) -> None:
        if not await self.database.initialized():
            self.log.info("Database appears empty, initializing database...")
            try:
                await self.database.init()
                self.log.info("Database initialized successfully.")
            except Failure:
                self.log.error("Database initialization failed.")
                raise

    def __create_server(self) -> Server | None:
        if self.config_path is None:
            self.log.error("Cannot create server without configuration path.")
            return None

        return Server(self, LoadedProject(self.config_path, self.config), self.config.server)

    async def __start_server(self) -> Server | None:
        if self.__server is None:
            self.__server = self.__create_server()

        if self.__server is not None and not self.__server.running:
            self.log.info("Starting HTTP server.")
            self.__server.start(on_exception=self.__on_server_exception)

            with anyio.move_on_after(1):
                while self.__server.cli_bind is None:
                    await asyncio.sleep(0.01)

            if self.__server.cli_bind:
                self.log.info(f"HTTP CLI server listening on {self.__server.cli_bind}.")
            if self.__server.bind:
                self.log.info(f"HTTP web server listening on {self.__server.bind}.")

        return self.__server

    async def __stop_server(self) -> None:
        if self.__server is not None:
            self.log.info("Stopping HTTP server.")
            await self.__server.stop()
            self.__server = None
            self.log.info("HTTP server stopped.")

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.log.error(f"An exception occurred while running server: {exception}")

    async def __apply(
        self,
        config_path: Path | None,
        config: Config,
        *,
        silent: bool = False,
    ) -> EngineActions:
        async with self.__apply_lock:
            self.__config_path = config_path
            self.__config = config

            running = [component.system.address for component in self.get_components(running=True)]

            reloading = self.__loaded

            verb = "reload" if reloading else "load"

            actions = self.get_apply_actions(config)
            if actions.server is None and actions.database is None and not actions.components:
                if not silent:
                    self.log.info("Configuration appears up-to-date.")

                self.__loaded = True
                return actions

            if not silent:
                self.log.debug("Actions pending: " + jsonify(actions))

            if actions.server is not None:
                if not silent:
                    self.log.info(f"Server configuration will be {verb}ed.")

                try:
                    await self.__stop_server()
                    await self.__start_server()
                    if not silent:
                        self.log.info(f"Server configuration {verb}ed successfully.")
                except Exception:
                    self.log.error(
                        f"An issue occurred while {verb}ing the server: {traceback.format_exc()}"
                    )

            if actions.database is not None:
                if not silent:
                    self.log.info(f"Database configuration will be {verb}ed.")
                try:
                    if self.__root is not None:
                        await self.__root.stop()

                    await self.__database.dispose()
                    self.__database = Database(config.database)
                    if not silent:
                        self.log.info(f"Database configuration {verb}ed successfully.")
                except Exception:
                    self.log.error(
                        f"An issue occurred while reloading the database: {traceback.format_exc()}"
                    )

            if actions.components:
                if not silent:
                    self.log.info(f"Component configurations will be {verb}ed.")

                try:
                    root = await self._execute_component_actions(
                        util.as_component(self.__root),
                        config.root,
                        actions.components,
                        silent=silent,
                    )

                    if root is not None:
                        self.root = root.system
                    else:
                        self.root = None

                    if not silent:
                        self.log.info(f"Component configurations {verb}ed successfully.")
                except Exception:
                    self.log.error(
                        f"An issue occurred while {verb}ing components: {traceback.format_exc()}"
                    )

            for component in self.get_components():
                component_config = config.get_component(component.system.address)
                if component_config is not None and component.system.config != component_config:
                    self.log.info(
                        f"Assigning new configuration in-place for '{component.system.address}'."
                    )
                    component.system.config = component_config

                component.system.sync_child_order()

            for address in running:
                component = self.get_component(address)
                if component is not None:
                    component.system.start()

            self.__loaded = True

        if not silent:
            self.log.info(f"{verb.capitalize()} completed.")

        return actions

    def get_apply_actions(self, config: Config) -> EngineActions:
        if self.__database.config != config.database:
            database = LoadPendingDatabaseConfigEngineAction()
        else:
            database = None

        if self.__server is None or self.__server.config != config.server:
            server = LoadPendingServerConfigEngineAction()
        else:
            server = None

        components = self._get_pending_component_actions(
            util.as_component(self.__root), config.root
        )

        return EngineActions(
            database=database,
            server=server,
            components=components,
        )

    def _get_pending_component_actions(
        self,
        root_component: Component | None,
        root_config: ComponentConfig,
        address: Address = Address.ROOT,
    ) -> list[EngineComponentAction]:
        if address.is_engine:
            address = Address.ROOT

        component = (
            root_component.system.get_component(address) if root_component is not None else None
        )
        config = root_config.get_component(address)

        match (component, config):
            case (None, None):
                return []
            case (None, config):
                return [CreateComponentEngineAction(address=address)]
            case (component, None):
                return [RemoveComponentEngineAction(address=address)]
            case (component, config):
                pass

        exclude = {"components"}
        old = (
            {}
            if component.system.config is None
            else component.system.config.model_dump(exclude=exclude)
        )
        new = config.model_dump(exclude=exclude)

        if old != new:
            affected = [address]
            for referencer in component.system.get_referencing_components(recursive=True):
                if not address.contains(referencer.system.address):
                    affected.append(referencer.system.address)

            return [RecreateComponentEngineAction(address=address) for address in affected]

        actions: list[EngineComponentAction] = []
        children = util.uniquify(
            [child.address for child in component.system.children]
            + [component.system.address / child.name for child in config.components]
        )

        for child in children:
            actions.extend(
                self._get_pending_component_actions(
                    root_component,
                    root_config,
                    child,
                )
            )

        return actions

    async def _execute_component_actions(
        self,
        root_component: Component | None,
        root_config: ComponentConfig,
        actions: Sequence[EngineComponentAction],
        *,
        silent: bool = False,
    ) -> Component | None:
        for action in actions:
            if root_component is not None:
                container = root_component.system.get_node(action.address.container)
                component = root_component.system.get_component(action.address)
            else:
                container = self
                component = None

            config = root_config.get_component(action.address)

            match action:
                case CreateComponentEngineAction():
                    if not silent:
                        self.log.info(f"Creating '{action.address}'...")

                    if config is None:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' not found in configuration. Skipping..."
                            )

                        continue

                    if component is not None:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' already exists. Skipping..."
                            )

                        continue

                    match config.create(container):
                        case Ok(component):
                            for current in component.system.get_components(inclusive=True):
                                if not silent:
                                    self.log.info(
                                        f"Created '{current.system.address}' as instance of {type(current)}."
                                    )
                        case Fail(errors):
                            if not silent:
                                self.log.error(
                                    f"Failed to create '{action.address}'. Errors: {jsonify(errors, indent=2)}"
                                )
                case RecreateComponentEngineAction():
                    self.log.info(f"Recreating '{action.address}'...")
                    if config is None:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' not found in configuration. Skipping..."
                            )

                        continue

                    if component is not None:
                        if not silent:
                            self.log.info(f"Stopping '{action.address}'...")

                        await component.system.stop()
                        component.system.detach()
                    else:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' does not exist. Creating..."
                            )

                    match config.create(container):
                        case Ok(component):
                            for current in component.system.get_components(inclusive=True):
                                if not silent:
                                    self.log.info(
                                        f"Recreated '{current.system.address}' as instance of {type(current)}."
                                    )
                        case Fail(errors):
                            if not silent:
                                self.log.error(
                                    f"Failed to recreate '{action.address}'. Errors: {jsonify(errors, indent=2)}"
                                )
                case RemoveComponentEngineAction():
                    if component is not None:
                        if not silent:
                            self.log.info(f"Stopping '{action.address}'...")

                        await component.system.stop()
                        component.system.detach()

                        if not silent:
                            self.log.info(f"Removed '{action.address}'.")
                    else:
                        if not silent:
                            self.log.warning(
                                f"Component at {action.address} does not exist to remove. Skipping..."
                            )

            if action.address.is_root:
                root_component = component

        return root_component
