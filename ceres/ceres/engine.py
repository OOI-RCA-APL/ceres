import asyncio
import signal
import sys
import traceback
from asyncio import FIRST_COMPLETED, Event
from enum import Enum
from logging import Logger
from pathlib import Path
from queue import Empty, Queue
from typing import Any, final

from .address import ComponentAddress, LocalComponentAddress, UnitAddress
from .component import ProcedureKind
from .config import Config, UnitConfig
from .data import ImmutableDataObject, jsonify
from .errors import (
    ProcedureError,
    ReloadAlreadyActiveError,
    ReloadConfigInvalidError,
    ReloadError,
)
from .exceptions import (
    StartupConfigCheckFailedException,
    StartupDatabaseInitFailedException,
)
from .internal import logs
from .internal.config import load_config
from .internal.database.manager import DatabaseManager
from .internal.server import Server
from .internal.tasklet import Tasklet
from .internal.unit import UnitContext, UnitHandle
from .internal.utilities import temporary_signal_handler, unreachable
from .result import Fail, Ok, Result


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
        self._config = config
        self._config_queue: Queue[Config] = Queue()
        self._server: Server | None = None
        self._database = DatabaseManager(self._config.database)
        self._units: dict[UnitAddress, UnitHandle] = {}
        self._reloading = Event()

    @property
    def logger(self) -> Logger:
        return logs.get("engine")

    @property
    def config_path(self) -> Path | None:
        return self._config.path

    @property
    def config_directory(self) -> Path | None:
        if self._config.path:
            return self._config.path.parent

        return None

    @property
    def config(self) -> Config:
        return self._config

    async def reload(self) -> Result[Config, ReloadError]:
        if self._reloading.is_set():
            return Fail(ReloadAlreadyActiveError())

        source: Path | Config

        if self.config_path:
            self.logger.info(f"Reloading configuration from '{self.config_path}'...")
            source = self.config_path
        else:
            self.logger.info("No configuration path is set. Reloading current configuration...")
            source = self._config

        match await load_config(source, logger=self.logger):
            case Ok(config):
                self.logger.info("Queueing reload...")
                self._reloading.set()
                self._config_queue.put(config)
                return Ok(config)
            case Fail(errors):
                self.logger.error("Reload failed, found errors in configuration.")
                return Fail(ReloadConfigInvalidError(errors=errors))

        unreachable()

    async def __run__(self) -> None:
        match await load_config(self._config, logger=self.logger):
            case Ok():
                pass
            case Fail() as fail:
                raise StartupConfigCheckFailedException(
                    f"initial configuration check failed: {jsonify(fail, indent=2)}"
                )

        if not await self._database.tables():
            self.logger.info("Database appears empty, initializing database...")
            try:
                await self._database.init()
                self.logger.info("Database initialized successfully.")
            except Exception as exception:
                self.logger.error("Database initialization failed.")
                raise StartupDatabaseInitFailedException(str(exception))

        try:
            if self.config_directory and str(self.config_directory) not in sys.path:
                sys.path.append(str(self.config_directory))

            exiting = Event()
            started = False

            while not exiting.is_set():
                if started:
                    await self._reloading.wait()
                    await self._reload()

                def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
                    exiting.set()

                with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                    await self._sync_units()
                    await self._start_server()

                    started = True
                    self._reloading.clear()

                    tasks = [
                        asyncio.create_task(self._reloading.wait(), name="reload-wait"),
                        asyncio.create_task(exiting.wait(), name="exit-wait"),
                    ]

                    try:
                        await asyncio.wait(tasks, return_when=FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            task.cancel()

            self.logger.info("Exit signal received, stopping...")
        except KeyboardInterrupt:
            self.logger.info("Exit signal received, stopping...")
            raise

    async def __stop__(self) -> None:
        await self._stop_server()
        await self._stop_units()
        await self._database.dispose()

    async def call(
        self,
        address: ComponentAddress,
        kind: ProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (unit := self._units.get(UnitAddress(address.unit))) is None:
            raise ValueError(f"unit at {address} does not exist")

        return await unit.call(
            LocalComponentAddress(address.name),
            kind,
            procedure,
            input,
        )

    async def _reload(self) -> None:
        self.logger.info("Reloading...")
        config_previous = self._config

        try:
            self._config = self._config_queue.get_nowait()
        except Empty:
            self.logger.warning("No new configuration was found, ignoring reload.")
            return

        if self._config == config_previous:
            self.logger.info("Configuration was not modified. Nothing to reload.")
            return

        if self._config.server != config_previous.server:
            self.logger.info("Server configuration modified, reloading server...")
            try:
                await self._reload_server()
            except Exception:
                self.logger.error(
                    f"An issue occurred while reloading the server: {traceback.format_exc()}"
                )

        if self._config.database != config_previous.database:
            self.logger.info("Database configuration modified, reloading all units and database...")
            try:
                await self._stop_units()
                await self._database.dispose()
                self._database = DatabaseManager(self._config.database)
            except Exception:
                self.logger.error(
                    f"An issue occurred while reloading units and database: {traceback.format_exc()}"
                )

        if self._get_unit_sync_actions():
            self.logger.info("Syncing units...")
            try:
                await self._sync_units()
            except Exception:
                self.logger.error(
                    f"An issue occurred while syncing units: {traceback.format_exc()}"
                )

        self.logger.info("Reload completed.")

    async def _start_server(self) -> None:
        if not self._server:
            self._server = Server(
                self._config.server,
                self,
                self._database,
            )

        if not self._server.running:
            self.logger.info("Starting server...")
            self._server.start(
                on_completed=self._on_server_completed,
                on_exception=self._on_server_exception,
            )

    async def _stop_server(self) -> None:
        if self._server:
            if self._server.running:
                self.logger.info("Stopping server...")
                await self._server.stop()

        self._server = None

    async def _reload_server(self) -> None:
        await self._stop_server()
        await self._start_server()

    async def _sync_units(self) -> None:
        unit_configs: dict[UnitAddress, UnitConfig] = {
            UnitAddress(current.name): current for current in self._config.units
        }

        actions = self._get_unit_sync_actions()

        for action in actions:
            unit = self._units.get(action.address)

            if action.kind == UnitSyncActionKind.REMOVE:
                if unit:
                    self.logger.info(f"Removing unit '{action.address}'...")
                    await unit.stop()
                    self._units.pop(unit.address, None)
            else:
                if action.kind == UnitSyncActionKind.START:
                    if unit and unit.running:
                        continue

                    self.logger.info(f"Starting unit '{action.address}'...")
                elif action.kind == UnitSyncActionKind.RELOAD:
                    if not unit:
                        continue

                    self.logger.info(f"Reloading unit '{action.address}'...")
                    await unit.stop()
                    self._units.pop(unit.address, None)

                if unit_config := unit_configs.get(action.address):
                    id = await self._database.entities.get_address_id(action.address)
                    context = UnitContext(
                        id=id,
                        address=action.address,
                        root_config=self._config,
                        unit_config=unit_config,
                    )

                    unit = UnitHandle(context)
                    self._units[action.address] = unit
                    unit.start(
                        on_completed=self._on_unit_completed,
                        on_exception=self._on_unit_exception,
                    )

        started = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.START and action.address in self._units
        ]
        reloaded = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.RELOAD and action.address in self._units
        ]
        removed = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.REMOVE and action.address not in self._units
        ]

        if started:
            self.logger.info(f"{len(started)} unit(s) started.")
        if reloaded:
            self.logger.info(f"{len(reloaded)} unit(s) reloaded.")
        if removed:
            self.logger.info(f"{len(removed)} unit(s) removed.")

    async def _stop_units(self) -> None:
        if not self._units:
            return

        self.logger.info("Stopping all units...")

        for unit in [*self._units.values()]:
            if unit.instance:
                self.logger.info(f"Stopping unit '{unit.address}'...")
                await unit.stop()

            self._units.pop(unit.address, None)

        self.logger.info("All units were stopped successfully.")

    def _get_unit_sync_actions(self) -> list[UnitSyncAction]:
        configs: dict[UnitAddress, UnitConfig] = {
            UnitAddress(current.name): current for current in self._config.units
        }
        units: dict[UnitAddress, UnitHandle] = {
            current.address: current for current in self._units.values()
        }

        actions: list[UnitSyncAction] = []

        for unit_address, unit_config in configs.items():
            unit = units.get(unit_address)
            if unit and unit.running and unit.config == unit_config:
                continue

            if not unit or not unit.running:
                actions.append(UnitSyncAction(address=unit_address, kind=UnitSyncActionKind.START))
            elif unit.config != unit_config:
                actions.append(UnitSyncAction(address=unit_address, kind=UnitSyncActionKind.RELOAD))

        for unit_address, unit in self._units.items():
            if unit_address not in configs:
                actions.append(UnitSyncAction(address=unit_address, kind=UnitSyncActionKind.REMOVE))

        return actions

    def _on_server_completed(self, server: Server) -> None:
        self.logger.info(f"Server completed execution.")

    def _on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in server: {traceback.format_exception(exception)}"
        )

    def _on_unit_completed(self, unit: UnitHandle) -> None:
        self.logger.info(f"Unit '{unit.address}' completed execution.")
        self._units.pop(unit.address, None)

    def _on_unit_exception(self, unit: UnitHandle, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in unit '{unit.address}': {traceback.format_exception(exception)}"
        )
        self._units.pop(unit.address, None)
