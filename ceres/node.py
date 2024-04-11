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

from pydantic import Field
from pydantic.fields import FieldInfo
from sqlalchemy.exc import DatabaseError
from typing_extensions import ParamSpec, Unpack, dataclass_transform, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert, AlertUpdate
from ceres.config import DatabaseType
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
    LogEntryFilter,
    LogEntryFilterArgs,
    MessageFilter,
    MessageFilterArgs,
    StatisticsFilter,
    StatisticsFilterArgs,
    SystemFilter,
    SystemFilterArgs,
    UserFilter,
    UserFilterArgs,
)
from ceres.internal.database.entities import AlertEntity, LogEntryEntity, MessageEntity
from ceres.internal.utilities import get_traceback, get_type_adapter, group_by
from ceres.level import Level
from ceres.logs import Log, LogEntry, LogEntryUpdate
from ceres.message import Message, MessageUpdate
from ceres.status import Status
from ceres.stream import Stream, WriteStream
from ceres.tasklet import Tasklet
from ceres.user import User, UserCreate, UserUpdate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ceres.database.database import Database, Statistics
    from ceres.engine import Engine
    from ceres.system import System, SystemGroup
else:
    AsyncSession = object

    Database = object
    Statistics = object
    Engine = object
    SystemGroup = object
    System = object


_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")
_FilterT = TypeVar("_FilterT", bound=MessageFilter | AlertFilter | LogEntryFilter)

Record = Message | Alert | LogEntry
_RecordT = TypeVar("_RecordT", bound=Record)


