import os
import signal
import sys
import traceback
from asyncio import Event
from logging import Logger
from queue import Empty, Queue
from typing import Any, Dict, Optional

import anyio
from anyio import CancelScope

from . import logs
from .config import DatabaseConfig, EngineConfig
from .database import Database
from .exceptions import ConfigException, ReloadAlreadyActiveException
from .internal import use_signal_handler
from .path import UnitPath
from .server import Server, ServerEngineProtocol
from .tasks import Tasklet
from .unit import UnitContext, UnitHandle


class Engine(Tasklet, ServerEngineProtocol):
    def __init__(self, config_path: str) -> None:
        self._config = EngineConfig.load(config_path)
        self._config_path = config_path
        self._config_queue: Queue[EngineConfig] = Queue()
        self._server: Optional[Server] = None
        self._database = Database(self._config.database)
        self._units: Dict[UnitPath, UnitHandle] = {}
        self._reloading = Event()

    @property
    def logger(self) -> Logger:
        return logs.get("engine")

    @property
    def config_path(self) -> str:
        return self._config_path

    @property
    def config_directory(self) -> str:
        return os.path.dirname(self._config_path)

    @property
    def config(self) -> EngineConfig:
        return self._config

    @property
    def server(self) -> Optional[Server]:
        return self._server

    @property
    def database(self) -> "Database":
        return self._database

    async def reload(self) -> None:
        if self._reloading.is_set():
            raise ReloadAlreadyActiveException("A reload is already is progress.")

        self.logger.info(f"Reloading configuration from '{self._config_path}'...")
        try:
            config = EngineConfig.load(self._config_path)
        except ConfigException as error:
            self.logger.error(error.message)
            self.logger.error("Reload failed, found errors in configuration.")
            raise

        if not await self._check_config(self._config):
            self.logger.error("Reload failed, configuration check was unsuccessful.")
            raise ConfigException("Configuration check failed.")

        self.logger.info("Queueing reload...")
        self._reloading.set()
        self._config_queue.put(config)
        return None

    async def _tasklet_run(self) -> None:
        if not await self._check_config(self._config):
            self.logger.error("Initial configuration check failed. Exiting...")
            return

        try:
            if self.config_directory not in sys.path:
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

                            await self._create_units()
                            await self._start_units()
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
        self.logger.info("Reloading configuration...")
        config_previous = self._config

        try:
            self._config = self._config_queue.get()
        except Empty:
            pass

        if self._config == config_previous:
            self.logger.info("Configuration was not modified, doing nothing.")
        else:
            if self._config.server != config_previous.server:
                self.logger.info("Server configuration modified, reloading server...")
                try:
                    await self._reload_server()
                except Exception:
                    self.logger.error(
                        f"An issue occurred while reloading the server: {traceback.format_exc()}"
                    )

            if self._config.database != config_previous.database:
                self.logger.info("Database configuration modified, reloading units and database...")
                try:
                    await self._stop_units()
                    await self._database.dispose()
                    self._database = Database(self._config.database)
                except Exception:
                    self.logger.error(
                        f"An issue occurred while reloading units and database: {traceback.format_exc()}"
                    )
            elif self._config.units != config_previous.units:
                self.logger.info("Unit configuration modified, reloading units...")
                try:
                    await self._stop_units()
                except Exception:
                    self.logger.error(
                        f"An issue occurred while reloading units: {traceback.format_exc()}"
                    )

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

    async def _create_units(self) -> None:
        self._units.clear()

        for unit in self._config.units:
            path = UnitPath.create(unit.name)
            id = await self._database.entities.get_unit_id(path)

            context = UnitContext(
                id=id,
                path=path,
                connections=unit.connections,
                database=self._config.database,
            )

            self._units[path] = UnitHandle(context)

    async def _start_units(self) -> None:
        for unit in self._units.values():
            self.logger.info(f"Starting unit '{unit.path}'...")
            unit.start(
                on_completed=self._on_unit_completed,
                on_exception=self._on_unit_exception,
            )

    async def _stop_units(self) -> None:
        if not self._units:
            return

        self.logger.info("Stopping all units...")

        for unit in self._units.values():
            if unit.instance:
                self.logger.info(f"Stopping unit '{unit.path}'...")
                await unit.stop()

        self._units = {}
        self.logger.info("All units were stopped successfully.")

    def _on_unit_completed(self, unit: UnitHandle) -> None:
        print(f"Unit '{unit.path}' completed execution.")

    def _on_unit_exception(self, unit: UnitHandle, exception: BaseException) -> None:
        print(f"An exception occurred in unit '{unit.path}': ", end="")
        traceback.print_exception(exception)

    async def _wait_for_database(
        self,
        config: DatabaseConfig,
        attempts: Optional[int] = None,
    ) -> bool:
        if attempts is not None and attempts <= 0:
            attempts = 1

        info = config.copy(update={"password": "<OMITTED>"}).json()

        self.logger.info(f"Using database configuration: {info}")

        attempt = 0

        while True:
            try:
                database = Database(config)
                async with database.connect():
                    self.logger.info("Connected to database successfully.")
                    return True
            except Exception as exception:
                if attempts is None or attempt < attempts:
                    self.logger.info("Failed to connect to database. Retrying...")
                    await database.dispose()
                    await anyio.sleep(1)
                    attempt += 1
                    continue

                self.logger.info(f"Failed to connect to database: {exception}")
                await database.dispose()
                return False
            finally:
                await database.dispose()

    async def _check_config(self, config: EngineConfig, wait: bool = False) -> bool:
        if config.database:
            self.logger.info("Database configuration found, verifying it's reachable...")
            await self._wait_for_database(config.database, attempts=None if wait else 3)

        self.logger.info("Configuration passed all checks.")
        return True
