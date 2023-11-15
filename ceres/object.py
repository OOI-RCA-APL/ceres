import asyncio
from abc import abstractmethod
from asyncio import Event as AsyncEvent
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Callable,
    Iterable,
    Mapping,
    TypeVar,
)

from sqlalchemy.exc import DatabaseError
from typing_extensions import ParamSpec, Unpack, dataclass_transform, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert
from ceres.config import DatabaseType
from ceres.data import VALIDATED_DATACLASS_FIELD_SPECIFIERS, ValidatedDataclass
from ceres.events import (
    AlertEvent,
    ConnectedEvent,
    ConnectFailedEvent,
    DatabaseExceptionEvent,
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
from ceres.internal.utilities import get_traceback, get_type_adapter, group_by
from ceres.level import Level
from ceres.logs import Log, LogEntry
from ceres.message import Message
from ceres.status import Status
from ceres.stream import Stream, WriteStream

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ceres.component import Component, ComponentGroup
    from ceres.database.database import Database, Statistics
    from ceres.engine import Engine
else:
    AsyncSession = object

    Component = object
    ComponentGroup = object
    Engine = object
    Database = object
    Statistics = object


_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")

Record = Message | Alert | LogEntry
_RecordT = TypeVar("_RecordT", bound=Record)


@dataclass
class _Flush:
    records: list[Record]
    event: AsyncEvent = field(default_factory=AsyncEvent)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Object(ValidatedDataclass, Tasklet):
    def __post_init__(self) -> None:
        self.__events: WriteStream[Event] = WriteStream()
        self.__log = Log(self, self)

        self.__flush_buffer: list[Record] = []
        self.__flushes: deque[_Flush] = deque()
        self.__flushed = AsyncEvent()
        self.__flushed.set()

    @property
    @abstractmethod
    def __object_parent__(self) -> "Object | None":
        return ...

    @property
    @abstractmethod
    def __object_descendants__(self) -> Iterable["Object"]:
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
    def root(self) -> Component | None:
        ...

    @property
    @abstractmethod
    def engine(self) -> Engine | None:
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
            info=dict(info) if info is not None else {},
        )

        self.emit(AlertEvent, alert=alert)
        return alert

    @override
    async def __run__(self) -> None:
        self.emit(StartedEvent)

        await self.__process_flush()

    async def __process_flush(self) -> None:
        while True:
            if self.__flush_buffer and not self.__flushes:
                try:
                    await self.flush()
                except Exception:
                    await asyncio.sleep(1)

            await asyncio.sleep(0.1)

    @override
    @abstractmethod
    async def __stop__(self) -> None:
        ...

    def store(self, record: Record) -> None:
        if not isinstance(record, Record):
            raise TypeError(f"unsupported record type: {type(record)}")

        # Add the record to the flush buffer and clear the flushed event.
        self.__flush_buffer.append(record)
        self.__flushed.clear()

    async def __create_records_by_cls(
        self,
        session: AsyncSession,
        record_cls: type[_RecordT],
        records: list[_RecordT],
    ) -> None:
        if not records:
            return

        match self.__object_database__.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert

            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        if record_cls is Message:
            entity_cls = MessageEntity
        elif record_cls is Alert:
            entity_cls = AlertEntity
        elif record_cls is LogEntry:
            entity_cls = LogEntryEntity
        else:
            raise TypeError(f"unsupported record type: {record_cls}")

        values: list[dict[str, Any]] = get_type_adapter(list[record_cls]).dump_python(records)

        await session.execute(insert(entity_cls).on_conflict_do_nothing(), values)

    async def __create_records(self, session: AsyncSession, records: Iterable[Record]) -> None:
        by_type: defaultdict[type[Record], list[Record]] = defaultdict(list)
        for model_cls, group in group_by(records, type):
            by_type[model_cls] = list(group)  # type: ignore

        await self.__create_records_by_cls(session, Message, by_type[Message])
        await self.__create_records_by_cls(session, Alert, by_type[Alert])
        await self.__create_records_by_cls(session, LogEntry, by_type[LogEntry])

    async def flush(self) -> None:
        # Get the previous flush object if there is one.
        previous = self.__flushes[-1] if self.__flushes else None

        # If there's no records in the buffer, wait for the latest flush to complete.
        if not self.__flush_buffer:
            if previous:
                await previous.event.wait()

            # Otherwise return, there's nothing to wait for.
            return

        # Register the flush request.
        flush = _Flush(records=self.__flush_buffer)
        # Clear the buffer.
        self.__flush_buffer = []
        self.__flushes.append(flush)

        try:
            # Wait for the previous flush to complete.
            if previous:
                await previous.event.wait()

            async with await self.__object_database__.init() as session:
                await self.__create_records(session, flush.records)
                await session.commit()
        except DatabaseError as exception:
            if len(self.__flushes) > 1:
                next = self.__flushes[1].records
            else:
                next = self.__flush_buffer

            next[0:0] = flush.records
            self.emit(DatabaseExceptionEvent, traceback=get_traceback(exception))
        finally:
            # Notify the flush attempt is over.
            flush.event.set()
            # Remove it from the queue.
            self.__flushes.popleft()
            # If there are records no records remaining in the buffer and no pending flushes, set
            # the "flushed" event.
            if not self.__flush_buffer and not self.__flushes:
                self.__flushed.set()

    def get_object(self, address: str | DynamicAddress | None, /) -> "Object | None":
        if address is None:
            return self

        address = DynamicAddress(address)
        if address.is_engine:
            return self.engine

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

    async def get_status(self) -> Status:
        return Status(
            address=self.address,
            running=self.running,
        )

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
            | ConnectFailedEvent
        ):
            yield await self.get_statuses(filter, **kwargs)

    async def get_messages(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> list[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)
        if filter.address is None:
            filter = filter.with_defaults(MessageFilter(address=self.address.all()))

        return await self.__object_database__.get_messages(filter, relative_to=self.address)

    async def get_message(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        return await self.__object_database__.get_message(
            filter,
            **kwargs,
            relative_to=self.address,
        )

    async def stream_messages(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> AsyncIterable[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)

        async for event in self.events.of(MessageSentEvent | MessageReceivedEvent).filter(
            lambda event: filter.matches(event.message, self.address),
        ):
            yield event.message

    async def get_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> list[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)
        if filter.address is None:
            filter = filter.with_defaults(AlertFilter(address=self.address.all()))

        return await self.__object_database__.get_alerts(filter, relative_to=self.address)

    async def get_alert(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        return await self.__object_database__.get_alert(filter, **kwargs, relative_to=self.address)

    async def stream_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> AsyncIterable[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)

        async for event in self.events.of(AlertEvent).filter(
            lambda event: filter.matches(event.alert, self.address)
        ):
            yield event.alert

    async def get_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> list[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)
        if filter.address is None:
            filter = filter.with_defaults(LogEntryFilter(address=self.address.all()))

        return await self.__object_database__.get_log_entries(filter, relative_to=self.address)

    async def get_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        return await self.__object_database__.get_log_entry(
            filter,
            **kwargs,
            relative_to=self.address,
        )

    async def stream_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> AsyncIterable[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)

        async for event in self.events.of(LogEvent).filter(
            lambda event: filter.matches(event.entry, self.address)
        ):
            yield event.entry

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        filter = StatisticsFilter(**kwargs).with_defaults(filter)
        filter = filter.with_defaults(
            StatisticsFilter(
                root=self.address,
                address=self.address.all(),
            )
        )

        return await self.__object_database__.get_statistics(filter)
