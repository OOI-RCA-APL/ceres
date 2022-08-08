import importlib
import inspect
import traceback
from dataclasses import dataclass, field
from logging import Logger
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Protocol,
    Type,
    TypeVar,
    cast,
)

import anyio
from anyio.abc import TaskGroup

from . import logs
from .connection import Connection, ConnectionDescriptor
from .exceptions import ObjectLoadException
from .internal import awaitify
from .object import Object, ObjectDescriptor
from .tasks import Tasklet, ensure_event_loop

ObjectT = TypeVar("ObjectT", bound=Object)


class ObjectHandle(Generic[ObjectT]):
    def __init__(
        self,
        *,
        cls: Type,
        descriptor: ObjectDescriptor[ObjectT],
    ) -> None:
        self._cls = cls
        self._descriptor = descriptor
        self._instance: Optional[ObjectT] = None

    @property
    def cls(self) -> Type:
        return self._cls

    @property
    def descriptor(self) -> ObjectDescriptor:
        return self._descriptor

    @property
    def instance(self) -> Optional[ObjectT]:
        return self._instance

    async def load(self) -> None:
        if self._descriptor.instance:
            self._instance = self._descriptor.instance
            return

        if not self._descriptor.module:
            return

        try:
            module = importlib.import_module(self._descriptor.module)
        except ModuleNotFoundError:
            raise ObjectLoadException(f"Module '{self._descriptor.module}' was not found.")
        except Exception:
            raise ObjectLoadException(
                f"Module '{self._descriptor.module}' raised an exception while importing: {traceback.format_exc()}"
            )

        init: Callable[[], Any] = cast(Any, getattr(module, "init", None))

        if (
            not init
            or not inspect.isfunction(init)
            or len(inspect.signature(init).parameters.keys()) > 0
        ):
            raise ObjectLoadException(
                f"Module '{module}' must contain an 'init()' function that takes no arguments."
            )

        try:
            instance = await awaitify(init())
        except Exception:
            raise ObjectLoadException(
                f"Module '{module}' 'init()' raised an exception: {traceback.format_exc()}"
            )

        if not isinstance(instance, self.cls):
            raise ObjectLoadException(
                f"Module '{module}' 'init()' must return an instance of {self._cls}, got '{instance}'."
            )

        self._instance = instance


@dataclass(frozen=True)
class WorkerConfig:
    name: str = "default"
    connections: List[ConnectionDescriptor] = field(default_factory=list)


class WorkerProxy(Protocol):
    def startup(self, config: WorkerConfig) -> None:
        ...

    def shutdown(self) -> None:
        ...


class Worker(WorkerProxy, Tasklet):
    def __init__(self) -> None:
        self._config: WorkerConfig = WorkerConfig()
        self._connections: Dict[str, ObjectHandle[Connection]] = {}
        self._tasks: Optional[TaskGroup] = None

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def logger(self) -> Logger:
        return logs.get(f"worker/{self.name}")

    def startup(self, config: WorkerConfig) -> None:
        async def execute() -> None:
            await self.load(config)
            await self.run()

        ensure_event_loop().run_until_complete(execute())

    def shutdown(self) -> None:
        ensure_event_loop().run_until_complete(self.stop())

    async def load(self, config: WorkerConfig) -> None:
        self._config = config
        self._connections.clear()

        for connection_descriptor in self._config.connections:
            self._connections[connection_descriptor.name] = ObjectHandle(
                cls=Connection,
                descriptor=connection_descriptor,
            )

        for connection in self._connections.values():
            try:
                await connection.load()
                self.logger.info(f"Loaded connection '{connection.descriptor.name}'.")
            except ObjectLoadException as exception:
                self.logger.error(
                    f"Failed to load connection '{connection.descriptor.name}'. {exception.message}"
                )

    async def execute(self) -> None:
        async with anyio.create_task_group() as group:
            for connection in self._connections.values():
                if connection.instance:
                    group.start_soon(connection.instance.run)

            self._tasks = group
