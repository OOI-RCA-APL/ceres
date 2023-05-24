import traceback
from asyncio import Event as AsyncEvent
from asyncio import Lock as AsyncLock
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from enum import Enum
from itertools import groupby
from typing import Any, TypedDict, final
from uuid import UUID, uuid4

from pydantic import Extra, Field
from sqlalchemy import BinaryExpression, ColumnElement, Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import SQLCoreOperations
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import Self, Unpack

from ceres.address import Address
from ceres.alert import Alert
from ceres.config import DatabaseKind
from ceres.data import (
    BytesPattern,
    DateTime,
    ImmutableDataObject,
    Name,
    PositiveTimeDelta,
    StrPattern,
    jsonify,
)
from ceres.database import Database
from ceres.internal.database.entities import (
    AlertEntity,
    ComponentEntity,
    LogEntryEntity,
    MessageEntity,
)
from ceres.internal.utilities import ValidateByType, chunkify, dictify, escape_like_expression
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message, MessageDirection
from ceres.timing import utc

WhereExpression = ColumnElement[bool] | ExpressionElementRole[bool]
OrderByExpression = ColumnElement[Any] | ExpressionElementRole[Any]


class MessageOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class Query(ImmutableDataObject):
    class Config(ImmutableDataObject.Config):
        extra = Extra.ignore

    def with_defaults(self, defaults: Self) -> Self:
        update: dict[str, Any] = {}

        for attribute in self.__fields__:
            current = getattr(self, attribute, None)
            if current is not None:
                continue
            default = getattr(defaults, attribute, None)
            if default is None:
                continue

            update[attribute] = default

        return self.copy(update=update)


class MessageQueryArgs(TypedDict, total=False):
    address: Address | Sequence[Address] | None
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    direction: MessageDirection | None
    prefix: bytes | None
    suffix: bytes | None
    regex: BytesPattern | None
    order: MessageOrder | None
    limit: int | None
    offset: int | None


class MessageQuery(Query):
    address: Address | Sequence[Address] | None = None
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    direction: MessageDirection | None = None
    prefix: bytes | None = None
    suffix: bytes | None = None
    regex: BytesPattern | None = None
    order: MessageOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    def matches(self, message: Message) -> bool:
        if self.address is not None:
            if isinstance(self.address, Address):
                if message.address != self.address:
                    return False
            else:
                if message.address not in self.address:
                    return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(message.timestamp)
            direction = message.direction
            content = message.content

            if not self.search_case_sensitive:
                search = search.lower()
                content = content.lower()

            if not (search in timestamp or search.encode() in content or search in direction):
                return False

        if self.within is not None:
            if message.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if message.timestamp < self.after:
                return False
        if self.before is not None:
            if message.timestamp >= self.before:
                return False

        if self.direction is not None:
            if message.direction != self.direction:
                return False

        if self.prefix is not None:
            if not message.content.startswith(self.prefix):
                return False
        if self.suffix is not None:
            if not message.content.endswith(self.suffix):
                return False
        if self.regex is not None:
            if not self.regex.match(message.content):
                return False

        return True


class AlertOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class AlertQueryArgs(TypedDict, total=False):
    address: Address | Sequence[Address] | None
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: Level | Sequence[Level] | None
    code: str | Sequence[str] | None
    code_regex: StrPattern | None
    order: AlertOrder | None
    limit: int | None
    offset: int | None


class AlertQuery(Query):
    address: Address | Sequence[Address] | None = None
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: Level | Sequence[Level] | None = None
    code: str | Sequence[str] | None = None
    code_regex: StrPattern | None = None
    order: AlertOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    def matches(self, alert: Alert) -> bool:
        if self.address is not None:
            if isinstance(self.address, Address):
                if alert.address != self.address:
                    return False
            else:
                if alert.address not in self.address:
                    return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(alert.timestamp)
            level = alert.level
            code = alert.code
            info = jsonify(alert.info)

            if self.search_case_sensitive:
                search = search.lower()
                code = code.lower()
                info = info.lower()

            if not (search in timestamp or search in level or search in code or search in info):
                return False

        if self.within is not None:
            if alert.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if alert.timestamp < self.after:
                return False
        if self.before is not None:
            if alert.timestamp >= self.before:
                return False

        if self.level is not None:
            if isinstance(self.level, Level):
                if alert.level != self.level:
                    return False
            else:
                if alert.level not in self.level:
                    return False

        if self.code is not None:
            if isinstance(self.code, str):
                if alert.code != self.code:
                    return False
            else:
                if alert.code not in self.code:
                    return False

        if self.code_regex is not None:
            if not self.code_regex.match(alert.code):
                return False

        return True


class LogEntryOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class LogEntryQueryArgs(TypedDict, total=False):
    address: Address | Sequence[Address] | None
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: Level | Sequence[Level] | None
    prefix: str | None
    suffix: str | None
    regex: StrPattern | None
    order: LogEntryOrder | None
    limit: int | None
    offset: int | None


class LogEntryQuery(Query):
    address: Address | Sequence[Address] | None = None
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: Level | Sequence[Level] | None = None
    prefix: str | None = None
    suffix: str | None = None
    regex: StrPattern | None = None
    order: LogEntryOrder | None = None
    limit: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)

    def matches(self, entry: LogEntry) -> bool:
        if self.address is not None:
            if isinstance(self.address, Address):
                if entry.address != self.address:
                    return False
            else:
                if entry.address not in self.address:
                    return False

        if self.search is not None:
            search = self.search
            timestamp = _format_timestamp(entry.timestamp)
            level = entry.level
            content = entry.content

            if not self.search_case_sensitive:
                search = search.lower()
                content = content.lower()

            if not (search in timestamp or search in level or search in content):
                return False

        if self.within is not None:
            if entry.timestamp < utc() - self.within:
                return False
        if self.after is not None:
            if entry.timestamp < self.after:
                return False
        if self.before is not None:
            if entry.timestamp >= self.before:
                return False

        if self.prefix is not None:
            if not entry.content.startswith(self.prefix):
                return False
        if self.suffix is not None:
            if not entry.content.endswith(self.suffix):
                return False
        if self.regex is not None:
            if not self.regex.match(entry.content):
                return False

        return True


class StatisticsQueryArgs(TypedDict, total=False):
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None


class StatisticsQuery(Query):
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None


