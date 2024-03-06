import asyncio
import os
import traceback
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence, TypeVar

from aiotools.taskgroup import TaskGroup
from typing_extensions import Self, Unpack, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert, AlertUpdate
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
from ceres.filter import (
    AlertFilter,
    AlertFilterArgs,
    ComponentFilter,
    ComponentFilterArgs,
    LogEntryFilter,
    LogEntryFilterArgs,
    MessageFilter,
    MessageFilterArgs,
    UserFilter,
    UserFilterArgs,
)
from ceres.internal.app.main import App
from ceres.internal.project import Project
from ceres.internal.server import Server, ServerInternalConfig
from ceres.internal.utilities import sleep_forever, strify, uniquify
from ceres.logs import LogEntry, LogEntryUpdate
from ceres.message import Message, MessageUpdate
from ceres.object import Object
from ceres.result import Fail, Ok, Result
from ceres.user import User, UserCreate, UserUpdate

if TYPE_CHECKING:
    from ceres.component import Component, ComponentGroup
    from ceres.database.database import Database
else:
    Component = object
    ComponentGroup = object
    Database = object

_EventT = TypeVar("_EventT", bound=Event)


class ActionType(StrEnum):
    CREATE = "create"
    RECREATE = "recreate"
    REMOVE = "remove"


class Action(ImmutableDataObject):
    type: ActionType
    address: Address


