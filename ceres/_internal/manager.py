import asyncio
from abc import abstractmethod
from asyncio import Task
from typing import TYPE_CHECKING, Any, Protocol, override

from ceres._internal.protocols import ComponentSource, DatabaseSource, NodeSource
from ceres.concurrency import cancel, sleep

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.database import Database
    from ceres.node import Node


class BaseDatabaseManager(DatabaseSource):
    __slots__ = ("__source__",)

    def __init__(self, source: DatabaseSource, /) -> None:
        self.__source__ = source

    @property
    @override
    def __database__(self) -> Database:
        return self.__source__.__database__

    @override
    def __get_filter_defaults__(self) -> dict[str, Any]:
        return self.__source__.__get_filter_defaults__()


class BaseNodeManager(BaseDatabaseManager, NodeSource):
    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)
        self.__source__ = source

    @property
    @override
    def __node__(self) -> Node:
        return self.__source__.__node__


class BaseComponentManager(BaseNodeManager, ComponentSource):
    __slots__ = ()

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__source__ = source

    @property
    @override
    def __component__(self) -> Component:
        return self.__source__.__component__

    @property
    @override
    def __system__(self) -> ComponentSystem:
        return self.__source__.__system__


class _Named(Protocol):
    @property
    def name(self) -> Any: ...


class BaseComponentTaskManager[T: _Named](BaseComponentManager):
    __slots__ = (
        "_objects",
        "_tasks",
        "_running",
        "_stopping",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__source__ = source
        self._objects: dict[str, T] = {}
        self._tasks: dict[str, Task] = {}
        self._running = False
        self._stopping = False

    @property
    def count(self) -> int:
        return len(self._objects)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stopping(self) -> bool:
        return self._stopping

    async def __run__(self) -> None:
        self._running = True
        try:
            self._sync_tasks()
            await sleep(...)
        finally:
            self._stopping = True
            try:
                await self._clear_tasks()
            finally:
                self._running = False
                self._stopping = False

    @abstractmethod
    async def process(self, config: T, /) -> None: ...

    def add(self, obj: T, /) -> None:
        if obj.name is None:
            while True:
                number = self.count + 1
                name = str(number)
                if self.get(name) is None:
                    try:
                        obj.name = name  # type: ignore
                    except Exception:
                        pass
                    break

        assert obj.name not in self._objects
        self._objects[obj.name] = obj
        if self._running and not self._stopping:
            self._sync_tasks()

    def get(self, name: str, /) -> T | None:
        return self._objects.get(name)

    def all(self) -> list[T]:
        return list(self._objects.values())

    async def remove(self, name: str, /) -> T | None:
        runner = self._tasks.get(name)
        if runner is not None:
            await cancel(runner)
            self._tasks.pop(name, None)

        config = self._objects.pop(name, None)
        return config

    async def clear(self) -> None:
        await self._clear_tasks()
        self._objects.clear()

    async def _clear_tasks(self) -> None:
        await cancel(self._tasks.values())
        self._tasks.clear()

    def _create_task(self, config: T) -> Task:
        assert config.name is not None
        task = asyncio.create_task(self.process(config), name=config.name + "-task")
        self._tasks[config.name] = task
        return task

    def _sync_tasks(self) -> None:
        for config in self._objects.values():
            self._create_task(config)