class AlertLevelStatistics(ImmutableDataObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(ImmutableDataObject):
    count: int
    levels: Sequence[AlertLevelStatistics]


class ComponentStatistics(ImmutableDataObject):
    alerts: AlertStatistics
    children: Mapping[Name, "ComponentStatistics"] = Field(default_factory=dict)


class UnitStatistics(ImmutableDataObject):
    alerts: AlertStatistics
    components: Mapping[Name, ComponentStatistics] = Field(default_factory=dict)


class Statistics(ImmutableDataObject):
    alerts: AlertStatistics
    units: Mapping[Name, UnitStatistics] = Field(default_factory=dict)


Item = Message | Alert | LogEntry


@final
class Environment(ValidateByType):
    def __init__(
        self,
        *,
        database: Database | None = None,
    ) -> None:
        if database is None:
            database = Database()

        self.__database = database
        self.__mapping: dict[Address, UUID] | None = None
        self.__mapping_lock = AsyncLock()
        self.__flushing = False
        self.__buffer: list[Item] = []
        self.__settled = AsyncEvent()
        self.__settled.set()

    @property
    def database(self) -> Database:
        return self.__database

    @property
    def settled(self) -> bool:
        return self.__settled.is_set()

    async def assign_component_id(
        self,
        address: Address,
        default: UUID | None = None,
    ) -> UUID:
        if self.__mapping is not None:
            id = self.__mapping.get(address)
            if id is not None:
                return id

        async with self.__database.session() as session:
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

    def add(self, item: Message | Alert | LogEntry) -> None:
        if not isinstance(item, (Message, Alert, LogEntry)):
            raise TypeError(f"unsupported item type: {type(item)}")

        self.__buffer.append(item)
        self.__settled.clear()

    async def flush(self) -> None:
        if self.__flushing or not self.__buffer:
            return
        if not self.__buffer:
            return

        self.__flushing = True

        try:
            async with self.database.session() as session:
                buffer = self.__buffer
                self.__buffer = []

                match self.database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert

                        chunk_size = 500

                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert  # noqa

                        chunk_size = 1000

                for model_cls, models in groupby(buffer, type):
                    if issubclass(model_cls, Message):
                        entity_cls = MessageEntity
                    elif issubclass(model_cls, Alert):
                        entity_cls = AlertEntity
                    elif issubclass(model_cls, LogEntry):
                        entity_cls = LogEntryEntity
                    else:
                        continue

                    for chunk in chunkify(models, chunk_size):
                        values: list[dict[str, Any]] = []

                        for model in chunk:
                            data = dictify(model)
                            data.pop("address", None)
                            data["component_id"] = await self.assign_component_id(model.address)
                            values.append(data)

                        await session.execute(
                            insert(entity_cls).values(values).on_conflict_do_nothing()
                        )

                await session.commit()
        except Exception:
            traceback.print_exc()
        finally:
            self.__flushing = False
            if not self.__buffer:
                self.__settled.set()

    async def settle(self) -> None:
        await self.__settled.wait()

    async def get_messages(
        self,
        query: MessageQuery | None = None,
        *,
        where: Callable[[type[MessageEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[MessageEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> list[Message]:
        statement = select(
            MessageEntity.id,
            ComponentEntity.address.label("source"),
            MessageEntity.timestamp,
            MessageEntity.direction,
            MessageEntity.content,
        ).join(ComponentEntity)
        if query is not None:
            query = query.with_defaults(MessageQuery(**kwargs))
        else:
            query = MessageQuery(**kwargs)

        if query.address is not None:
            if isinstance(query.address, Address):
                statement = statement.where(MessageEntity.address == query.address)
            else:
                statement = statement.where(MessageEntity.address.in_(query.address))

        if query.search is not None:
            pattern = "%" + escape_like_expression(query.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(MessageEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, query.search_case_sensitive)
                        | _like(
                            MessageEntity.content,
                            pattern.encode("utf-8"),
                            query.search_case_sensitive,
                        ),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(MessageEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, query.search_case_sensitive)
                        | _like(
                            func.encode(MessageEntity.content, "escape"),
                            pattern.encode("utf-8").decode("unicode-escape"),
                            query.search_case_sensitive,
                        ),
                    )

        if query.within is not None:
            statement = statement.where(MessageEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(MessageEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(MessageEntity.timestamp < query.before)
        if query.direction is not None:
            statement = statement.where(MessageEntity.direction == query.direction)
        if query.prefix is not None:
            statement = statement.where(
                MessageEntity.content.like(escape_like_expression(query.prefix) + b"%"),
            )
        if query.suffix is not None:
            statement = statement.where(
                MessageEntity.content.like(b"%" + escape_like_expression(query.suffix)),
            )

        if query.order is not None:
            match query.order:
                case MessageOrder.OLD_TO_NEW:
                    statement = statement.order_by(MessageEntity.timestamp)
                case MessageOrder.NEW_TO_OLD:
                    statement = statement.order_by(MessageEntity.timestamp.desc())

        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset is not None:
            statement = statement.offset(query.offset)

        if where is not None:
            statement = statement.where(where(MessageEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(MessageEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(MessageEntity.timestamp)

        async with self.__database.session() as session:
            rows = await session.execute(statement)

        return [Message.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_message(
        self,
        query: MessageQuery | None = None,
        *,
        where: Callable[[type[MessageEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[MessageEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[MessageQueryArgs],
    ) -> Message | None:
        messages = await self.get_messages(
            query,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return messages[0] if messages else None

    async def get_alerts(
        self,
        query: AlertQuery | None = None,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[AlertQueryArgs],
    ) -> list[Alert]:
        statement = select(
            AlertEntity.id,
            ComponentEntity.address.label("source"),
            AlertEntity.timestamp,
            AlertEntity.level,
            AlertEntity.code,
            AlertEntity.info,
        ).join(ComponentEntity)

        if query is not None:
            query = query.with_defaults(AlertQuery(**kwargs))
        else:
            query = AlertQuery(**kwargs)

        if query.address is not None:
            if isinstance(query.address, Address):
                statement = statement.where(AlertEntity.address == query.address)
            else:
                statement = statement.where(AlertEntity.address.in_(query.address))

        if query.search is not None:
            pattern = "%" + escape_like_expression(query.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(AlertEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(AlertEntity.level, pattern, query.search_case_sensitive)
                        | _like(AlertEntity.code, pattern, query.search_case_sensitive)
                        | _like(AlertEntity.info, pattern, query.search_case_sensitive),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(AlertEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(AlertEntity.level, pattern, query.search_case_sensitive)
                        | _like(AlertEntity.code, pattern, query.search_case_sensitive)
                        | _like(cast(AlertEntity.info, Text), pattern, query.search_case_sensitive),
                    )

        if query.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(AlertEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(AlertEntity.timestamp < query.before)
        if query.level is not None:
            if isinstance(query.level, Level):
                statement = statement.where(AlertEntity.level == query.level)
            else:
                statement = statement.where(AlertEntity.level.in_(query.level))
        if query.code is not None:
            if isinstance(query.code, str):
                statement = statement.where(AlertEntity.code == query.code)
            else:
                statement = statement.where(AlertEntity.code.in_(query.code))
        if query.code_regex is not None:
            statement = statement.where(AlertEntity.code.regexp_match(query.code_regex))

        if query.order is not None:
            match query.order:
                case AlertOrder.OLD_TO_NEW:
                    statement = statement.order_by(AlertEntity.timestamp)
                case AlertOrder.NEW_TO_OLD:
                    statement = statement.order_by(AlertEntity.timestamp.desc())
        elif order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset is not None:
            statement = statement.offset(query.offset)

        if where is not None:
            statement = statement.where(where(AlertEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(AlertEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        async with self.__database.session() as session:
            rows = await session.execute(statement)

        return [Alert.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_alert(
        self,
        query: AlertQuery | None = None,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[AlertQueryArgs],
    ) -> Alert | None:
        alerts = await self.get_alerts(
            query,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return alerts[0] if alerts else None

    async def get_log_entries(
        self,
        query: LogEntryQuery | None = None,
        *,
        where: Callable[[type[LogEntryEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[LogEntryEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[LogEntryQueryArgs],
    ) -> list[LogEntry]:
        statement = select(
            LogEntryEntity.id,
            ComponentEntity.address.label("source"),
            LogEntryEntity.timestamp,
            LogEntryEntity.level,
            LogEntryEntity.content,
        ).join(ComponentEntity)
        if query is not None:
            query = query.with_defaults(LogEntryQuery(**kwargs))
        else:
            query = LogEntryQuery(**kwargs)

        if query.address is not None:
            if isinstance(query.address, Address):
                statement = statement.where(LogEntryEntity.address == query.address)
            else:
                statement = statement.where(LogEntryEntity.address.in_(query.address))

        if query.search is not None:
            pattern = "%" + escape_like_expression(query.search) + "%"
            match self.database.kind:
                case DatabaseKind.SQLITE:
                    statement = statement.where(
                        _like(
                            _sqlite_format_timestamp(LogEntryEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(LogEntryEntity.level, pattern, query.search_case_sensitive)
                        | _like(
                            LogEntryEntity.content,
                            pattern,
                            query.search_case_sensitive,
                        ),
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            _pg_format_timestamp(LogEntryEntity.timestamp),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(LogEntryEntity.level, pattern, query.search_case_sensitive)
                        | _like(
                            LogEntryEntity.content,
                            pattern,
                            query.search_case_sensitive,
                        ),
                    )

        if query.within is not None:
            statement = statement.where(LogEntryEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(LogEntryEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(LogEntryEntity.timestamp < query.before)
        if query.level is not None:
            if isinstance(query.level, Level):
                statement = statement.where(LogEntryEntity.level == query.level)
            else:
                statement = statement.where(LogEntryEntity.level.in_(query.level))
        if query.prefix is not None:
            statement = statement.where(
                LogEntryEntity.content.like(escape_like_expression(query.prefix) + "%"),
            )
        if query.suffix is not None:
            statement = statement.where(
                LogEntryEntity.content.like("%" + escape_like_expression(query.suffix)),
            )

        if query.order is not None:
            match query.order:
                case LogEntryOrder.OLD_TO_NEW:
                    statement = statement.order_by(LogEntryEntity.timestamp)
                case LogEntryOrder.NEW_TO_OLD:
                    statement = statement.order_by(LogEntryEntity.timestamp.desc())

        if query.limit is not None:
            statement = statement.limit(query.limit)
        if query.offset is not None:
            statement = statement.offset(query.offset)

        if where is not None:
            statement = statement.where(where(LogEntryEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(LogEntryEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(LogEntryEntity.timestamp)

        async with self.__database.session() as session:
            rows = await session.execute(statement)

        return [LogEntry.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_log_entry(
        self,
        query: LogEntryQuery | None = None,
        *,
        where: Callable[[type[LogEntryEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[LogEntryEntity]], OrderByExpression] | None = None,
        **kwargs: Unpack[LogEntryQueryArgs],
    ) -> LogEntry | None:
        alerts = await self.get_log_entries(
            query,
            where=where,
            order_by=order_by,
            **{**kwargs, "limit": 1},
        )

        return alerts[0] if alerts else None

    async def get_statistics(
        self,
        query: StatisticsQuery | None = None,
        **kwargs: Unpack[StatisticsQueryArgs],
    ) -> Statistics:
        statement = (
            select(ComponentEntity.address, AlertEntity.level, func.count("*").label("count"))
            .join(ComponentEntity)
            .group_by(ComponentEntity.address, AlertEntity.level)
        )

        if query is not None:
            query = query.with_defaults(StatisticsQuery(**kwargs))
        else:
            query = StatisticsQuery(**kwargs)

        if query.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - query.within)
        if query.after is not None:
            statement = statement.where(AlertEntity.timestamp >= query.after)
        if query.before is not None:
            statement = statement.where(AlertEntity.timestamp < query.before)

        alert_count = 0
        unit_alert_counts: defaultdict[Name, int] = defaultdict(int)
        component_alert_counts: defaultdict[Name, defaultdict[Name, int]] = defaultdict(
            lambda: defaultdict(int),
        )

        alert_counts_by_level: defaultdict[Level, int] = defaultdict(int)
        unit_alert_counts_by_level: defaultdict[Name, defaultdict[Level, int]] = defaultdict(
            lambda: defaultdict(int),
        )
        component_alert_counts_by_level: defaultdict[
            Name,
            defaultdict[Name, defaultdict[Level, int]],
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        async with self.__database.session() as session:
            rows = await session.execute(statement)

        for address, level, count in rows:
            alert_count += count
            unit_alert_counts[address.unit] += count
            component_alert_counts[address.unit][address.name] += count

            alert_counts_by_level[level] += count
            unit_alert_counts_by_level[address.unit][level] += count
            component_alert_counts_by_level[address.unit][address.name][level] += count

        return Statistics(
            alerts=AlertStatistics(
                count=alert_count,
                levels=sorted(
                    [
                        AlertLevelStatistics(
                            level=level,
                            count=count,
                        )
                        for level, count in alert_counts_by_level.items()
                    ],
                    key=lambda current: current.level,
                ),
            ),
            units={
                unit_name: UnitStatistics(
                    alerts=AlertStatistics(
                        count=unit_alert_counts[unit_name],
                        levels=sorted(
                            [
                                AlertLevelStatistics(
                                    level=level,
                                    count=count,
                                )
                                for level, count in unit_alert_counts_by_level[unit_name].items()
                            ],
                            key=lambda current: current.level,
                        ),
                    ),
                    components={
                        component_name: ComponentStatistics(
                            alerts=AlertStatistics(
                                count=component_alert_counts[unit_name][component_name],
                                levels=sorted(
                                    [
                                        AlertLevelStatistics(
                                            level=level,
                                            count=count,
                                        )
                                        for level, count in component_alert_counts_by_level[
                                            unit_name
                                        ][component_name].items()
                                    ],
                                    key=lambda current: current.level,
                                ),
                            ),
                        )
                        for component_name in component_alert_counts_by_level[unit_name]
                    },
                )
                for unit_name in unit_alert_counts_by_level
            },
        )

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


def _like(
    expression: SQLCoreOperations[Any],
    pattern: str | bytes,
    case_sensitive: bool = False,
) -> BinaryExpression[bool]:
    if case_sensitive:
        return expression.like(pattern)
    return expression.ilike(pattern)


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%f")[:-3]


def _sqlite_format_timestamp(timestamp: SQLCoreOperations[datetime]) -> Any:
    return func.strftime(
        "%Y-%m-%d %H:%M:%f",
        func.julianday(timestamp),
    )


def _pg_format_timestamp(timestamp: SQLCoreOperations[datetime]) -> Any:
    return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.MS")
