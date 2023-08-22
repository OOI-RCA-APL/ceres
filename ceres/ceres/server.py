import asyncio
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from typing_extensions import Self, Unpack, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.config import Config
from ceres.data import ImmutableDataObject
from ceres.directory import Directory
from ceres.errors import (
    ConfigError,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
    ReloadError,
)
from ceres.exceptions import DatabaseInitException
from ceres.filter import ComponentFilter, ComponentFilterArgs
from ceres.internal.project import Project
from ceres.internal.utilities import sleep_forever, strify, uniquify
from ceres.internal.uvicorn import Uvicorn, UvicornConfig
from ceres.object import Object
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from ceres.component import Component, ComponentGroup
    from ceres.database.database import Database
else:
    Component = object
    ComponentGroup = object
    Database = object


class ActionKind(str, Enum):
    CREATE = "create"
    RECREATE = "recreate"
    REMOVE = "remove"


class Action(ImmutableDataObject):
    kind: ActionKind
    address: Address


class Server(Object, kw_only=False):
    config_path: Path

    def __post_init__(self) -> None:
        super().__post_init__()

        match Config.read(self.config_path):
            case Ok(config):
                self.__config: Config = config
            case Fail(errors):
                raise ValueError(str(errors))

        from ceres.database.database import Database

        self.__database = Database(self.__config.database)
        self.__reloading = AsyncEvent()
        self.__reloaded_config: Config | None = None
        self.__port_uvicorn: Uvicorn | None = None
        self.__uds_uvicorn: Uvicorn | None = None

        self.__root = self.__config.create()
        self.root = self.__root

        assert self.root.server is self
        assert self.root.__object_database__ is self.__object_database__

        from ceres.internal.app import App

        self.__app = App(self)
        self.__setup__()

    def __setup__(self) -> None:
        pass

    @property
    @override
    def __object_parent__(self) -> Object | None:
        return None

    @property
    @override
    def __object_descendants__(self) -> Sequence[Object]:
        return [self.root, *self.get_components()]

    @property
    @override
    def __object_database__(self) -> Database:
        return self.__database

    @property
    @override
    def address(self) -> Address:
        return Address.server()

    @property
    @override
    def root(self) -> Component:
        return self.__root

    @root.setter
    def root(self, root: Component) -> None:
        root = root.unref()
        self.__root = root
        self.__root.server = self

    @property
    @override
    def server(self) -> Self:
        return self

    @property
    def config(self) -> Config:
        return self.__config

    @property
    def project_directory(self) -> Directory:
        return Directory(self.config_path.parent)

    @property
    def local_directory(self) -> Directory:
        return self.project_directory.subdir("local")

    @override
    async def __run__(self) -> None:
        self.local_directory.create()
        await self.__load_database()
        await self.__object_sync__()

        async def process() -> None:
            started = False

            while True:
                if started:
                    await self.__reloading.wait()
                    await self.__execute_reload()

                started = True
                self.__reloading.clear()

                self.__start_uds_uvicorn()
                self.__start_port_uvicorn()

                async def start_enabled() -> None:
                    await asyncio.sleep(0)
                    async with await self.__object_database__.init() as session:
                        for component in self.get_components():
                            await component.__object_sync__(session)
                            if component.enabled and not component.running:
                                self.log.info(
                                    f"Starting enabled component '{component.address}'..."
                                )
                                component.start()

                    await sleep_forever()

                tasks = [
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
                            else:
                                task.cancel()
                    if self.stopping:
                        self.log.info("Exit signal received, stopping...")
                        break

        await asyncio.gather(
            super().__run__(),
            process(),
        )

    @override
    async def __stop__(self) -> None:
        await self.__stop_uds_uvicorn()
        await self.__stop_port_uvicorn()

        await self.root.stop()
        await self.__database.dispose()
        await super().__stop__()

    async def load(self) -> "Result[Config, list[ConfigError]]":
        match await Config.load(self.config_path, log=self.log):
            case Ok(config) as ok:
                self.__config = config
                await self.__load_database()
                await self.__load_components()
                return ok
            case Fail() as fail:
                return fail

    @override
    def get_component(self, address: str | DynamicAddress | None = None, /) -> Component | None:
        return self.root.get_component(address)

    @override
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> ComponentGroup:
        return self.root.get_components(filter, inclusive=True, **kwargs)

    async def reload(self) -> Result[Config, ReloadError]:
        if self.__reloading.is_set():
            return Fail(ReloadAlreadyActiveError())

        self.log.info(f"Reloading configuration from '{self.config_path}'...")

        match await Config.load(self.config_path, log=self.log):
            case Ok(config):
                self.log.info("Queueing reload...")
                self.__reloading.set()
                self.__reloaded_config = config
                return Ok(config)
            case Fail(errors):
                self.log.error("Reload failed, found errors in configuration.")
                return Fail(ReloadConfigInvalidError(errors=errors))

    async def __load_database(self) -> None:
        if not await self.__object_database__.tables():
            self.log.info("Database appears empty, initializing database...")
            try:
                await self.__object_database__.init()
                self.log.info("Database initialized successfully.")
            except Exception as exception:
                self.log.error("Database initialization failed.")
                raise DatabaseInitException(str(exception))

    async def __execute_reload(self) -> None:
        self.log.info("Reloading...")
        previous = self.config

        if self.__reloaded_config is None:
            self.log.warning("No new configuration was found, ignoring reload.")
            return

        self.__config = self.__reloaded_config

        changed = False

        if self.config.server != previous.server:
            self.log.info("Server configuration modified, reloading server...")
            try:
                await self.__stop_port_uvicorn()
                self.__start_port_uvicorn()
                self.__start_uds_uvicorn()
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
                self.log.info(
                    "Database configuration modified, reloading database and components..."
                )
                try:
                    running = self.get_components(running=True)
                    await self.root.stop()
                    await self.__database.dispose()
                    from ceres.database.database import Database

                    self.__database = Database(self.config.database)
                    running.start()
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
                    try:
                        await self.__execute_actions(actions)
                    except Exception:
                        self.log.error(f"An issue occurred while syncing: {traceback.format_exc()}")
                finally:
                    changed = True
            else:
                self.log.info("No changes to component configurations.")
        finally:
            self.__reloaded_config = None
            self.__reloading.clear()

        if not changed:
            self.log.info("No changes to configuration. Nothing to do.")

        self.log.info("Reload completed.")

    async def __load_components(self) -> None:
        await self.__object_sync__()
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
                if address.is_root:
                    self.root = component
                else:
                    parent = self.get_component(address.parent)
                    if parent is not None:
                        parent.add_component(component)

            except Exception:
                self.log.error(f"Failed to load '{address}': {traceback.format_exc()}")
                return

        await component.__object_sync__()
        self.log.info(f"Loaded '{address}' as {strify(type(component))}.")

        for child in config.components:
            await self.__load_component(address / child.name)

    async def __execute_actions(self, actions: Sequence[Action]) -> None:
        running = [other.address for other in self.get_components() if other.running]
        for action in actions:
            component = self.get_component(action.address)

            if action.kind == ActionKind.REMOVE:
                if component is not None:
                    self.log.info(f"Removing '{action.address}'...")
                    await component.stop()
                    component.remove_component()
                    self.log.info(f"Removed '{action.address}'.")
            else:
                if action.kind == ActionKind.CREATE:
                    if component is None:
                        self.log.info(f"Creating '{action.address}'...")
                        await self.__load_component(action.address)
                        self.log.info(f"Created '{action.address}'.")
                elif action.kind == ActionKind.RECREATE:
                    if component is not None:
                        self.log.info(f"Recreating '{action.address}'...")
                        await component.stop()
                        component.remove_component()
                        await self.__load_component(action.address)
                        self.log.info(f"Recreated '{action.address}'.")

        for address in running:
            component = self.get_component(address)
            if component is not None and not component.running:
                self.log.info(f"Starting '{address}'...")
                component.start()

        created = [
            action
            for action in actions
            if action.kind == ActionKind.CREATE and self.get_component(action.address) is not None
        ]
        recreated = [
            action
            for action in actions
            if action.kind == ActionKind.RECREATE and self.get_component(action.address) is not None
        ]
        removed = [
            action
            for action in actions
            if action.kind == ActionKind.REMOVE and self.get_component(action.address) is None
        ]

        if created:
            self.log.info(f"{len(created)} components(s) created.")
        if recreated:
            self.log.info(f"{len(recreated)} components(s) reloaded.")
        if removed:
            self.log.info(f"{len(removed)} components(s) removed.")

    def __get_component_reload_actions(self) -> list[Action]:
        return self.__get_component_reload_actions_for(Address.root())

    def __get_component_reload_actions_for(self, address: Address) -> list[Action]:
        config = self.config.get_component(address)

        component = self.root.get_component(address)
        if component is None and config is not None:
            return [Action(kind=ActionKind.CREATE, address=address)]
        if component is not None and config is None:
            return [Action(kind=ActionKind.REMOVE, address=address)]
        if component is None and config is None:
            return []

        assert component is not None
        assert config is not None

        include = {"name", "cls_path", "class", "args"}
        old = (
            {} if component.__config__ is None else component.__config__.model_dump(include=include)
        )
        new = config.model_dump(include=include)

        if old != new:
            return [Action(kind=ActionKind.RECREATE, address=address)]

        actions: list[Action] = []
        children = uniquify(
            [child.address for child in component.components]
            + [component.address / child.name for child in config.components]
        )

        for child in children:
            actions.extend(self.__get_component_reload_actions_for(child))

        return actions

    def __create_uds_uvicorn(self) -> Uvicorn:
        context = Project(self.config_path, self.__config)
        return Uvicorn(
            UvicornConfig(
                app=self.__app,
                uds=str(context.socket_path),
                loop="none",
            )
        )

    def __start_uds_uvicorn(self) -> Uvicorn:
        if self.__uds_uvicorn is None:
            self.__uds_uvicorn = self.__create_uds_uvicorn()

        if not self.__uds_uvicorn.running:
            self.__uds_uvicorn.start()
            self.log.info(f"Listening on socket at '{self.__uds_uvicorn.config.uds}'.")

        return self.__uds_uvicorn

    async def __stop_uds_uvicorn(self) -> None:
        if self.__uds_uvicorn is not None:
            await self.__uds_uvicorn.stop()
            self.log.info(f"Removing listener from socket at '{self.__uds_uvicorn.config.uds}'.")
            self.__uds_uvicorn = None

    def __create_port_uvicorn(self) -> Uvicorn | None:
        if self.__config.server.port is None:
            return None

        return Uvicorn(
            UvicornConfig(
                app=self.__app,
                port=self.__config.server.port,
                loop="none",
            )
        )

    def __start_port_uvicorn(self) -> Uvicorn | None:
        if self.__port_uvicorn is None:
            self.__port_uvicorn = self.__create_port_uvicorn()

        if self.__port_uvicorn is not None and not self.__port_uvicorn.running:
            self.log.info(f"Listening on port {self.__port_uvicorn.config.port}...")
            self.__port_uvicorn.start()

        return self.__port_uvicorn

    async def __stop_port_uvicorn(self) -> None:
        if self.__port_uvicorn is not None:
            self.log.info(f"Removing listener from port {self.__port_uvicorn.config.port}...")
            await self.__port_uvicorn.stop()
            self.__port_uvicorn = None
