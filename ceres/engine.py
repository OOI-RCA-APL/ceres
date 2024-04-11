import asyncio
import os
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence, TypeVar

from aiotools.taskgroup import TaskGroup
from typing_extensions import Self, Unpack, final, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.config import Config, ServerSSLConfig
from ceres.data import ImmutableDataObject, PasswordHash, StrEnum
from ceres.directory import Directory
from ceres.errors import (
    ConfigError,
    ConfigNotProvidedError,
    Failure,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
)
from ceres.events import Event, LogEvent, StoppedEvent, StoppingEvent
from ceres.filter import SystemFilter, SystemFilterArgs
from ceres.internal.app.main import App
from ceres.internal.project import Project
from ceres.internal.server import Server, ServerInternalConfig
from ceres.internal.utilities import sleep_forever, strify, uniquify
from ceres.node import Node
from ceres.result import Fail, Ok, Result
from ceres.system import System, SystemGroup

if TYPE_CHECKING:
    from ceres.database.database import Database
else:
    Database = object

_EventT = TypeVar("_EventT", bound=Event)


class ActionType(StrEnum):
    CREATE = "create"
    RECREATE = "recreate"
    REMOVE = "remove"


class Action(ImmutableDataObject):
    type: ActionType
    address: Address


@final
class Engine(Node):
    def __init__(self, source: Path | Config | None = None) -> None:
        super().__init__()

        if source is None:
            self.__config = Config()
            self.__config_path = None
        elif isinstance(source, Path):
            self.__config_path = source
            match Config.read(source):
                case Ok(config):
                    self.__config = config
                case Fail(errors):
                    raise ValueError(str(errors))
        else:
            self.__config = source
            self.__config_path = None

        from ceres.database.database import Database
        from ceres.system import System

        self.__database = Database(self.__config.database)
        self.__reloading = AsyncEvent()
        self.__reloaded_config: Config | None = None
        self.__server: Server | None = None
        self.root = System()

        if self.__config_path is not None:
            self.__project_directory = Directory(self.__config_path.parent)
        else:
            self.__project_directory = Directory(os.getcwd())

        self.__setup__()

    def __setup__(self) -> None:
        pass

    @property
    @override
    def __node_parent__(self) -> None:
        return None

    @property
    @override
    def __node_descendants__(self) -> Iterable[Node]:
        return self.__root.get_systems(inclusive=True)

    @property
    @override
    def parent(self) -> None:
        return None

    @property
    @override
    def root(self) -> System | None:
        return self.__root

    @root.setter
    def root(self, root: System) -> None:
        self.__root = root
        self.__root.engine = self

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
        return self.__database

    @property
    def config(self) -> Config:
        return self.__config

    @property
    def config_path(self) -> Path | None:
        return self.__config_path

    @property
    def project_directory(self) -> Directory | None:
        return self.__project_directory

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
                    await self.__reloading.wait()
                    await self.__execute_reload()

                started = True
                self.__reloading.clear()

                self.__start_server()

                async def start_enabled() -> None:
                    await asyncio.sleep(0)
                    async with await self.database.init() as session:
                        for system in self.get_systems():
                            await system.__node_sync__(session)
                            if system.enabled and not system.running:
                                system.start()

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

        async with TaskGroup() as group:
            group.create_task(super().__run__())
            group.create_task(process())

    @override
    async def __stop__(self) -> None:
        self.emit(StoppingEvent)
        await self.__stop_server()
        await self.__root.stop()

        self.emit(StoppedEvent)
        await self.flush()
        await self.__database.dispose()

    async def load(self, config: Config | None = None) -> "Result[Config, list[ConfigError]]":
        if config is not None:
            match await config.check(log=self.log):
                case Ok(config):
                    self.__config = config
                case Fail() as fail:
                    return fail
        elif self.__config_path is not None:
            match await Config.load(self.__config_path, log=self.log):
                case Ok(config):
                    self.__config = config
                case Fail() as fail:
                    return fail
        else:
            return Fail([ConfigNotProvidedError(message="No configuration source provided.")])

        await self.__load_database()
        await self.__load_systems()
        return Ok(self.__config)

    @override
    def propagate(self, event: _EventT) -> _EventT:
        if not isinstance(event, LogEvent):
            self.log.derive(event.address).info(
                "[event] [{type}] {event}",
                type=event.type,
                event=event.model_dump_json(exclude={"id", "timestamp", "address", "type"}),
            )

        return super().propagate(event)

    @override
    def get_system(self, address: str | DynamicAddress | None = None) -> System | None:
        return self.__root.get_system(address)

    @override
    def get_systems(
        self,
        filter: SystemFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[SystemFilterArgs],
    ) -> SystemGroup:
        return self.__root.get_systems(filter, inclusive=True, **kwargs)

    async def hash_password(self, password: str) -> PasswordHash:
        return await self.__database.hash_password(password)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        return await self.__database.verify_password(password, hash)

    async def reload(self, config: Config | None = None) -> Config:
        """
        Reload the engine's configuration. An optional `config` object can be provided directly to
        reload from. If omitted, the configuration will be reloaded from the engine's configuration
        file path.
        """
        if self.__reloading.is_set():
            raise Failure(ReloadAlreadyActiveError)

        if config is not None:
            self.log.info("Queueing reload of provided configuration...")
            self.__reloading.set()
            self.__reloaded_config = config
            return config

        if self.__config_path is None:
            self.log.warning("No configuration path provided, ignoring reload.")
            return self.config

        self.log.info(f"Reloading configuration from '{self.__config_path}'...")
        match await Config.load(self.__config_path, log=self.log):
            case Ok(config):
                self.log.info("Configuration parsed successfully, queueing reload...")
                self.__reloading.set()
                self.__reloaded_config = config
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

        if self.__reloaded_config is None:
            self.log.warning("No queued configuration was found, ignoring reload.")
            return

        self.__config = self.__reloaded_config

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
                    running = self.get_systems(running=True)
                    await self.__root.stop()
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

    async def __load_systems(self) -> None:
        await self.__node_sync__()
        await self.__load_system(Address.root())

    async def __load_system(self, address: Address) -> System | None:
        if address.is_root:
            config = self.config
        else:
            config = self.config.get_system(address)
            if config is None:
                return None

        system = self.get_system(address)

        if system is None:
            try:
                system = System.from_config(config)
                if address.is_root:
                    self.root = system
                    assert system.engine is self
                    assert system.database is self.database
                else:
                    parent = self.get_system(address.parent)
                    if parent is not None:
                        parent.add(system)

            except Exception:
                self.log.error(f"Failed to load '{address}': {traceback.format_exc()}")
                return None

        await system.__node_sync__()
        self.log.info(f"Loaded '{address}' with component type {strify(type(system.component))}.")

        for child in config.subsystems:
            await self.__load_system(address / child.name)

        return system

    async def __execute_actions(self, actions: Sequence[Action]) -> None:
        running = [other.address for other in self.get_systems() if other.running]
        for action in actions:
            system = self.get_system(action.address)

            if action.type == ActionType.REMOVE:
                if system is not None:
                    self.log.info(f"Removing '{action.address}'...")
                    await system.stop()
                    system.remove()
                    self.log.info(f"Removed '{action.address}'.")
            else:
                if action.type == ActionType.CREATE:
                    if system is None:
                        self.log.info(f"Creating '{action.address}'...")
                        await self.__load_system(action.address)
                        self.log.info(f"Created '{action.address}'.")
                elif action.type == ActionType.RECREATE:
                    if system is not None:
                        self.log.info(f"Recreating '{action.address}'...")
                        await system.stop()
                        system.remove()
                        await self.__load_system(action.address)
                        self.log.info(f"Recreated '{action.address}'.")

        for address in running:
            system = self.get_system(address)
            if system is not None and not system.running:
                self.log.info(f"Starting '{address}'...")
                system.start()

        created = [
            action
            for action in actions
            if action.type == ActionType.CREATE and self.get_node(action.address) is not None
        ]
        recreated = [
            action
            for action in actions
            if action.type == ActionType.RECREATE and self.get_node(action.address) is not None
        ]
        removed = [
            action
            for action in actions
            if action.type == ActionType.REMOVE and self.get_node(action.address) is None
        ]

        if created:
            self.log.info(f"{len(created)} systems(s) created.")
        if recreated:
            self.log.info(f"{len(recreated)} systems(s) reloaded.")
        if removed:
            self.log.info(f"{len(removed)} systems(s) removed.")

    def __get_component_reload_actions(self) -> list[Action]:
        return self.__get_component_reload_actions_for(Address.root())

    def __get_component_reload_actions_for(self, address: Address) -> list[Action]:
        config = self.config.get_system(address)

        component = self.get_system(address)
        if component is None and config is not None:
            return [Action(type=ActionType.CREATE, address=address)]
        if component is not None and config is None:
            return [Action(type=ActionType.REMOVE, address=address)]
        if component is None and config is None:
            return []

        assert component is not None
        assert config is not None

        include = {"name", "cls_path", "class", "arguments"}
        old = (
            {} if component.__config__ is None else component.__config__.model_dump(include=include)
        )
        new = config.model_dump(include=include)

        if old != new:
            return [Action(type=ActionType.RECREATE, address=address)]

        actions: list[Action] = []
        children = uniquify(
            [child.address for child in component.subsystems]
            + [component.address / child.name for child in config.subsystems]
        )

        for child in children:
            actions.extend(self.__get_component_reload_actions_for(child))

        return actions

    def __create_server(self) -> Server | None:
        socket: Path | None = None
        if self.__config.server.socket is not None:
            socket = self.__config.server.socket
        elif self.__config_path is not None:
            project = Project(self.__config_path, self.__config)
            socket = project.socket_path
        elif self.__config.server.port is None:
            return None

        config = ServerInternalConfig()
        config.loglevel = "CRITICAL"

        # SSL / HTTPS
        ssl = self.__config.server.ssl or ServerSSLConfig()
        config.keyfile = str(ssl.key) if ssl.key is not None else None
        config.keyfile_password = ssl.key_password
        config.certfile = str(ssl.cert) if ssl.cert is not None else None
        config.ca_certs = str(ssl.ca_certs) if ssl.ca_certs is not None else None

        bind: list[str] = []
        insecure_bind: list[str] = []

        if self.__config.server.port is not None:
            bind.append(f"{self.__config.server.host}:{self.__config.server.port}")
        if socket is not None:
            if config.ssl_enabled:
                insecure_bind.append(f"unix:{socket}")
            else:
                bind.append(f"unix:{socket}")

        config.bind = bind
        config.insecure_bind = insecure_bind

        return Server(config, App(self))

    def __start_server(self) -> Server | None:
        if self.__server is None:
            self.__server = self.__create_server()

        if self.__server is not None and not self.__server.running:
            bind = [*self.__server.config.bind, *self.__server.config.insecure_bind]
            self.log.info(f"Listening on {bind}...")
            self.__server.start(on_exception=self.__on_server_exception)

        return self.__server

    async def __stop_server(self) -> None:
        if self.__server is not None:
            bind = [*self.__server.config.bind, *self.__server.config.insecure_bind]
            self.log.info(f"Removing listeners from {bind}...")
            await self.__server.stop()
            self.__server = None

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.log.error(
            f"An exception occurred while running server on {server.config.bind}: {exception}"
        )
