import asyncio
from abc import abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING, AsyncIterable

from pydantic import Field
from pydantic.fields import FieldInfo
from typing_extensions import Unpack, dataclass_transform, override

from ceres._internal.typedecs import __Item__
from ceres._internal.utilities import get_traceback, model_apply_overrides
from ceres.address import Address, AddressSelector, DynamicAddress
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
from ceres.manager.alert import LiveAlertManager
from ceres.manager.event import EventManager
from ceres.manager.logs import LiveLogManager
from ceres.manager.message import LiveMessageManager
from ceres.manager.statistic import StatisticsManager
from ceres.manager.user import UserManager
from ceres.status import Status
from ceres.tasklet import Tasklet

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ceres.component import Component, ComponentFilter, ComponentFilterArgs, ComponentSystem
    from ceres.config import LoggingConfig, NodeConfig
    from ceres.database.database import Database
    from ceres.engine import Engine
else:
    AsyncSession = object
    Component = object
    ComponentFilter = object
    ComponentFilterArgs = object
    ComponentSystem = object
    NodeConfig = object
    LoggingConfig = object
    Database = object
    Engine = object


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class Node(Tasklet):
    def __init__(self, /) -> None:
        super().__init__()

    @property
    @abstractmethod
    def __container__(self) -> "Node | None": ...

    async def __node_sync__(self, session: AsyncSession | None = None) -> None:
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
    def config(self) -> NodeConfig | None: ...

    @property
    @abstractmethod
    def root(self) -> ComponentSystem | None: ...

    @cached_property
    def messages(self) -> LiveMessageManager:
        return LiveMessageManager(self)

    @cached_property
    def alerts(self) -> LiveAlertManager:
        return LiveAlertManager(self)

    @cached_property
    def log(self) -> LiveLogManager:
        return LiveLogManager(self)

    @cached_property
    def users(self) -> UserManager:
        return UserManager(self)

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

    def get_resolved_logging_config(self) -> LoggingConfig:
        from ceres.config import LoggingConfig

        local = self.config.logging if self.config is not None else None

        container = self.__container__
        if container is not None:
            return model_apply_overrides(container.get_resolved_logging_config(), local)

        return local if local is not None else LoggingConfig()

    def store(self, item: __Item__, /) -> None:
        # If the node has a containing node, delegate storage of the item to it.
        container = self.__container__
        if container is not None:
            container.store(item)
            return

        from ceres.alert import Alert
        from ceres.logs import LogEntry
        from ceres.message import Message

        if type(item) not in (Message, Alert, LogEntry):
            raise TypeError(f"invalid item type {type(item)}")

        self.__writer.add(item)

    async def flush(self) -> None:
        container = self.__container__
        if container is not None and container is not self:
            await asyncio.gather(self.__writer.flush(), container.flush())
        else:
            await self.__writer.flush()

    async def settle(self) -> None:
        await asyncio.gather(self.__writer.settle(), self.events.settle())

    @override
    async def __run__(self) -> None:
        self.events.emit(StartedEvent)
        await asyncio.gather(self.__process_flush(), self.events.process())

    async def __process_flush(self) -> None:
        while True:
            try:
                if not self.__writer.flushing and not self.__writer.empty:
                    await self.__writer.flush()
            except Exception as exception:
                self.events.emit(DatabaseExceptionEvent, traceback=get_traceback(exception))
                await asyncio.sleep(1)

            await asyncio.sleep(0.1)

    @override
    @abstractmethod
    async def __stop__(self) -> None: ...

    def get_node(self, address: str | DynamicAddress | None, /) -> "Node | None":
        """
        Get an object from the tree by address.
        """
        if address is None:
            return self

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
        Get current status of the system, including address and running state.
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
        Get current statuses of systems in the tree.
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
        Asyncronously yield statuses of the systems in the tree whenever they change.
        """
        yield await self.get_statuses(filter, **kwargs)

        async for _ in self.events.follow().every(
            StartedEvent
            | StoppedEvent
            | EnabledEvent
            | DisabledEvent
            | ConnectedEvent
            | DisconnectedEvent
            | ConnectFailedEvent
        ):
            yield await self.get_statuses(filter, **kwargs)
