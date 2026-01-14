from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from asyncio import Task
from typing import TYPE_CHECKING, Any, Protocol, override

from ceres._internal import util
from ceres._internal.protocols import ComponentSource, DatabaseSource, NodeSource

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.database import Database
    from ceres.node import Node


class BaseDatabaseManager(ABC, DatabaseSource):
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
    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)
        self.__source__ = source

    @property
    @override
    def __node__(self) -> Node:
        return self.__source__.__node__


class BaseComponentManager(BaseNodeManager, ComponentSource):
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
    name: Any


class BaseComponentTaskManager[T: _Named](BaseComponentManager):
    __slots__ = (
        "__configs",
        "__tasks",
        "__running",
        "__stopping",
        "__syncs",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__source__ = source
        self.__objects: dict[str, T] = {}
        self.__tasks: dict[str, Task] = {}
        self.__running = False
        self.__stopping = False

    @property
    def count(self) -> int:
        return len(self.__objects)

    @property
    def running(self) -> bool:
        return self.__running

    @property
    def stopping(self) -> bool:
        return self.__stopping

    async def __run__(self) -> None:
        self.__running = True
        try:
            self.__sync_tasks()
            await util.sleep_forever()
        finally:
            self.__stopping = True
            try:
                await self.__clear_tasks()
            finally:
                self.__running = False
                self.__stopping = False

    @abstractmethod
    async def process(self, config: T, /) -> None: ...

    def add(self, obj: T, /) -> None:
        if obj.name is None:
            while True:
                number = self.count + 1
                name = str(number)
                if self.get(name) is None:
                    obj.name = name
                    break

        assert obj.name not in self.__objects
        self.__objects[obj.name] = obj
        if self.__running and not self.__stopping:
            self.__sync_tasks()

    def get(self, name: str, /) -> T | None:
        return self.__objects.get(name)

    def all(self) -> list[T]:
        return list(self.__objects.values())

    async def remove(self, name: str, /) -> T | None:
        runner = self.__tasks.get(name)
        if runner is not None:
            await util.cancel(runner)
            self.__tasks.pop(name, None)

        config = self.__objects.pop(name, None)
        return config

    async def clear(self) -> None:
        await self.__clear_tasks()
        self.__objects.clear()

    async def __clear_tasks(self) -> None:
        await util.cancel(self.__tasks.values())
        self.__tasks.clear()

    def __create_task(self, config: T) -> Task:
        assert config.name is not None
        task = asyncio.create_task(self.process(config), name=config.name + "-task")
        self.__tasks[config.name] = task
        return task

    def __sync_tasks(self) -> None:
        for config in self.__objects.values():
            self.__create_task(config)
