from __future__ import annotations

import os
import signal
import sys
import traceback
from asyncio import Event
from enum import Enum
from logging import Logger
from queue import Empty, Queue
from typing import Any

import anyio
from anyio import CancelScope
from pydantic import BaseModel

from .config import Config, UnitConfig
from .errors import ReloadAlreadyActiveError, ReloadConfigInvalidError, ReloadError
from .internal import logs
from .internal.config import load_config
from .internal.database.manager import DatabaseManager
from .internal.server import Server, ServerEngineProtocol
from .internal.tasks import Tasklet
from .internal.unit import UnitContext, UnitHandle
from .internal.utilities import unreachable, use_signal_handler
from .path import UnitPath
from .result import Fail, Ok, Result


class UnitSyncActionKind(str, Enum):
    START = "start"
    RELOAD = "reload"
    REMOVE = "remove"


class UnitSyncAction(BaseModel):
    kind: UnitSyncActionKind
    path: UnitPath


class Engine(Tasklet, ServerEngineProtocol):
    def __init__(self, config: Config) -> None:
        self._config = config
        self._config_queue: Queue[Config] = Queue()
        self._server: Server | None = None
        self._database = DatabaseManager.create(self._config.database)
        self._units: dict[UnitPath, UnitHandle] = {}
        self._reloading = Event()

    @property
    def logger(self) -> Logger:
        return logs.get("engine")

    @property
    def config_path(self) -> str | None:
        return self._config.path

    @property
    def config_directory(self) -> str | None:
        if self._config.path:
            return os.path.dirname(self._config.path)

        return None

    @property
    def config(self) -> Config:
        return self._config

    async def reload(self) -> Result[Config, ReloadError]:
        if self._reloading.is_set():
            return Fail(ReloadAlreadyActiveError())

        source: str | Config

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

    async def _tasklet_run(self) -> None:
        if not await load_config(self._config, logger=self.logger):
            self.logger.error("Initial configuration check failed. Exiting...")
            return

        try:
            if self.config_directory and self.config_directory not in sys.path:
                sys.path.append(self.config_directory)

            exiting = Event()
            started = False

            while not exiting.is_set():
                if started:
                    await self._reloading.wait()
                    await self._reload()

                async def process_reload(cancel: CancelScope) -> None:
                    await self._reloading.wait()
                    cancel.cancel()

                def handle_exit_signal(*args: Any) -> None:
                    exiting.set()
                    group.cancel_scope.cancel()

                with use_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                    async with anyio.create_task_group() as group:
                        try:
                            group.start_soon(process_reload, group.cancel_scope)

                            await self._sync_units()
                            await self._start_server()
                        finally:
                            started = True
                            self._reloading.clear()

            self.logger.info("Exit signal received, stopping...")
        except KeyboardInterrupt:
            self.logger.info("Exit signal received, stopping...")
            await self.stop()
            raise

    async def _tasklet_stop(self) -> None:
        await self._stop_server()
        await self._stop_units()
        await self._database.dispose()

    async def _reload(self) -> None:
        self.logger.info("Reloading...")
        config_previous = self._config

        try:
            self._config = self._config_queue.get()
        except Empty:
            pass

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
                self._database = DatabaseManager.create(self._config.database)
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
            self._server = Server(self._config.server, self)
        if not self._server.running:
            self.logger.info("Starting server...")
            self._server.start()

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
        configs: dict[UnitPath, UnitConfig] = {
            UnitPath.create(current.name): current for current in self._config.units
        }

        actions = self._get_unit_sync_actions()

        for action in actions:
            unit = self._units.get(action.path)

            if action.kind == UnitSyncActionKind.REMOVE:
                if unit:
                    self.logger.info(f"Removing unit '{action.path}'...")
                    await unit.stop()
                    self._units.pop(unit.path)
            else:
                if action.kind == UnitSyncActionKind.START:
                    if unit and unit.running:
                        continue

                    self.logger.info(f"Starting unit '{action.path}'...")
                elif action.kind == "reload":
                    if not unit:
                        continue

                    self.logger.info(f"Reloading unit '{action.path}'...")
                    await unit.stop()
                    self._units.pop(unit.path)

                if config := configs.get(action.path):
                    id = await self._database.entities.get_unit_id(action.path)
                    context = UnitContext(
                        id=id,
                        path=action.path,
                        connections=config.connections,
                        database=self._config.database,
                        config=config,
                    )

                    unit = UnitHandle(context)
                    self._units[action.path] = unit
                    unit.start()

        started = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.START and action.path in self._units
        ]
        reloaded = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.RELOAD and action.path in self._units
        ]
        removed = [
            action
            for action in actions
            if action.kind == UnitSyncActionKind.REMOVE and action.path not in self._units
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
                self.logger.info(f"Stopping unit '{unit.path}'...")
                await unit.stop()

            self._units.pop(unit.path)

        self.logger.info("All units were stopped successfully.")

    def _get_unit_sync_actions(self) -> list[UnitSyncAction]:
        configs: dict[UnitPath, UnitConfig] = {
            UnitPath.create(current.name): current for current in self._config.units
        }
        units: dict[UnitPath, UnitHandle] = {
            current.path: current for current in self._units.values()
        }

        actions: list[UnitSyncAction] = []

        for path, config in configs.items():
            unit = units.get(path)
            if unit and unit.running and unit.config == config:
                continue

            if not unit or not unit.running:
                actions.append(UnitSyncAction(path=path, kind=UnitSyncActionKind.START))
            elif unit.config != config:
                actions.append(UnitSyncAction(path=path, kind=UnitSyncActionKind.RELOAD))

        for path, unit in self._units.items():
            if path not in configs:
                actions.append(UnitSyncAction(path=path, kind=UnitSyncActionKind.REMOVE))

        return actions

    def _on_unit_completed(self, unit: UnitHandle) -> None:
        self.logger.info(f"Unit '{unit.path}' completed execution.")
        self._units.pop(unit.path)

    def _on_unit_exception(self, unit: UnitHandle, exception: BaseException) -> None:
        self.logger.error(
            f"An exception occurred in unit '{unit.path}': {traceback.format_exception(exception)}"
        )
        self._units.pop(unit.path)
