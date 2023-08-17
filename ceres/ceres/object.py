import asyncio
from abc import abstractmethod
from asyncio import Event as AsyncEvent
from collections import deque
from dataclasses import dataclass, field
from itertools import groupby
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Callable,
    Mapping,
    Sequence,
    TypeVar,
)

from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import ParamSpec, Unpack, dataclass_transform, overload, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert
from ceres.config import DatabaseKind
from ceres.data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    ValidatedDataclass,
)
from ceres.database import AlertStatistics as AlertStatistics
from ceres.database import Database
from ceres.database import LevelStatistics as LevelStatistics
from ceres.database import Statistics as Statistics
from ceres.events import (
    AlertEvent,
    ConnectedEvent,
    DisabledEvent,
    DisconnectedEvent,
    EnabledEvent,
    Event,
    LogEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    StartedEvent,
    StoppedEvent,
)
from ceres.filter import (
    AlertFilter,
    AlertFilterArgs,
    ComponentFilter,
    ComponentFilterArgs,
    LogEntryFilter,
    LogEntryFilterArgs,
    MessageFilter,
    MessageFilterArgs,
    StatisticsFilter,
    StatisticsFilterArgs,
)
from ceres.internal.database.entities import AlertEntity, LogEntryEntity, MessageEntity
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import chunkify, dictify
from ceres.level import Level
from ceres.logs import Log, LogEntry
from ceres.message import Message
from ceres.stream import Stream, WriteStream

if TYPE_CHECKING:
    from ceres.component import Component, ComponentGroup
    from ceres.server import Server
else:
    Component = object
    ComponentGroup = object
    Status = object
    Server = object

_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")

Item = Message | Alert | LogEntry


class Status(ImmutableDataObject):
    address: Address
    running: bool
    enabled: bool