class Engine(Object, kw_only=False):
    source: Path | Config | None

    def __post_init__(self) -> None:
        super().__post_init__()

        if self.source is None:
            self.__config = Config()
            self.__config_path = None
        elif isinstance(self.source, Path):
            self.__config_path = self.source
            match Config.read(self.source):
                case Ok(config):
                    self.__config = config
                case Fail(errors):
                    raise ValueError(str(errors))
        else:
            self.__config = self.source
            self.__config_path = None

        from ceres.database.database import Database

        self.__database = Database(self.__config.database)
        self.__reloading = AsyncEvent()
        self.__reloaded_config: Config | None = None
        self.__server: Server | None = None
        self.__root: Component | None = None

        if self.__config_path is not None:
            self.__project_directory = Directory(self.__config_path.parent)
        else:
            self.__project_directory = Directory(os.getcwd())

        self.__setup__()

    def __setup__(self) -> None:
        pass

    @property
    @override
    def __object_parent__(self) -> Object | None:
        return None

    @property
    @override
    def __object_descendants__(self) -> Iterable[Object]:
        return self.get_components()

    @property
    @override
    def __object_database__(self) -> Database:
        return self.__database

    @property
    @override
    def address(self) -> Address:
        return Address.engine()

    @property
    @override
    def root(self) -> Component | None:
        return self.__root

    @root.setter
    def root(self, root: Component) -> None:
        root = root.unref()
        self.__root = root
        self.__root.engine = self

    @property
    @override
    def engine(self) -> Self:
        return self

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

    @property
    def database(self) -> Database:
        return self.__database

    @override
    async def __run__(self) -> None:
        if self.local_directory is not None:
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

                self.__start_server()

                async def start_enabled() -> None:
                    await asyncio.sleep(0)
                    async with await self.__object_database__.init() as session:
                        for component in self.get_components():
                            await component.__object_sync__(session)
                            if component.enabled and not component.running:
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

        async with TaskGroup() as group:
            group.create_task(super().__run__())
            group.create_task(process())

    @override
    async def __stop__(self) -> None:
        self.emit(StoppingEvent)
        await self.__stop_server()
        if self.__root is not None:
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
        await self.__load_components()
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
    def get_component(self, address: str | DynamicAddress | None = None, /) -> Component | None:
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
    ) -> ComponentGroup:
        if self.__root is None:
            from ceres.component import ComponentGroup

            return ComponentGroup()

        return self.__root.get_components(filter, inclusive=True, **kwargs)

    async def hash_password(self, password: str) -> PasswordHash:
        return await self.__database.hash_password(password)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        return await self.__database.verify_password(password, hash)

    async def get_users(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> list[User]:
        """
        Get a list of users matching the given `filter`.
        """
        return await self.__database.get_users(filter, **kwargs)

    async def get_user(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> User | None:
        """
        Get a user matching the given `filter`.
        """
        return await self.__database.get_user(filter, **kwargs)

    async def count_users(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> int:
        """
        Count users matching the given `filter`.
        """
        return await self.__database.count_users(filter, **kwargs)

    async def create_user(self, data: UserCreate) -> User:
        """
        Create a new user in the database.
        """
        return await self.__database.create_user(data)

    async def update_users(self, filter: UserFilter, assign: UserUpdate) -> int:
        """
        Update users matching the given `filter`. Returns the number of users updated.
        """
        return await self.__database.update_users(filter, assign)

    async def update_user(self, filter: UserFilter, assign: UserUpdate) -> User | None:
        """
        Update a user matching the given `filter`. Returns the updated user, if found.
        """
        return await self.__database.update_user(filter, assign)

    async def delete_users(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> int:
        """
        Delete users matching the given `filter`. Returns the number of users deleted.
        """
        return await self.__database.delete_users(filter, **kwargs)

    async def delete_user(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> User | None:
        """
        Delete a user matching the given `filter`. Returns the deleted user, if found.
        """
        return await self.__database.delete_user(filter, **kwargs)

    async def count_messages(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> int:
        """
        Count messages matching the given `filter`.
        """
        return await self.__database.count_messages(filter, **kwargs)

    async def create_message(self, data: Message) -> Message:
        """
        Create a new message in the database.
        """
        return await self.__database.create_message(data)

    async def update_messages(self, filter: MessageFilter, assign: MessageUpdate) -> int:
        """
        Update messages matching the given `filter`. Returns the number of messages updated.
        """
        return await self.__database.update_messages(filter, assign)

    async def update_message(self, filter: MessageFilter, assign: MessageUpdate) -> Message | None:
        """
        Update a message matching the given `filter`. Returns the updated message, if found.
        """
        return await self.__database.update_message(filter, assign)

    async def delete_messages(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> int:
        """
        Delete messages matching the given `filter`.
        """
        return await self.__database.delete_messages(filter, **kwargs)

    async def delete_message(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        """
        Delete a message matching the given `filter`. Returns the deleted message, if found.
        """
        return await self.__database.delete_message(filter, **kwargs)

    async def count_alerts(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> int:
        """
        Count alerts matching the given `filter`.
        """
        return await self.__database.count_alerts(filter, **kwargs)

    async def create_alert(self, assign: Alert) -> Alert:
        """
        Create a new alert in the database.
        """
        return await self.__database.create_alert(assign)

    async def update_alerts(self, filter: AlertFilter, assign: AlertUpdate) -> int:
        """
        Update alerts matching the given `filter`. Returns the number of alerts updated.
        """
        return await self.__database.update_alerts(filter, assign)

    async def update_alert(self, filter: AlertFilter, assign: AlertUpdate) -> Alert | None:
        """
        Update an alert matching the given `filter`. Returns the updated alert, if found.
        """
        return await self.__database.update_alert(filter, assign)

    async def delete_alerts(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> int:
        """
        Delete alerts matching the given `filter`. Returns the number of alerts deleted.
        """
        return await self.__database.delete_alerts(filter, **kwargs)

    async def delete_alert(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        """
        Delete an alert matching the given `filter`. Returns the deleted alert, if found.
        """
        return await self.__database.delete_alert(filter, **kwargs)

    async def count_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> int:
        """
        Count log entries matching the given `filter`.
        """
        return await self.__database.count_log_entries(filter, **kwargs)

    async def create_log_entry(self, assign: LogEntry) -> LogEntry:
        """
        Create a new log entry in the database.
        """
        return await self.__database.create_log_entry(assign)

    async def update_log_entries(self, filter: LogEntryFilter, assign: LogEntryUpdate) -> int:
        """
        Update log entries matching the given `filter`. Returns the number of log entries updated.
        """
        return await self.__database.update_log_entries(filter, assign)

    async def update_log_entry(
        self,
        filter: LogEntryFilter,
        assign: LogEntryUpdate,
    ) -> LogEntry | None:
        """
        Update a log entry matching the given `filter`. Returns the updated log entry, if found.
        """
        return await self.__database.update_log_entry(filter, assign)

    async def delete_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> int:
        """
        Delete log entries matching the given `filter`. Returns the number of log entries deleted.
        """
        return await self.__database.delete_log_entries(filter, **kwargs)

    async def delete_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        """
        Delete a log entry matching the given `filter`. Returns the deleted log entry, if found.
        """
        return await self.__database.delete_log_entry(filter, **kwargs)

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
        if not await self.__object_database__.initialized():
            self.log.info("Database appears empty, initializing database...")
            try:
                await self.__object_database__.init()
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
                self.log.info(
                    "Database configuration modified, reloading database and components..."
                )
                try:
                    running = self.get_components(running=True)
                    if self.__root is not None:
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
                    assert component.engine is self
                    assert component.__object_database__ is self.__object_database__
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

            if action.type == ActionType.REMOVE:
                if component is not None:
                    self.log.info(f"Removing '{action.address}'...")
                    await component.stop()
                    component.remove_component()
                    self.log.info(f"Removed '{action.address}'.")
            else:
                if action.type == ActionType.CREATE:
                    if component is None:
                        self.log.info(f"Creating '{action.address}'...")
                        await self.__load_component(action.address)
                        self.log.info(f"Created '{action.address}'.")
                elif action.type == ActionType.RECREATE:
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
            if action.type == ActionType.CREATE and self.get_component(action.address) is not None
        ]
        recreated = [
            action
            for action in actions
            if action.type == ActionType.RECREATE and self.get_component(action.address) is not None
        ]
        removed = [
            action
            for action in actions
            if action.type == ActionType.REMOVE and self.get_component(action.address) is None
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

        component = self.get_component(address)
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
            [child.address for child in component.components]
            + [component.address / child.name for child in config.components]
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
