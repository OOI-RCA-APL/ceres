from __future__ import annotations

import asyncio
from abc import abstractmethod
from functools import cached_property
from typing import Any, AsyncIterable, Unpack, dataclass_transform, override

from pydantic import Field
from pydantic.fields import FieldInfo

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.protocols import NodeSource
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.data import StrEnum
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

with lazy_imports(__name__):
    from sqlalchemy.ext.asyncio import AsyncSession

    from ceres._internal.database.writer import Writer
    from ceres.alert import BoundAlertManager
    from ceres.component import Component, ComponentFilter, ComponentFilterArgs, ComponentSystem
    from ceres.config import ComponentConfig, Config, LoggingConfig
    from ceres.database import Database
    from ceres.engine import Engine
    from ceres.event import NodeEventManager
    from ceres.item import Item
    from ceres.logs import BoundLogManager
    from ceres.message import BoundMessageManager
    from ceres.particle import BoundParticleManager
    from ceres.setting import SettingManager
    from ceres.statistics import StatisticsManager
    from ceres.status import Status
    from ceres.user import UserManager
    from ceres.variable import BoundVariableManager


class InternalVariableName(StrEnum):
    ENABLED = "__enabled__"


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
    def users(self) -> UserManager:
        return UserManager(self)

    @cached_property
    def variables(self) -> BoundVariableManager:
        return BoundVariableManager(self)

    @cached_property
    def settings(self) -> SettingManager:
        return SettingManager(self)

    @cached_property
    def events(self) -> NodeEventManager:
        return NodeEventManager(self)

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
        return Writer(lambda: self.database)

    def get_resolved_logging_config(self) -> LoggingConfig:
        from ceres.config import LoggingConfig

        local = self.config.logging if self.config is not None else None

        container = self.__container__
        if container is not None:
            return util.model_apply_overrides(container.get_resolved_logging_config(), local)

        return local if local is not None else LoggingConfig()

    def store(self, item: Item, /) -> None:
        from ceres.item import Item

        if not isinstance(item, Item):
            raise TypeError(f"invalid item type {type(item)}")

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
            await util.concurrently(self.__writer.flush(), container.flush())
        else:
            await self.__writer.flush()

    async def settle(self) -> None:
        await util.concurrently(self.__writer.settle(), self.events.settle())

    @override
    async def __run__(self) -> None:
        self.events.emit(StartedEvent)
        await util.concurrently(self.__process_flush(), self.events.__run__())

    async def __process_flush(self) -> None:
        while True:
            try:
                if not self.__writer.flushing and not self.__writer.empty:
                    await self.__writer.flush()
            except Exception as exception:
                self.events.emit(DatabaseExceptionEvent, traceback=util.get_traceback(exception))
                await asyncio.sleep(1)

            await asyncio.sleep(0.1)

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

    async def follow_statuses(
        self,
        filter: ComponentFilter | None = None,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> AsyncIterable[list[Status]]:
        """
        Asyncronously yield statuses of components in the tree whenever they change.
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