@dataclass
class _Flush:
    items: Sequence[Item]
    event: AsyncEvent = field(default_factory=AsyncEvent)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Object(ValidatedDataclass, Tasklet):
    def __post_init__(self) -> None:
        self.__events: WriteStream[Event] = WriteStream()
        self.__log = Log(self)

        self.__flush_buffer: list[Item] = []
        self.__flushes: deque[_Flush] = deque()
        self.__flushed = AsyncEvent()
        self.__flushed.set()

    @property
    @abstractmethod
    def __object_parent__(self) -> "Object | None":
        return ...

    @property
    @abstractmethod
    def __object_descendants__(self) -> Sequence["Object"]:
        return ...

    @property
    @abstractmethod
    def __object_database__(self) -> Database:
        ...

    async def __object_sync__(self, session: AsyncSession | None = None) -> None:
        pass

    @property
    @abstractmethod
    def address(self) -> Address:
        ...

    @property
    @abstractmethod
    def root(self) -> Component:
        ...

    @property
    @abstractmethod
    def server(self) -> Server | None:
        ...

    @property
    def log(self) -> Log:
        return self.__log

    @property
    def events(self) -> Stream[Event]:
        return self.__events.view()

    @property
    def settled(self) -> bool:
        if not self.running:
            return True

        return self.__flushed.is_set()

    async def settle(self) -> None:
        await self.flush()
        await self.__flushed.wait()

    def emit(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        if "address" not in kwargs:
            kwargs["address"] = self.address

        return self.propagate(event_cls(*args, **kwargs))

    def propagate(self, event: _EventT) -> _EventT:
        # Add the event to the outgoing event stream.
        self.__events.put(event)

        # If there is no containing object, store and disperse the event ourselves.
        if self.__object_parent__ is None:
            match event:
                case MessageSentEvent() | MessageReceivedEvent():
                    self.store(event.message)
                case AlertEvent():
                    self.store(event.alert)
                case LogEvent():
                    self.store(event.entry)
                case _:
                    pass

            self.handle(event)
            for contained in self.__object_descendants__:
                contained.handle(event)
        # Otherwise propagate the event to the containing object.
        else:
            self.__object_parent__.propagate(event)

        return event

    def handle(self, event: Event) -> None:
        pass

    def alert(
        self,
        level: Level,
        code: str,
        info: Mapping[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            address=self.address,
            level=level,
            code=code,
            info=info if info is not None else {},
        )

        self.emit(AlertEvent, alert=alert)
        return alert

    @override
    async def __run__(self) -> None:
        self.emit(StartedEvent)

        await self.__process_flush()

    async def __process_flush(self) -> None:
        while True:
            if self.__flush_buffer:
                await self.flush()
            await asyncio.sleep(0.1)

    @override
    async def __stop__(self) -> None:
        await self.flush()

    @override
    async def __done__(self) -> None:
        self.emit(StoppedEvent)

    def store(self, item: Item) -> None:
        if not isinstance(item, Item):
            raise TypeError(f"unsupported item type: {type(item)}")

        # Add the item to the flush buffer and clear the flushed event.
        self.__flush_buffer.append(item)
        self.__flushed.clear()

    async def flush(self) -> None:
        # Keep track of all pending flushes.
        pending = tuple(self.__flushes)

        # If there's no items in the buffer, wait for the latest flush to complete.
        if not self.__flush_buffer:
            if pending:
                await pending[-1].event.wait()

            # Otherwise return, there's nothing to wait for.
            return

        # Register the flush request.
        flush = _Flush(items=tuple(self.__flush_buffer))
        self.__flushes.append(flush)

        # Clear the buffer.
        self.__flush_buffer = []

        try:
            # Wait for the previous flush to complete.
            if pending:
                await pending[-1].event.wait()

            async with await self.__object_database__.init() as session:
                # Pick the number of items to insert in a single query based on the database kind.
                match self.__object_database__.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert

                        chunk_size = 500

                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert  # noqa

                        chunk_size = 1000

                # Group items by item class.
                for model_cls, model in groupby(flush.items, type):
                    # Determine the entity class of item.
                    if issubclass(model_cls, Message):
                        entity_cls = MessageEntity
                    elif issubclass(model_cls, Alert):
                        entity_cls = AlertEntity
                    elif issubclass(model_cls, LogEntry):
                        entity_cls = LogEntryEntity
                    else:
                        continue

                    # Insert items in chunks.
                    for chunk in chunkify(model, chunk_size):
                        values = [dictify(model) for model in chunk]
                        await session.execute(
                            insert(entity_cls).on_conflict_do_nothing(
                                index_elements=[entity_cls.id]
                            ),
                            values,
                        )

                await session.commit()
        finally:
            # Notify the flush is complete.
            flush.event.set()
            # Remove it from the queue.
            self.__flushes.popleft()
            # If there are items no items remaining in the buffer and no pending flushes, set
            # the "flushed" event.
            if not self.__flush_buffer and not self.__flushes:
                self.__flushed.set()

    def get_object(self, address: str | DynamicAddress | None, /) -> "Object | None":
        if address is None:
            return self

        address = DynamicAddress(address)
        if address.is_server:
            return self.server

        return self.get_component(address)

    @abstractmethod
    def get_component(self, address: str | DynamicAddress | None = None, /) -> Component | None:
        ...

    @abstractmethod
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> "ComponentGroup":
        ...

    @overload
    async def get_status(self, address: str | DynamicAddress) -> Status | None:
        ...

    @overload
    async def get_status(self, address: None = None) -> Status:
        ...

    async def get_status(self, address: str | DynamicAddress | None = None) -> Status | None:
        if address is None:
            return Status(
                address=self.address,
                running=self.running,
                enabled=False,
            )

        component = self.get_object(address)
        if component is None:
            return None

        return await component.get_status()

    async def get_statuses(
        self,
        filter: ComponentFilter | None = None,
        /,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Status]:
        filter = ComponentFilter(**kwargs).with_defaults(filter)

        return [await component.get_status() for component in self.get_components(filter)]

    async def stream_statuses(
        self,
        filter: ComponentFilter | None = None,
        /,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> AsyncIterable[list[Status]]:
        yield await self.get_statuses(filter, **kwargs)

        async for _ in self.events.of(
            StartedEvent
            | StoppedEvent
            | EnabledEvent
            | DisabledEvent
            | ConnectedEvent
            | DisconnectedEvent
        ):
            yield await self.get_statuses(filter, **kwargs)

    async def get_messages(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> list[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)
        addresses = self.__get_addresses(filter.address)
        filter = filter.with_defaults(MessageFilter(address=AddressSelector(addresses)))
        return await self.__object_database__.get_messages(filter)

    async def get_message(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        return await self.__object_database__.get_message(filter, **kwargs)

    async def stream_messages(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> AsyncIterable[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)

        async for event in self.events.of(MessageSentEvent | MessageReceivedEvent).filter(
            lambda event: filter.matches(event.message),
        ):
            yield event.message

    async def get_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> list[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)
        addresses = self.__get_addresses(filter.address)
        filter = filter.with_defaults(AlertFilter(address=AddressSelector(addresses)))
        return await self.__object_database__.get_alerts(filter)

    async def get_alert(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        return await self.__object_database__.get_alert(filter, **kwargs)

    async def stream_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> AsyncIterable[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)

        async for event in self.events.of(AlertEvent).filter(
            lambda event: filter.matches(event.alert)
        ):
            yield event.alert

    async def get_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> list[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)
        addresses = self.__get_addresses(filter.address)
        filter = filter.with_defaults(LogEntryFilter(address=AddressSelector(addresses)))
        return await self.__object_database__.get_log_entries(filter)

    async def get_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        return await self.__object_database__.get_log_entry(filter, **kwargs)

    async def stream_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> AsyncIterable[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)

        async for event in self.events.of(LogEvent).filter(
            lambda event: filter.matches(event.entry)
        ):
            yield event.entry

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        filter = StatisticsFilter(**kwargs).with_defaults(filter)
        addresses = self.__get_addresses(filter.address)
        filter = filter.with_defaults(
            StatisticsFilter(
                root=self.address,
                address=AddressSelector(addresses),
            )
        )

        return await self.__object_database__.get_statistics(filter)

    def __get_addresses(self, address: AddressSelector | None) -> list[Address]:
        addresses: list[Address] = []

        if address is None or address.matches(self.address):
            addresses.append(self.address)

        addresses.extend(
            component.address for component in self.get_components(address=address, inclusive=False)
        )

        return addresses
