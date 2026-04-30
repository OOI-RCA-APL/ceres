import asyncio
from abc import abstractmethod
from asyncio import Task
from typing import TYPE_CHECKING, Any, Protocol, override

from ceres.__internal__.protocols import ComponentSource, DatabaseSource, NodeSource
from ceres.concurrency import cancel, sleep

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.database import Database
    from ceres.node import Node


class BaseDatabaseManager(DatabaseSource):
    """Base manager that delegates database access to a ``DatabaseSource``."""

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
    """Base manager that delegates both database and node access to a ``NodeSource``."""

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)
        self.__source__ = source

    @property
    @override
    def __node__(self) -> Node:
        return self.__source__.__node__


class BaseComponentManager(BaseNodeManager, ComponentSource):
    """Base manager that delegates database, node, and component access to a ``ComponentSource``."""

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
    """Manage a collection of named objects, each backed by a long-running async task.

    Add or remove objects at runtime. While this manager is running, each object gets its
    own ``asyncio.Task`` executing ``process``. Stopping the manager cancels all tasks.
    """

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
        """Start all current tasks and wait indefinitely until stopped."""
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
    async def process(self, config: T, /) -> None:
        """Run the long-lived processing loop for a single managed object.

        Subclasses must implement this coroutine. It is invoked as an ``asyncio.Task`` for
        each object added to the manager.

        Args:
            config: The named object to process.
        """
        ...

    def add(self, obj: T, /) -> None:
        """Register `obj` and, if the manager is running, start its task immediately.

        If `obj.name` is ``None``, assign it a unique numeric name. The object's name must
        not already be in use.

        Args:
            obj: The named object to add.
        """
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
        """Return the managed object with the given `name`, or ``None`` if not found."""
        return self._objects.get(name)

    def all(self) -> list[T]:
        """Return a list of all managed objects."""
        return list(self._objects.values())

    async def remove(self, name: str, /) -> T | None:
        """Cancel the task for `name`, remove the object, and return it.

        Args:
            name: The name of the object to remove.

        Returns:
            The removed object, or ``None`` if no object with that name existed.
        """
        runner = self._tasks.get(name)
        if runner is not None:
            await cancel(runner)
            self._tasks.pop(name, None)

        config = self._objects.pop(name, None)
        return config

    async def clear(self) -> None:
        """Cancel all tasks and remove all managed objects."""
        await self._clear_tasks()
        self._objects.clear()

    async def _clear_tasks(self) -> None:
        """Cancel and discard all running tasks without removing the managed objects."""
        await cancel(self._tasks.values())
        self._tasks.clear()

    def _create_task(self, config: T) -> Task:
        """Create and register an ``asyncio.Task`` that processes `config`."""
        assert config.name is not None
        task = asyncio.create_task(self.process(config), name=config.name + "-task")
        self._tasks[config.name] = task
        return task

    def _sync_tasks(self) -> None:
        """Ensure every registered object has a corresponding running task."""
        for config in self._objects.values():
            self._create_task(config)
