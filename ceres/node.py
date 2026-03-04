from abc import abstractmethod
from collections.abc import AsyncIterable
from functools import cached_property
from typing import TYPE_CHECKING, Any, Unpack, dataclass_transform, override

from pydantic import Field
from pydantic.fields import FieldInfo

from ceres._internal import util
from ceres._internal.lazy import __lazy_imports__
from ceres._internal.protocols import NodeSource
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.concurrency import concurrently, sleep
from ceres.data import replacing
from ceres.event import (
    ConnectedEvent,
    ConnectFailedEvent,
    DatabaseExceptionEvent,
    DisabledEvent,
    DisconnectedEvent,
    EnabledEvent,
    StartedEvent,
    StoppedEvent,
)
from ceres.tasklet import Tasklet

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from ceres.component import Component, ComponentFilter, ComponentFilterArgs, ComponentSystem
    from ceres.config import ComponentConfig, Config, LoggingConfig
    from ceres.database import Database
    from ceres.engine import Engine
    from ceres.item import Item

with __lazy_imports__(__name__):
    from ceres.alert import BoundAlertManager
    from ceres.event import EventManager
    from ceres.logs import BoundLogManager
    from ceres.message import BoundMessageManager
    from ceres.particle import BoundParticleManager
    from ceres.statistics import StatisticsManager
    from ceres.status import Status
    from ceres.variable import BoundVariableManager


__all__ = [
    "Node",
]


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class Node(Tasklet, NodeSource):
    __slots__ = ("__tasklet__",)

    def __init__(self) -> None:
        super().__init__()

    @property
    @abstractmethod
    def __container__(self) -> Node | None: ...

    @property
    @override
    def __database__(self) -> Database:
        return self.database

    @override
    def __get_filter_defaults__(self) -> dict[str, Any]:
        return {
            "root": self.address,
            "address": self.address.all(),
        }

    @property
    @override
    def __node__(self) -> Node:
        return self

    async def __node_sync__(self, connection: AsyncConnection | None = None) -> None:
        pass

    @property
    @abstractmethod
    def address(self) -> Address: ...

    @property
    @abstractmethod
    def engine(self) -> Engine | None: ...

    @property
    @abstractmethod
    def database(self) -> Database: ...

    @property
    @abstractmethod
    def config(self) -> Config | ComponentConfig | None: ...

    @property
    @abstractmethod
    def root(self) -> ComponentSystem | None: ...

    @cached_property
    def messages(self) -> BoundMessageManager:
        return BoundMessageManager(self)

    @cached_property
    def particles(self) -> BoundParticleManager:
        return BoundParticleManager(self)

    @cached_property
    def alerts(self) -> BoundAlertManager:
        return BoundAlertManager(self)

    @property
    def alert(self) -> BoundAlertManager:
        return self.alerts

    @cached_property
    def logs(self) -> BoundLogManager:
        return BoundLogManager(self)

    @property
    def log(self) -> BoundLogManager:
        return self.logs

    @cached_property
    def variables(self) -> BoundVariableManager:
        return BoundVariableManager(self)

    @cached_property
    def events(self) -> EventManager:
        return EventManager(self)

    @cached_property
    def statistics(self) -> StatisticsManager:
        return StatisticsManager(self)

    @property
    def settled(self) -> bool:
        if not self.running:
            return True

        return self.__writer.settled and self.events.settled

    @cached_property
    def __writer(self):
        from ceres._internal.database.writer import Writer

        return Writer(lambda: self.database)

    def get_resolved_logging_config(self) -> LoggingConfig | None:
        local = self.config.logging if self.config is not None else None

        # If this node has a container, inherit logging configuration from it.
        container = self.__container__
        if container is not None:
            inherited = container.get_resolved_logging_config()
            if inherited is not None:
                return replacing(inherited, local)

        return local

    def store(self, item: Item, /) -> None:
        from ceres.item import Item
        from ceres.particle import Particle

        if not isinstance(item, Item):
            raise TypeError(f"invalid item type {type(item)}")
        if isinstance(item, Particle):
            item = item.to_dynamic()

        self.__store(item)

    def __store(self, item: Item, /) -> None:
        container = self.__container__
        if container is None:
            self.__writer.add(item)
        else:
            container.__store(item)

    async def flush(self) -> None:
        container = self.__container__
        if container is not None:
            await concurrently(self.__writer.flush(), container.flush())
        else:
            await self.__writer.flush()

    async def settle(self) -> None:
        await concurrently(self.__writer.settle(), self.events.settle())

    @override
    async def __run__(self) -> None:
        self.events.emit(StartedEvent)
        await concurrently(self.__process_flush(), self.events.__run__())

    async def __process_flush(self) -> None:
        while True:
            try:
                if not self.__writer.flushing and not self.__writer.empty:
                    await self.__writer.flush()
            except Exception as exception:
                self.events.emit(DatabaseExceptionEvent, traceback=util.get_traceback(exception))
                await sleep(1)

            await sleep(0.1)

    @override
    @abstractmethod
    def __stopping__(self) -> None: ...

    @override
    @abstractmethod
    async def __stop__(self) -> None: ...

    def get_node(self, address: str | DynamicAddress | None, /) -> ComponentSystem | Engine | None:
        """
        Get a node from the tree by address.
        """
        if address is None:
            return self  # type: ignore

        address = DynamicAddress(address)
        if address.is_engine:
            return self.engine

        component = self.get_component(address)
        if component is None:
            return None

        return component.system

    @abstractmethod
    def get_component(self, address: str | DynamicAddress | None = None, /) -> Component | None:
        """
        Get a component from the tree by address.
        """

    @abstractmethod
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Component]:
        """
        Get a group of components from the tree by address/filter.
        """

    async def get_status(self) -> Status:
        """
        Get current status of the component, including address and running state.
        """
        return Status(
            address=self.address,
            running=self.running,
        )

    async def get_statuses(
        self,
        filter: ComponentFilter | None = None,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Status]:
        """
        Get current statuses of components in the tree.
        """
        return [
            await component.system.get_status()
            for component in self.get_components(filter, **kwargs)
        ]

    async def stream_statuses(
        self,
        filter: ComponentFilter | None = None,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> AsyncIterable[list[Status]]:
        """
        Asyncronously yield statuses of components in the tree whenever they change.
        """
        yield await self.get_statuses(filter, **kwargs)

        async for _ in self.events.stream.every(
            StartedEvent,
            StoppedEvent,
            EnabledEvent,
            DisabledEvent,
            ConnectedEvent,
            DisconnectedEvent,
            ConnectFailedEvent,
        ):
            yield await self.get_statuses(filter, **kwargs)
