from logging import Logger
from multiprocessing.managers import BaseManager
from typing import Any, Dict, Optional, Sequence, cast

import anyio

from . import logs
from .app import App
from .config import Config
from .connection import ConnectionDescriptor
from .tasks import Tasklet
from .worker import Worker, WorkerConfig, WorkerProxy


class WorkerManager(BaseManager):
    pass


WorkerManager.register("Worker", Worker)


class WorkerHandle:
    def __init__(self, config: WorkerConfig) -> None:
        self._config = config
        self._manager: Optional[WorkerManager] = None
        self._instance: Optional[WorkerProxy] = None

    @property
    def setup(self) -> WorkerConfig:
        return self._config

    @property
    def instance(self) -> Optional[WorkerProxy]:
        return self._instance

    def start(self) -> None:
        self._manager = WorkerManager()
        self._manager.start()
        instance = cast(WorkerProxy, cast(Any, self._manager).Worker())
        self._instance = instance
        instance.startup(self._config)

    def stop(self) -> None:
        if self._instance:
            self._instance.shutdown()
            self._instance = None
        if self._manager:
            self._manager.shutdown()
            self._manager = None


class Supervisor(Tasklet):
    def __init__(self, config: Optional[Config], app: Optional[App]) -> None:
        super().__init__()
        self._config = config or Config()
        self._app = app
        self._workers: Dict[str, WorkerHandle] = {}

    @property
    def logger(self) -> Logger:
        return logs.get("supervisor")

    @property
    def connections(self) -> Sequence[ConnectionDescriptor]:
        return [
            ConnectionDescriptor(
                name=name,
                module=definition.module,
                worker=definition.worker,
            )
            for name, definition in self._config.connections.items()
        ]

    async def execute(self) -> None:
        self.logger.info("Supervisor starting...")

        names = sorted(
            {
                *(current.worker for current in self.connections),
            }
        )

        self._workers = {}

        for name in names:
            self._workers[name] = WorkerHandle(
                WorkerConfig(
                    name=name,
                    connections=[current for current in self.connections if current.worker == name],
                )
            )

        async def process_worker(worker: WorkerHandle) -> None:
            await anyio.to_thread.run_sync(worker.start, cancellable=True)

        try:
            async with anyio.create_task_group() as group:
                for worker in self._workers.values():
                    self.logger.info(f"Starting worker '{worker.setup.name}'...")
                    group.start_soon(process_worker, worker)

        except:
            await self.stop()

    async def stop(self) -> None:
        if not self._workers:
            return

        self.logger.info("Stopping all workers...")

        for worker in self._workers.values():
            if worker.instance:
                self.logger.info(f"Stopping worker '{worker.setup.name}'...")
                worker.stop()

        self._workers = {}
        self.logger.info("All workers were stopped successfully.")

        await super().stop()
