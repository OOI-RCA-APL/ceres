import asyncio
import traceback
from asyncio import FIRST_COMPLETED, Event
from enum import Enum
from logging import Logger
from pathlib import Path
from queue import Empty, Queue
from typing import final

from .address import GlobalComponentAddress, UnitAddress, caddr
from .alert import Alert
from .config import ConcurrencyKind, Config, UnitConfig
from .data import ImmutableDataObject, jsonify
from .database import Database
from .datetime import utc
from .errors import (
    ProcedureError,
    ProcedureUnitDoesNotExistError,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
    ReloadError,
)
from .exceptions import EngineConfigCheckFailedException, EngineDatabaseInitException
from .internal import logs
from .internal.app import App
from .internal.config import load_config
from .internal.server import Server
from .internal.tasklet import Tasklet
from .internal.unit import Subscription, UnitHandle
from .message import Message
from .procedure import CallableProcedureKind, SubscribableProcedureKind
from .result import Fail, Ok, Result
from .stream import Stream, StreamView
from .unit import UnitContext


class UnitSyncActionKind(str, Enum):
    START = "start"
    RELOAD = "reload"
    REMOVE = "remove"


class UnitSyncAction(ImmutableDataObject):
    kind: UnitSyncActionKind
    address: UnitAddress


@final
class Engine(Tasklet):
    def __init__(self, config: Config) -> None:
        self.__config = config
        self.__config_queue: Queue[Config] = Queue()

        if self.__config.server:
            self.__server = Server(App(self), self.__config.server)
        else:
            self.__server = None

        self.__database = Database(self.__config.database)
        self.__unit_handles: dict[UnitAddress, UnitHandle] = {}
        self.__reloading = Event()
        self.__message_stream: Stream[Message] = Stream()
        self.__alert_stream: Stream[Alert] = Stream()

    @property
    def logger(self) -> Logger:
        return logs.get("engine")

    @property
    def config_path(self) -> Path | None:
        return self.__config.path

    @property
    def config_directory(self) -> Path | None:
        if self.__config.path:
            return self.__config.path.parent

        return None

    @property
    def config(self) -> Config:
        return self.__config

    @property
    def database(self) -> Database:
        return self.__database

    @property
    def message_stream(self) -> StreamView[Message]:
        return self.__message_stream.view()

    @property
    def alert_stream(self) -> StreamView[Alert]:
        return self.__alert_stream.view()

    async def reload(self) -> Result[Config, ReloadError]:
        if self.__reloading.is_set():
            return Fail(ReloadAlreadyActiveError())

        source: Path | Config

        if self.config_path:
            self.logger.info(f"Reloading configuration from '{self.config_path}'...")
            source = self.config_path
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

    async def __run__(self) -> None:
        match await load_config(self.__config, logger=self.logger):
            case Ok():
                pass
            case Fail() as fail:
                raise EngineConfigCheckFailedException(
                    f"initial configuration check failed: {jsonify(fail, indent=2)}"
                )

        if not await self.__database.tables():
            self.logger.info("Database appears empty, initializing database...")
            try:
                await self.__database.init()
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
                asyncio.create_task(self.__process(), name="process"),
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

    async def __process(self) -> None:
        while True:
            try:
                await asyncio.gather(
                    self.__process_messages(),
                    self.__process_alerts(),
                )
            except Exception:
                self.logger.error(
                    f"An exception occurred in engine process: {traceback.format_exc()}"
                )

    async def __process_messages(self) -> None:
        cursor = utc()

        while True:
            await asyncio.sleep(0.1)
            messages = await self.database.entities.get_messages(
                where=lambda message: message.timestamp > cursor,
                order_by=lambda message: message.timestamp.desc(),
            )

            if not messages:
                continue

            for message in reversed(messages):
                self.__message_stream.put(message)

            cursor = messages[0].timestamp

    async def __process_alerts(self) -> None:
        cursor = utc()

        while True:
            await asyncio.sleep(0.1)
            alerts = await self.database.entities.get_alerts(
                where=lambda message: message.timestamp > cursor,
                order_by=lambda message: message.timestamp.desc(),
            )

            if not alerts:
                continue

            for alert in reversed(alerts):
                self.__alert_stream.put(alert)

            cursor = alerts[0].timestamp

    async def __stop__(self) -> None:
        async def stop() -> None:
            await self.__stop_server()
            await self.__stop_units()
            await self.__database.dispose()

        await asyncio.shield(asyncio.create_task(stop()))

    async def call(
        self,
        address: GlobalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (unit_handle := self.__unit_handles.get(UnitAddress(address.unit))) is None:
            raise ValueError(f"unit at {address} does not exist")

        return await unit_handle.call(
            caddr(address.component),
            kind,
            procedure,
            input,
        )

    async def subscribe(
        self,
        address: GlobalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[Subscription, ProcedureError]:
        if (unit_handle := self.__unit_handles.get(UnitAddress(address.unit))) is None:
            return Fail(ProcedureUnitDoesNotExistError())

        return await unit_handle.subscribe(
            caddr(address.name),
            kind,
            procedure,
            input,
        )

    async def unsubscribe(
        self,
        address: GlobalComponentAddress,
        subscription: Subscription,
    ) -> None:
        if (unit_handle := self.__unit_handles.get(UnitAddress(address.unit))) is None:
            return

        await unit_handle.unsubscribe(subscription)

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
        unit_configs: dict[UnitAddress, UnitConfig] = {
            UnitAddress(current.name): current for current in self.__config.units
        }

        actions = self.__get_unit_sync_actions()

        for action in actions:
            unit_handle = self.__unit_handles.get(action.address)

            if action.kind == UnitSyncActionKind.REMOVE:
                if unit_handle:
                    self.logger.info(f"Removing unit '{action.address}'...")
                    await unit_handle.stop()
                    self.__unit_handles.pop(unit_handle.address, None)
            else:
                if action.kind == UnitSyncActionKind.START:
                    if unit_handle and unit_handle.running:
                        continue

                    self.logger.info(f"Starting unit '{action.address}'...")
                elif action.kind == UnitSyncActionKind.RELOAD:
                    if not unit_handle:
                        continue

                    self.logger.info(f"Reloading unit '{action.address}'...")
                    await unit_handle.stop()
                    self.__unit_handles.pop(unit_handle.address, None)

                if unit_config := unit_configs.get(action.address):
                    id = await self.__database.entities.get_address_id(action.address)
                    concurrency = unit_config.concurrency or self.__config.runtime.concurrency

                    match concurrency:
                        case ConcurrencyKind.THREAD:
                            # If the unit will be running in a thread, create a clone so it uses a
                            # separate event loop but the underlying syncronous SQLAlchemy engine is
                            # shared.
                            database = Database(self.__database)
                        case ConcurrencyKind.PROCESS:
                            # If the unit will be running in a process, let it create its own
                            # database client from the same configuration.
                            database = None

                    context = UnitContext(
                        id=id,
                        address=action.address,
                        root_config=self.__config,
                        unit_config=unit_config,
                        database=database,
                    )

                    unit_handle = UnitHandle(context)
                    self.__unit_handles[action.address] = unit_handle
                    unit_handle.start(
                        on_completed=self.__on_unit_completed,
                        on_exception=self.__on_unit_exception,
                    )

        started = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.START and action.address in self.__unit_handles
        ]
        reloaded = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.RELOAD and action.address in self.__unit_handles
        ]
        removed = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.REMOVE
            and action.address not in self.__unit_handles
        ]

        if started:
            self.logger.info(f"{len(started)} unit(s) started.")
        if reloaded:
            self.logger.info(f"{len(reloaded)} unit(s) reloaded.")
        if removed:
            self.logger.info(f"{len(removed)} unit(s) removed.")

    async def __stop_units(self) -> None:
        if not self.__unit_handles:
            return

        self.logger.info("Stopping all units...")

        async def stop(unit_handle: UnitHandle) -> None:
            if unit_handle.running:
                self.logger.info(f"Stopping unit '{unit_handle.address}'...")
                await unit_handle.stop()

            self.__unit_handles.pop(unit_handle.address, None)

        await asyncio.gather(*(stop(unit) for unit in self.__unit_handles.values()))

        self.logger.info("All units were stopped successfully.")

    def __get_unit_sync_actions(self) -> list[UnitSyncAction]:
        configs: dict[UnitAddress, UnitConfig] = {
            UnitAddress(current.name): current for current in self.__config.units
        }
        units: dict[UnitAddress, UnitHandle] = {
            current.address: current for current in self.__unit_handles.values()
        }

        actions: list[UnitSyncAction] = []

        for unit_address, unit_config in configs.items():
            unit_handle = units.get(unit_address)
            if unit_handle and unit_handle.running and unit_handle.config == unit_config:
                continue

            if not unit_handle or not unit_handle.running:
                actions.append(UnitSyncAction(address=unit_address, kind=UnitSyncActionKind.START))
            elif unit_handle.config != unit_config:
                actions.append(UnitSyncAction(address=unit_address, kind=UnitSyncActionKind.RELOAD))

        for unit_address, unit_handle in self.__unit_handles.items():
            if unit_address not in configs:
                actions.append(UnitSyncAction(address=unit_address, kind=UnitSyncActionKind.REMOVE))

        return actions

    def __on_server_completed(self, server: Server) -> None:
        self.logger.info(f"Server stopped.")

    def __on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in server: {traceback.format_exception(exception)}"
        )

    def __on_unit_completed(self, unit_handle: UnitHandle) -> None:
        self.logger.info(f"Unit '{unit_handle.address}' stopped.")
        self.__unit_handles.pop(unit_handle.address, None)

    def __on_unit_exception(self, unit_handle: UnitHandle, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in unit '{unit_handle.address}': {traceback.format_exception(exception)}"
        )
        self.__unit_handles.pop(unit_handle.address, None)
