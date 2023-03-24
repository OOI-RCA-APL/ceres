from asyncio import Lock as AsyncLock
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from enum import Enum
from re import Pattern
from typing import TYPE_CHECKING, Any, TypedDict, final
from uuid import UUID, uuid4

from pydantic import Extra, Field
from sqlalchemy import BinaryExpression, ColumnElement, Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import SQLCoreOperations
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import Self, Unpack

from ceres.address import Address
from ceres.alert import Alert, AlertLevel
from ceres.config import DatabaseKind
from ceres.data import DateTime, ImmutableDataObject, Name, PositiveTimeDelta
from ceres.database import Database
from ceres.internal.database.entities import AlertEntity, ComponentEntity, MessageEntity
from ceres.internal.utilities import ValidateByType, escape_like_expression
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
    source: Address | Sequence[Address] | None
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    direction: MessageDirection | None
    prefix: bytes | None
    suffix: bytes | None
    order: MessageOrder | None
    limit: int | None
    offset: int | None


class MessageQuery(Query):
    source: Address | Sequence[Address] | None = None
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    direction: MessageDirection | None = None
    prefix: bytes | None = None
    suffix: bytes | None = None
    order: MessageOrder | None = None
    limit: int | None = Field(None, ge=0)
    offset: int | None = Field(None, ge=0)


class AlertOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


_StrPattern = Pattern[str] if TYPE_CHECKING else Pattern


class AlertQueryArgs(TypedDict, total=False):
    source: Address | Sequence[Address] | None
    search: str | None
    search_case_sensitive: bool
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: AlertLevel | Sequence[AlertLevel] | None
    code: str | Sequence[str] | None
    code_regex: str | _StrPattern | None
    order: AlertOrder | None
    limit: int | None
    offset: int | None


class AlertQuery(Query):
    source: Address | Sequence[Address] | None = None
    search: str | None = None
    search_case_sensitive: bool = False
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: AlertLevel | Sequence[AlertLevel] | None = None
    code: str | Sequence[str] | None = None
    code_regex: str | _StrPattern | None = None
    order: AlertOrder | None = None
    limit: int | None = None
    offset: int | None = None


class StatisticsQueryArgs(TypedDict, total=False):
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None


class StatisticsQuery(Query):
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None


class AlertLevelStatistics(ImmutableDataObject):
    level: AlertLevel
    count: int = Field(ge=0)


class AlertStatistics(ImmutableDataObject):
    count: int
    levels: Sequence[AlertLevelStatistics]


class ComponentStatistics(ImmutableDataObject):
    alerts: AlertStatistics


class UnitStatistics(ImmutableDataObject):
    alerts: AlertStatistics
    components: Mapping[Name, ComponentStatistics] = Field(default_factory=dict)


class Statistics(ImmutableDataObject):
    alerts: AlertStatistics
    units: Mapping[Name, UnitStatistics] = Field(default_factory=dict)


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

    @property
    def database(self) -> Database:
        return self.__database

    async def assign_address_id(
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
                id = await (
                    session.scalar(
                        select(ComponentEntity.id).where(ComponentEntity.address == address),
                    )
                )

            if id is None:
                id = default or uuid4()
                component = ComponentEntity(
                    id=id,
                    address=address,
                )

                session.add(component)
                await session.commit()

            mapping[address] = id
            return id

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

        if query.source is not None:
            if isinstance(query.source, Address):
                statement = statement.where(MessageEntity.source == query.source)
            else:
                statement = statement.where(MessageEntity.source.in_(query.source))

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

        if query.source is not None:
            if isinstance(query.source, Address):
                statement = statement.where(AlertEntity.source == query.source)
            else:
                statement = statement.where(AlertEntity.source.in_(query.source))

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
            if isinstance(query.level, AlertLevel):
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

    async def get_statistics(
        self,
        query: StatisticsQuery | None = None,
        **kwargs: Unpack[StatisticsQueryArgs],
    ) -> Statistics:
        statement = (
            select(
                ComponentEntity.address.label("source"),
                AlertEntity.level,
                func.count("*").label("count"),
            )
            .join(ComponentEntity)
            .group_by(
                ComponentEntity.address.label("source"),
                AlertEntity.level,
            )
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

        alert_counts_by_level: defaultdict[AlertLevel, int] = defaultdict(int)
        unit_alert_counts_by_level: defaultdict[Name, defaultdict[AlertLevel, int]] = defaultdict(
            lambda: defaultdict(int),
        )
        component_alert_counts_by_level: defaultdict[
            Name,
            defaultdict[Name, defaultdict[AlertLevel, int]],
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


def _sqlite_format_timestamp(timestamp: SQLCoreOperations[datetime]) -> Any:
    return func.strftime(
        "%Y-%m-%d %H:%M:%f",
        func.julianday(timestamp),
    )


def _pg_format_timestamp(timestamp: SQLCoreOperations[datetime]) -> Any:
    return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.MS")
