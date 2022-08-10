import traceback
from dataclasses import dataclass, field
from logging import Logger
from typing import Dict, List, Optional, Protocol, TypeVar

import anyio
from anyio.abc import TaskGroup

from . import logs
from .config import DatabaseConfig
from .connection import ConnectionDescriptor, ConnectionHandle
from .database import Database
from .exceptions import ObjectLoadException
from .object import Object
from .tasks import Tasklet, ensure_event_loop

ObjectT = TypeVar("ObjectT", bound=Object)


@dataclass(frozen=True)
class UnitDescriptor:
    name: str
    database: DatabaseConfig
    connections: List[ConnectionDescriptor] = field(default_factory=list)


class UnitProxy(Protocol):
    def rpc_start(self) -> None:
        ...

    def rpc_stop(self) -> None:
        ...


class Unit(UnitProxy, Tasklet):
    def __init__(self, descriptor: UnitDescriptor) -> None:
        self._descriptor = descriptor
        self._database = Database(self._descriptor.database)
        self._connections: Dict[str, ConnectionHandle] = {}
        self._tasks: Optional[TaskGroup] = None

    @property
    def descriptor(self) -> UnitDescriptor:
        return self._descriptor

    @property
    def logger(self) -> Logger:
        return logs.get(f"@{self._descriptor.name}")

    def rpc_start(self) -> None:
        async def run() -> None:
            try:
                await self.run()
            except Exception:
                self.logger.error(traceback.format_exc())

        ensure_event_loop().run_until_complete(run())

    def rpc_stop(self) -> None:
        async def stop() -> None:
            try:
                await self.stop()
            except Exception:
                self.logger.error(traceback.format_exc())

        ensure_event_loop().run_until_complete(stop())

    async def teardown(self) -> None:
        for connection in self._connections.values():
            await connection.disconnect()

        await self._database.dispose()

    async def execute(self) -> None:
        await self.teardown()

        self._connections.clear()

        for connection_descriptor in self._descriptor.connections:
            self._connections[connection_descriptor.name] = ConnectionHandle(
                descriptor=connection_descriptor,
                database=self._database,
            )

        for connection in self._connections.values():
            try:
                await connection.load()
                self.logger.info(f"Loaded connection '{connection.descriptor.name}'.")
            except ObjectLoadException as exception:
                self.logger.error(
                    f"Failed to load connection '{connection.descriptor.name}'. {exception.message}"
                )

        async with anyio.create_task_group() as group:
            for connection in self._connections.values():
                group.start_soon(connection.run)

            self._tasks = group
