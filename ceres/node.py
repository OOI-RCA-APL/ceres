from abc import abstractmethod
from collections.abc import AsyncIterable
from functools import cached_property
from typing import TYPE_CHECKING, Any, Unpack, dataclass_transform, override

from pydantic import Field
from pydantic.fields import FieldInfo

from ceres.__internal__.lazy import __lazy_imports__
from ceres.__internal__.protocols import NodeSource
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.concurrency import concurrently, sleep
from ceres.data import replacing
from ceres.error import trace
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
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime

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
    """Base class for addressable lifecycle-managed objects in the Ceres tree.

    A `Node` is a `Tasklet` with an `Address`, a view of the `Database`, and a suite of
    bound managers (alerts, logs, messages, particles, variables, events, and statistics) that
    surface the data and events scoped to this node. `Engine` and `ComponentSystem` are the
    concrete subclasses.
    """

    __slots__ = ("__tasklet__",)

    def __init__(self) -> None:
        super().__init__()

    @property
    @abstractmethod
    def __container__(self) -> Node | None:
        """The parent node in the tree, or `None` if this node is the root of its tree."""

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

    @property
    def time(self) -> datetime:
        """Current UTC time, provided as an attribute so tests can override it per node."""
        return utc()

    async def __node_sync__(self, connection: AsyncConnection | None = None) -> None:
        """Hook for subclasses to hydrate persisted state, called once during startup."""
        pass

    @property
    @abstractmethod
    def address(self) -> Address:
        """Absolute address identifying this node within the tree."""

    @property
    @abstractmethod
    def engine(self) -> Engine | None:
        """The engine this node belongs to, or `None` if the node is not attached to one."""

    @property
    @abstractmethod
    def database(self) -> Database:
        """The database backing this node."""

    @property
    @abstractmethod
    def config(self) -> Config | ComponentConfig | None:
        """The resolved configuration for this node, or `None` if no configuration applies."""

    @property
    @abstractmethod
    def root(self) -> ComponentSystem | None:
        """The root component's system for the tree this node belongs to."""

    @cached_property
    def messages(self) -> BoundMessageManager:
        """Node-bound manager for messages addressed to or from this node."""
        return BoundMessageManager(self)

    @cached_property
    def particles(self) -> BoundParticleManager:
        """Node-bound manager for particles produced by this node."""
        return BoundParticleManager(self)

    @cached_property
    def alerts(self) -> BoundAlertManager:
        """Node-bound manager for raising and querying alerts from this node."""
        return BoundAlertManager(self)

    @property
    def alert(self) -> BoundAlertManager:
        """Alias for `alerts`, kept for ergonomic call sites like `self.alert.info(...)`."""
        return self.alerts

    @cached_property
    def logs(self) -> BoundLogManager:
        """Node-bound manager for writing and querying log records from this node."""
        return BoundLogManager(self)

    @property
    def log(self) -> BoundLogManager:
        """Alias for `logs`, kept for ergonomic call sites like `self.log.info(...)`."""
        return self.logs

    @cached_property
    def variables(self) -> BoundVariableManager:
        """Node-bound manager for reading and writing variables scoped to this node."""
        return BoundVariableManager(self)

    @cached_property
    def events(self) -> EventManager:
        """Event manager that dispatches and streams events emitted on this node."""
        return EventManager(self)

    @cached_property
    def statistics(self) -> StatisticsManager:
        """Manager that aggregates timing and counter statistics for this node."""
        return StatisticsManager(self)

    @property
    def settled(self) -> bool:
        """Return `True` when all pending database writes and events have been flushed.

        A stopped node is always considered settled.
        """
        if not self.running:
            return True

        return self.__writer.settled and self.events.settled

    @cached_property
    def __writer(self):
        from ceres.__internal__.database.writer import Writer

        return Writer(lambda: self.database)

    def get_resolved_logging_config(self) -> LoggingConfig | None:
        """Return the effective logging configuration for this node.

        Resolution walks up the container chain, merging each ancestor's logging configuration
        with the local one so child settings override inherited ones.

        Returns:
            The merged `LoggingConfig`, or `None` when neither this node nor any ancestor
            configures logging.
        """
        local = self.config.logging if self.config is not None else None

        # If this node has a container, inherit logging configuration from it.
        container = self.__container__
        if container is not None:
            inherited = container.get_resolved_logging_config()
            if inherited is not None:
                return replacing(inherited, local)

        return local

    def store(self, item: Item, /) -> None:
        """Enqueue an item to be persisted by the owning tree's writer.

        Items bubble up to the root node, which owns the shared writer. Particles are converted
        to their dynamic form before being enqueued so the stored record is always concrete.

        Args:
            item: The item to persist.

        Raises:
            TypeError: If `item` is not an instance of `Item`.
        """
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
        """Flush any pending writes on this node and its ancestors to the database."""
        container = self.__container__
        if container is not None:
            await concurrently(self.__writer.flush(), container.flush())
        else:
            await self.__writer.flush()

    async def settle(self) -> None:
        """Wait until the local writer and event manager have drained their queues."""
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
                self.events.emit(DatabaseExceptionEvent, exception=trace(exception))
                await sleep(1)

            await sleep(0.1)

    @override
    @abstractmethod
    def __stopping__(self) -> None: ...

    @override
    @abstractmethod
    async def __stop__(self) -> None: ...

    def get_node(self, address: str | DynamicAddress | None, /) -> ComponentSystem | Engine | None:
        """Look up a node by address.

        Args:
            address: The address to resolve. Pass `None` to get this node itself, the engine
                address to get the engine, or any other address to resolve a descendant
                component's system.

        Returns:
            The matching node, or `None` if no node exists at the given address.
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
        """Look up a component by address relative to this node.

        Args:
            address: The address to resolve. Pass `None` to get the component at this node,
                or an address to resolve a descendant.

        Returns:
            The matching component, or `None` if no component exists at the given address.
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
        """Return the components in this node's subtree that match the given filter.

        Args:
            filter: A `ComponentFilter` or `AddressSelector` to apply, or `None` to skip
                positional filtering.
            inclusive: When `True`, include this node's own component in the result.
            **kwargs: Additional filter overrides forwarded as `ComponentFilterArgs`.

        Returns:
            A list of matching components, in tree order.
        """

    async def get_status(self) -> Status:
        """Return a snapshot of this node's running state.

        Returns:
            A `Status` value describing the node's address and whether it is currently running.
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
        """Return statuses of components in the subtree matching the given filter.

        Args:
            filter: A `ComponentFilter` to apply, or `None` to skip positional filtering.
            **kwargs: Additional filter overrides forwarded as `ComponentFilterArgs`.

        Returns:
            A list of `Status` values, one per matching component.
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
        """Yield statuses of components in the subtree whenever any status changes.

        The first yielded value is the current snapshot. Subsequent values are emitted each
        time a relevant lifecycle event (start, stop, enable, disable, connect, disconnect,
        connect-failed) fires.

        Args:
            filter: A `ComponentFilter` to apply, or `None` to skip positional filtering.
            **kwargs: Additional filter overrides forwarded as `ComponentFilterArgs`.

        Yields:
            Lists of `Status` values, one per matching component, recomputed on each change.
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
