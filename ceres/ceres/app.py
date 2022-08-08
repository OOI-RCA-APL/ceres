import os
import signal
import sys
from asyncio.queues import Queue as AsyncQueue
from logging import Logger
from typing import TYPE_CHECKING, Optional, Type

import anyio
from anyio import CancelScope, Event

from . import logs
from .config import Config, ConfigException, DatabaseConfig
from .database import Database
from .tasks import Tasklet, ensure_event_loop

if TYPE_CHECKING:
    from .server import Server
    from .supervisor import Supervisor


class App(Tasklet):
    def __init__(
        self,
        path: str,
        server_cls: Type["Server"],
        supervisor_cls: Type["Supervisor"],
    ) -> None:
        self._path = path
        self._server_cls = server_cls
        self._supervisor_cls = supervisor_cls
        self._config = Config()
        self._config_next: Optional[Config] = self._config
        self._config_queue: AsyncQueue[Config] = AsyncQueue()
        self._server: Optional["Server"] = None
        self._supervisor: Optional["Supervisor"] = None

    @property
    def logger(self) -> Logger:
        return logs.get("app")

    @property
    def path(self) -> str:
        return self._path

    @property
    def server(self) -> Optional["Server"]:
        return self._server

    @property
    def supervisor(self) -> "Supervisor":
        if self._supervisor is None:
            self._supervisor = self._supervisor_cls(self._config, self)

        return self._supervisor

    async def execute(self) -> None:
        self.logger.info(f"Loading configuration from '{self._path}'...")

        try:
            config = Config.load(self._path)
        except ConfigException as error:
            self.logger.error(error.message)
            return

        if not await self._check_config(config):
            self.logger.error("Initial configuration check failed. Exiting...")
            return

        self._config = config
        self._config_next = config

        sys.path.append(os.path.dirname(self._path))

        exit = Event()

        async def process_exit() -> None:
            await exit.wait()
            self.logger.info("Exit event received.")
            self._config_next = None
            await self.stop()

        async def process_stop(cancel: CancelScope) -> None:
            await self.join()
            self._config_next = None
            cancel.cancel()

        async def process_reload(cancel: CancelScope) -> None:
            if exit.is_set():
                self._config_next = None

            if not self._config_next:
                return

            config = await self._config_queue.get()
            self.logger.info("Received new configuration...")

            if await self._check_config(config):
                self._config_next = config
                cancel.cancel()

        async def process(config: Config) -> None:
            self.logger.info("Applying new configuration...")
            self._config = config
            self._server = (
                self._server_cls(self._config.server, self) if self._config.server else None
            )
            self._supervisor = self._supervisor_cls(self._config, self)

            async with anyio.create_task_group() as group:
                if self._server:
                    group.start_soon(self._server.serve)
                if self._supervisor:
                    self._supervisor.start()
                    group.start_soon(self._supervisor.join)

        loop = ensure_event_loop()

        def trigger_exit_event() -> None:
            exit.set()

        try:
            while self._config_next:
                loop.remove_signal_handler(signal.SIGINT)
                loop.remove_signal_handler(signal.SIGTERM)

                loop.add_signal_handler(signal.SIGINT, lambda *args: trigger_exit_event())
                loop.add_signal_handler(signal.SIGTERM, lambda *args: trigger_exit_event())

                if self._server:
                    await self._server.stop()
                if self._supervisor:
                    await self._supervisor.stop()

                async with anyio.create_task_group() as group:
                    group.start_soon(process_exit)
                    group.start_soon(process_stop, group.cancel_scope)
                    group.start_soon(process_reload, group.cancel_scope)
                    group.start_soon(process, self._config_next)

                loop.remove_signal_handler(signal.SIGINT)
                loop.remove_signal_handler(signal.SIGTERM)
        finally:
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)

    async def reload(self) -> Optional[ConfigException]:
        self.logger.info(f"Reloading configuration from '{self._path}'...")
        try:
            config = Config.load(self._path)
        except ConfigException as error:
            self.logger.error(error.message)
            self.logger.error("Reload failed, found errors in configuration.")
            return error

        self.logger.info("Queueing reload for new configuration...")
        await self._config_queue.put(config)
        return None

    async def stop(self) -> None:
        if self._server:
            self.logger.info("Stopping server...")
            await self._server.stop()
        if self._supervisor:
            self.logger.info("Stopping supervisor...")
            await self._supervisor.stop()

        await super().stop()

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

    async def _check_config(self, config: Config, wait: bool = False) -> bool:
        if config.database:
            self.logger.info("Database configuration found, verifying it's reachable...")
            await self._wait_for_database(config.database, attempts=None if wait else 3)

        self.logger.info("Configuration passed all checks.")
        return True