@dataclass(slots=True)
class _Flush:
    records: list[Record]
    event: AsyncEvent = field(default_factory=AsyncEvent)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class Node(Tasklet):
    def __init__(self) -> None:
        self.__events: WriteStream[Event] = WriteStream()
        self.__log = Log(self, self)  # type: ignore

        self.__flush_buffer: list[Record] = []
        self.__flushes: deque[_Flush] = deque()
        self.__flushed = AsyncEvent()
        self.__flushed.set()

    @property
    @abstractmethod
    def __node_parent__(self) -> "Node | None": ...

    @property
    @abstractmethod
    def __node_descendants__(self) -> Iterable["Node"]: ...

    @property
    def __node_default_root__(self) -> "Address | None":
        return None

    async def __node_sync__(self, session: AsyncSession | None = None) -> None:
        pass

    @property
    @abstractmethod
    def parent(self) -> "Node | None": ...

    @property
    @abstractmethod
    def address(self) -> Address: ...

    @property
    @abstractmethod
    def root(self) -> System | None: ...

    @property
    @abstractmethod
    def database(self) -> Database: ...

    @property
    @abstractmethod
    def engine(self) -> Engine | None: ...

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
        if self.__node_parent__ is None:
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
            for contained in self.__node_descendants__:
                contained.handle(event)
        # Otherwise propagate the event to the containing object.
        else:
            self.__node_parent__.propagate(event)

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
    async def __stop__(self) -> None: ...

    def store(self, record: Record) -> None:
        """
        Store a given record in the database.

        This method is syncronous because it does not write the record to the database *immediately*, but rather, buffers the record to be flushed later on.
        """

        if not isinstance(record, Record):
            raise TypeError(f"unsupported record type: {type(record)}")

        # Add the record to the flush buffer and clear the flushed event.
        self.__flush_buffer.append(record)
        self.__flushed.clear()

    async def flush(self) -> None:
        """
        Flush all buffered records to the database. To queue records to be flushed, use the `store()` method.

        *This method does not generally need to be called directly in code. Records will be flushed automatically while running and just before stopping.*
        """

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

            async with await self.database.init() as session:
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

    def get_node(self, address: str | DynamicAddress | None, /) -> "Node | None":
        """
        Get an object from the tree by address.
        """
        if address is None:
            return self

        address = DynamicAddress(address)
        if address.is_engine:
            return self.engine

        return self.get_system(address)

    @abstractmethod
    def get_system(
        self,
        address: str | DynamicAddress | None = None,
        /,
    ) -> System | None:
        """
        Get a system from the tree by address.
        """

    @abstractmethod
    def get_systems(
        self,
        filter: SystemFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[SystemFilterArgs],
    ) -> "SystemGroup":
        """
        Get a group of systems from the tree by address/filter.
        """

    async def get_messages(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> list[Message]:
        """
        Get messages from the database according to the given filter criteria.
        """
        filter = self.__apply_filter_defaults(MessageFilter, filter)
        return await self.database.get_messages(filter, **kwargs)

    async def get_message(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        """
        Get a message from the database according to the given filter criteria.
        """

        filter = self.__apply_filter_defaults(MessageFilter, filter)
        return await self.database.get_message(filter, **kwargs)

    async def stream_messages(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> AsyncIterable[Message]:
        """
        Stream emitted messages according to the given filter criteria.
        """
        filter = self.__apply_filter_defaults(MessageFilter, filter, kwargs)

        async for event in self.events.of(
            MessageSentEvent if TYPE_CHECKING else MessageSentEvent | MessageReceivedEvent
        ).filter(
            lambda event: filter.matches(event.message),
        ):
            yield event.message

    async def count_messages(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> int:
        """
        Count messages matching the given `filter`.
        """
        return await self.database.count_messages(filter, **kwargs)

    async def create_message(self, data: Message) -> Message:
        """
        Create a new message in the database.
        """
        return await self.database.create_message(data)

    async def update_messages(self, filter: MessageFilter, assign: MessageUpdate) -> int:
        """
        Update messages matching the given `filter`. Returns the number of messages updated.
        """
        return await self.database.update_messages(filter, assign)

    async def update_message(self, filter: MessageFilter, assign: MessageUpdate) -> Message | None:
        """
        Update a message matching the given `filter`. Returns the updated message, if found.
        """
        return await self.database.update_message(filter, assign)

    async def delete_messages(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> int:
        """
        Delete messages matching the given `filter`.
        """
        return await self.database.delete_messages(filter, **kwargs)

    async def delete_message(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        """
        Delete a message matching the given `filter`. Returns the deleted message, if found.
        """
        return await self.database.delete_message(filter, **kwargs)

    async def get_alerts(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> list[Alert]:
        """
        Get alerts from the database according to the given filter criteria.
        """
        filter = self.__apply_filter_defaults(AlertFilter, filter)
        return await self.database.get_alerts(filter, **kwargs)

    async def get_alert(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        """
        Get an alert from the database according to the given filter criteria.
        """
        filter = self.__apply_filter_defaults(AlertFilter, filter)
        return await self.database.get_alert(filter, **kwargs)

    async def stream_alerts(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> AsyncIterable[Alert]:
        """
        Stream emitted alerts according to the given filter criteria.
        """
        filter = self.__apply_filter_defaults(AlertFilter, filter, kwargs)
        async for event in self.events.of(AlertEvent).filter(
            lambda event: filter.matches(event.alert)
        ):
            yield event.alert

    async def count_alerts(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> int:
        """
        Count alerts matching the given `filter`.
        """
        return await self.database.count_alerts(filter, **kwargs)

    async def create_alert(self, assign: Alert) -> Alert:
        """
        Create a new alert in the database.
        """
        return await self.database.create_alert(assign)

    async def update_alerts(self, filter: AlertFilter, assign: AlertUpdate) -> int:
        """
        Update alerts matching the given `filter`. Returns the number of alerts updated.
        """
        return await self.database.update_alerts(filter, assign)

    async def update_alert(self, filter: AlertFilter, assign: AlertUpdate) -> Alert | None:
        """
        Update an alert matching the given `filter`. Returns the updated alert, if found.
        """
        return await self.database.update_alert(filter, assign)

    async def delete_alerts(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> int:
        """
        Delete alerts matching the given `filter`. Returns the number of alerts deleted.
        """
        return await self.database.delete_alerts(filter, **kwargs)

    async def delete_alert(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        """
        Delete an alert matching the given `filter`. Returns the deleted alert, if found.
        """
        return await self.database.delete_alert(filter, **kwargs)

    async def get_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> list[LogEntry]:
        """
        Get log entries from the database according to the given filter criteria.
        """
        self.__apply_filter_defaults(LogEntryFilter, filter)
        return await self.database.get_log_entries(filter, **kwargs)

    async def get_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        """
        Get a log entry from the database according to the given filter criteria.
        """
        self.__apply_filter_defaults(LogEntryFilter, filter)
        return await self.database.get_log_entry(filter, **kwargs)

    async def stream_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> AsyncIterable[LogEntry]:
        """
        Stream emitted log entries according to the given filter criteria.
        """
        filter = self.__apply_filter_defaults(LogEntryFilter, filter, kwargs)

        async for event in self.events.of(LogEvent).filter(
            lambda event: filter.matches(event.entry)
        ):
            yield event.entry

    async def count_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> int:
        """
        Count log entries matching the given `filter`.
        """
        return await self.database.count_log_entries(filter, **kwargs)

    async def create_log_entry(self, assign: LogEntry) -> LogEntry:
        """
        Create a new log entry in the database.
        """
        return await self.database.create_log_entry(assign)

    async def update_log_entries(self, filter: LogEntryFilter, assign: LogEntryUpdate) -> int:
        """
        Update log entries matching the given `filter`. Returns the number of log entries updated.
        """
        return await self.database.update_log_entries(filter, assign)

    async def update_log_entry(
        self,
        filter: LogEntryFilter,
        assign: LogEntryUpdate,
    ) -> LogEntry | None:
        """
        Update a log entry matching the given `filter`. Returns the updated log entry, if found.
        """
        return await self.database.update_log_entry(filter, assign)

    async def delete_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> int:
        """
        Delete log entries matching the given `filter`. Returns the number of log entries deleted.
        """
        return await self.database.delete_log_entries(filter, **kwargs)

    async def delete_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        """
        Delete a log entry matching the given `filter`. Returns the deleted log entry, if found.
        """
        return await self.database.delete_log_entry(filter, **kwargs)

    async def get_users(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> list[User]:
        """
        Get a list of users matching the given `filter`.
        """
        return await self.database.get_users(filter, **kwargs)

    async def get_user(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> User | None:
        """
        Get a user matching the given `filter`.
        """
        return await self.database.get_user(filter, **kwargs)

    async def count_users(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> int:
        """
        Count users matching the given `filter`.
        """
        return await self.database.count_users(filter, **kwargs)

    async def create_user(self, data: UserCreate) -> User:
        """
        Create a new user in the database.
        """
        return await self.database.create_user(data)

    async def update_users(self, filter: UserFilter, assign: UserUpdate) -> int:
        """
        Update users matching the given `filter`. Returns the number of users updated.
        """
        return await self.database.update_users(filter, assign)

    async def update_user(self, filter: UserFilter, assign: UserUpdate) -> User | None:
        """
        Update a user matching the given `filter`. Returns the updated user, if found.
        """
        return await self.database.update_user(filter, assign)

    async def delete_users(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> int:
        """
        Delete users matching the given `filter`. Returns the number of users deleted.
        """
        return await self.database.delete_users(filter, **kwargs)

    async def delete_user(
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> User | None:
        """
        Delete a user matching the given `filter`. Returns the deleted user, if found.
        """
        return await self.database.delete_user(filter, **kwargs)

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        """
        Get statistics about running systems according to the given filter criteria.
        """
        filter = (
            StatisticsFilter(**kwargs)
            .with_defaults(filter)
            .with_defaults(StatisticsFilter(root=self.address, address=self.address.all()))
        )

        return await self.database.get_statistics(filter)

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
        filter: SystemFilter | None = None,
        **kwargs: Unpack[SystemFilterArgs],
    ) -> list[Status]:
        """
        Get current statuses of systems in the tree.
        """
        filter = SystemFilter(**kwargs).with_defaults(filter)

        return [await component.get_status() for component in self.get_systems(filter)]

    async def stream_statuses(
        self,
        filter: SystemFilter | None = None,
        **kwargs: Unpack[SystemFilterArgs],
    ) -> AsyncIterable[list[Status]]:
        """
        Asyncronously yield statuses of the systems in the tree whenever they change.
        """
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

    async def __create_records_by_cls(
        self,
        session: AsyncSession,
        record_cls: type[_RecordT],
        records: list[_RecordT],
    ) -> None:
        if not records:
            return

        match self.database.type:
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

    def __apply_filter_defaults(
        self,
        filter_type: type[_FilterT],
        filter: _FilterT | None,
        kwargs: Any | None = None,
    ) -> _FilterT:
        if kwargs is None:
            kwargs = {}
        return (
            filter_type(**kwargs)
            .with_defaults(filter)  # type: ignore
            .with_defaults(filter_type(root=self.address, address=self.address.all()))  # type: ignore
        )
