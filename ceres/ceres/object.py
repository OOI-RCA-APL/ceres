import asyncio
from abc import abstractmethod
from asyncio import Event as AsyncEvent
from asyncio import Lock as AsyncLock
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
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
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import (
    BinaryExpression,
    SQLColumnExpression,
    Text,
    cast,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import ParamSpec, Unpack, dataclass_transform, overload, override

from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import Alert
from ceres.config import DatabaseKind
from ceres.data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    DataObject,
    ImmutableDataObject,
    ValidatedDataclass,
)
from ceres.database import Database
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
    AlertOrder,
    ComponentFilter,
    ComponentFilterArgs,
    LogEntryFilter,
    LogEntryFilterArgs,
    LogEntryOrder,
    MessageFilter,
    MessageFilterArgs,
    MessageOrder,
    StatisticsFilter,
    StatisticsFilterArgs,
)
from ceres.internal.database.entities import (
    AlertEntity,
    ComponentEntity,
    LogEntryEntity,
    MessageEntity,
)
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import chunkify, dictify, escape_like_expression
from ceres.level import Level
from ceres.logs import Log, LogEntry
from ceres.message import Message
from ceres.stream import Stream, WriteStream
from ceres.timing import utc

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


class LevelStatistics(DataObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(DataObject):
    count: int = 0
    levels: list[LevelStatistics] = Field(default_factory=list)


class Statistics(DataObject):
    address: Address
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)


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
    def __post_init_post_parse__(self) -> None:
        self.__events: WriteStream[Event] = WriteStream()
        self.__log = Log(self)

        self.__mapping: dict[Address, UUID] | None = None
        self.__mapping_lock = AsyncLock()
        self.__flush_buffer: list[Item] = []
        self.__flushes: deque[_Flush] = deque()
        self.__flushed = AsyncEvent()
        self.__flushed.set()

    @property
    @abstractmethod
    def __container__(self) -> "Object | None":
        return ...

    @property
    @abstractmethod
    def __contained__(self) -> Sequence["Object"]:
        return ...

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
    def database(self) -> Database:
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
        if self.__container__ is None:
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
            for contained in self.__contained__:
                contained.handle(event)
        # Otherwise propagate the event to the containing object.
        else:
            self.__container__.propagate(event)

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

    async def get_id(
        self,
        address: Address | None = None,
        default: UUID | None = None,
    ) -> UUID:
        if address is None:
            address = self.address
        if self.__container__ is not None:
            return await self.__container__.get_id(address, default=default)

        if self.__mapping is not None:
            id = self.__mapping.get(address)
            if id is not None:
                return id

        async with await self.__init_database_session() as session:
            mapping = await self.__get_or_load_mapping(session)
            id = mapping.get(address)
            if id is not None:
                return id

            if id is None:
                id = await session.scalar(
                    select(ComponentEntity.id).where(ComponentEntity.address == address),
                )

            if id is None:
                id = default or uuid4()
                component = ComponentEntity(id=id, address=address)

                session.add(component)
                await session.commit()

            mapping[address] = id
            return id

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

            async with await self.__init_database_session() as session:
                # Pick the number of items to insert in a single query based on the database kind.
                match self.database.kind:
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
                        values: list[dict[str, Any]] = []

                        for model in chunk:
                            # Convert the model to a dictionary, replacing the "address" field with
                            # the "component_id".
                            data = dictify(model)
                            data.pop("address", None)
                            data["component_id"] = await self.get_id(model.address)
                            values.append(data)

                        await session.execute(
                            insert(entity_cls).on_conflict_do_nothing(),
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

    async def __generate_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        return dict(
            tuple(row)
            for row in await session.execute(
                select(ComponentEntity.address, ComponentEntity.id),
            )
        )

    async def __get_or_load_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        async with self.__mapping_lock:
            if self.__mapping is None:
                self.__mapping = await self.__generate_mapping(session)

        return self.__mapping

    async def __init_database_session(self) -> AsyncSession:
        await self.database.init()
        return self.database.session()

    def get_object(self, address: str | DynamicAddress | None, /) -> "Object | None":
        if address is None:
            return self

        address = DynamicAddress(address)
        if address.is_server:
            return self.server

        return self.get_component(address)

    @abstractmethod
    def get_component(self, address: str | DynamicAddress | None, /) -> Component | None:
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
        *,
        where: Callable[[type[MessageEntity]], SQLColumnExpression[bool]] | None = None,
        order_by: Callable[[type[MessageEntity]], SQLColumnExpression[Any]] | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> list[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)

        ids = await self.__get_ids(filter.address)
        statement = (
            select(
                MessageEntity.id,
                ComponentEntity.address,
                MessageEntity.timestamp,
                MessageEntity.direction,
                MessageEntity.content,
            )
            .join(ComponentEntity)
            .where(MessageEntity.component_id.in_(ids))
        )

        if filter.search is not None:
            pattern = "%" + escape_like_expression(filter.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(MessageEntity.timestamp),
                            pattern,
                            filter.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, filter.search_case_sensitive)
                        | _like(
                            MessageEntity.content,
                            pattern.encode("utf-8"),
                            filter.search_case_sensitive,
                        ),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(MessageEntity.timestamp),
                            pattern,
                            filter.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, filter.search_case_sensitive)
                        | _like(
                            func.encode(MessageEntity.content, "escape"),
                            pattern.encode("utf-8").decode("unicode-escape"),
                            filter.search_case_sensitive,
                        ),
                    )

        if filter.within is not None:
            statement = statement.where(MessageEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(MessageEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(MessageEntity.timestamp < filter.before)
        if filter.direction is not None:
            statement = statement.where(MessageEntity.direction == filter.direction)
        if filter.prefix is not None:
            statement = statement.where(
                MessageEntity.content.like(escape_like_expression(filter.prefix) + b"%"),
            )
        if filter.suffix is not None:
            statement = statement.where(
                MessageEntity.content.like(b"%" + escape_like_expression(filter.suffix)),
            )

        if filter.order is not None:
            match filter.order:
                case MessageOrder.OLD_TO_NEW:
                    statement = statement.order_by(MessageEntity.timestamp)
                case MessageOrder.NEW_TO_OLD:
                    statement = statement.order_by(MessageEntity.timestamp.desc())

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        if where is not None:
            statement = statement.where(where(MessageEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(MessageEntity))

        if filter.order is None and order_by is None:
            statement = statement.order_by(MessageEntity.timestamp)

        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)

        return [Message.construct(**row._asdict()) for row in rows]  # type: ignore

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

    async def get_message(
        self,
        filter: MessageFilter | None = None,
        /,
        *,
        where: Callable[[type[MessageEntity]], SQLColumnExpression[bool]] | None = None,
        order_by: Callable[[type[MessageEntity]], SQLColumnExpression[Any]] | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        messages = await self.get_messages(
            filter,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return messages[0] if messages else None

    async def get_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        *,
        where: Callable[[type[AlertEntity]], SQLColumnExpression[bool]] | None = None,
        order_by: Callable[[type[AlertEntity]], SQLColumnExpression[Any]] | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> list[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)

        ids = await self.__get_ids(filter.address)
        statement = (
            select(
                AlertEntity.id,
                ComponentEntity.address,
                AlertEntity.timestamp,
                AlertEntity.level,
                AlertEntity.code,
                AlertEntity.info,
            )
            .join(ComponentEntity)
            .where(ComponentEntity.id.in_(ids))
        )

        if filter.search is not None:
            pattern = "%" + escape_like_expression(filter.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(AlertEntity.timestamp),
                            pattern,
                            filter.search_case_sensitive,
                        )
                        | _like(AlertEntity.level, pattern, filter.search_case_sensitive)
                        | _like(AlertEntity.code, pattern, filter.search_case_sensitive)
                        | _like(AlertEntity.info, pattern, filter.search_case_sensitive),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(AlertEntity.timestamp),
                            pattern,
                            filter.search_case_sensitive,
                        )
                        | _like(AlertEntity.level, pattern, filter.search_case_sensitive)
                        | _like(AlertEntity.code, pattern, filter.search_case_sensitive)
                        | _like(
                            cast(AlertEntity.info, Text), pattern, filter.search_case_sensitive
                        ),
                    )

        if filter.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(AlertEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(AlertEntity.timestamp < filter.before)
        if filter.level is not None:
            if isinstance(filter.level, Level):
                statement = statement.where(AlertEntity.level == filter.level)
            else:
                statement = statement.where(AlertEntity.level.in_(filter.level))
        if filter.code is not None:
            if isinstance(filter.code, str):
                statement = statement.where(AlertEntity.code == filter.code)
            else:
                statement = statement.where(AlertEntity.code.in_(filter.code))
        if filter.code_regex is not None:
            statement = statement.where(AlertEntity.code.regexp_match(filter.code_regex))

        if filter.order is not None:
            match filter.order:
                case AlertOrder.OLD_TO_NEW:
                    statement = statement.order_by(AlertEntity.timestamp)
                case AlertOrder.NEW_TO_OLD:
                    statement = statement.order_by(AlertEntity.timestamp.desc())
        elif order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        if where is not None:
            statement = statement.where(where(AlertEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(AlertEntity))

        if filter.order is None and order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)

        return [Alert.construct(**row._asdict()) for row in rows]  # type: ignore

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

    async def get_alert(
        self,
        filter: AlertFilter | None = None,
        /,
        *,
        where: Callable[[type[AlertEntity]], SQLColumnExpression[bool]] | None = None,
        order_by: Callable[[type[AlertEntity]], SQLColumnExpression[Any]] | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        alerts = await self.get_alerts(
            filter,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return alerts[0] if alerts else None

    async def get_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        *,
        where: Callable[[type[LogEntryEntity]], SQLColumnExpression[bool]] | None = None,
        order_by: Callable[[type[LogEntryEntity]], SQLColumnExpression[Any]] | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> list[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)

        ids = await self.__get_ids(filter.address)
        statement = (
            select(
                LogEntryEntity.id,
                ComponentEntity.address,
                LogEntryEntity.timestamp,
                LogEntryEntity.level,
                LogEntryEntity.content,
            )
            .join(ComponentEntity)
            .where(ComponentEntity.id.in_(ids))
        )

        if filter.search is not None:
            pattern = "%" + escape_like_expression(filter.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(LogEntryEntity.timestamp),
                            pattern,
                            filter.search_case_sensitive,
                        )
                        | _like(LogEntryEntity.level, pattern, filter.search_case_sensitive)
                        | _like(
                            LogEntryEntity.content,
                            pattern,
                            filter.search_case_sensitive,
                        ),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(LogEntryEntity.timestamp),
                            pattern,
                            filter.search_case_sensitive,
                        )
                        | _like(LogEntryEntity.level, pattern, filter.search_case_sensitive)
                        | _like(
                            LogEntryEntity.content,
                            pattern,
                            filter.search_case_sensitive,
                        ),
                    )

        if filter.within is not None:
            statement = statement.where(LogEntryEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(LogEntryEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(LogEntryEntity.timestamp < filter.before)
        if filter.level is not None:
            if isinstance(filter.level, Level):
                statement = statement.where(LogEntryEntity.level == filter.level)
            else:
                statement = statement.where(LogEntryEntity.level.in_(filter.level))
        if filter.prefix is not None:
            statement = statement.where(
                LogEntryEntity.content.like(escape_like_expression(filter.prefix) + "%"),
            )
        if filter.suffix is not None:
            statement = statement.where(
                LogEntryEntity.content.like("%" + escape_like_expression(filter.suffix)),
            )

        if filter.order is not None:
            match filter.order:
                case LogEntryOrder.OLD_TO_NEW:
                    statement = statement.order_by(LogEntryEntity.timestamp)
                case LogEntryOrder.NEW_TO_OLD:
                    statement = statement.order_by(LogEntryEntity.timestamp.desc())

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        if where is not None:
            statement = statement.where(where(LogEntryEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(LogEntryEntity))

        if filter.order is None and order_by is None:
            statement = statement.order_by(LogEntryEntity.timestamp)

        async with await self.__init_database_session() as session:
            rows = await session.execute(statement)

        return [LogEntry.construct(**row._asdict()) for row in rows]  # type: ignore

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

    async def get_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        /,
        *,
        where: Callable[[type[LogEntryEntity]], SQLColumnExpression[bool]] | None = None,
        order_by: Callable[[type[LogEntryEntity]], SQLColumnExpression[Any]] | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        alerts = await self.get_log_entries(
            filter,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return alerts[0] if alerts else None

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        filter = StatisticsFilter(**kwargs).with_defaults(filter)

        addresses = self.__get_addresses(filter.address)
        statement = (
            select(ComponentEntity.address, AlertEntity.level, func.count("*"))
            .where(AlertEntity.address.in_(addresses))
            .join(ComponentEntity)
            .group_by(ComponentEntity.address, AlertEntity.level)
        )

        if filter.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(AlertEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(AlertEntity.timestamp < filter.before)

        results: dict[Address, Statistics] = {}

        async with self.database.session() as session:
            for address, level, count in await session.execute(statement):
                address: Address
                for ancestor in address.path:
                    if not self.address.contains(ancestor):
                        continue

                    current = results.setdefault(ancestor, Statistics(address=ancestor))
                    current.alerts.count += count
                    for entry in current.alerts.levels:
                        if entry.level == level:
                            entry.count += count
                            break
                    else:
                        current.alerts.levels.append(LevelStatistics(level=level, count=count))
                        current.alerts.levels.sort(key=lambda entry: entry.level)

        return list(results.values())

    async def __get_ids(self, address: AddressSelector | None) -> list[UUID]:
        return [await self.get_id(address) for address in self.__get_addresses(address)]

    def __get_addresses(self, address: AddressSelector | None) -> list[Address]:
        ids: list[Address] = []

        if address is None or address.matches(self.address):
            ids.append(self.address)

        ids.extend(
            component.address for component in self.get_components(address=address, inclusive=False)
        )

        return ids


def _like(
    expression: SQLColumnExpression[Any],
    pattern: str | bytes,
    case_sensitive: bool = False,
) -> BinaryExpression[bool]:
    if case_sensitive:
        return expression.like(pattern)
    return expression.ilike(pattern)


def _sqlite_format_timestamp(timestamp: SQLColumnExpression[datetime]) -> Any:
    return func.strftime("%Y-%m-%d %H:%M:%f", func.julianday(timestamp))


def _pg_format_timestamp(timestamp: SQLColumnExpression[datetime]) -> Any:
    return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.MS")
