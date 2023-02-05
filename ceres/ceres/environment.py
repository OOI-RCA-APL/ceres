from enum import Enum
from re import Pattern
from typing import TYPE_CHECKING, Any, Callable, Sequence, TypedDict
from uuid import UUID, uuid4

from pydantic import Extra
from sqlalchemy import BinaryExpression, ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import Self, Unpack

from .address import Address
from .alert import Alert, AlertLevel
from .config import DatabaseKind
from .data import DateTime, ImmutableDataObject, PositiveTimeDelta
from .database import Database
from .internal.database.entities import AlertEntity, ComponentEntity, MessageEntity
from .internal.utilities import ValidateByType, escape_like_expression
from .message import Message, MessageDirection
from .timing import utc

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

        for attribute in self.__fields__.keys():
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
    limit: int | None = None


class AlertOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


if TYPE_CHECKING:
    _StrPattern = Pattern[str]
else:
    _StrPattern = Pattern


class AlertQueryArgs(TypedDict, total=False):
    source: Address | Sequence[Address] | None
    within: PositiveTimeDelta | None
    after: DateTime | None
    before: DateTime | None
    level: AlertLevel | Sequence[AlertLevel] | None
    code: str | Sequence[str] | None
    code_regex: str | _StrPattern | None
    order: AlertOrder | None
    limit: int | None


class AlertQuery(Query):
    source: Address | Sequence[Address] | None = None
    within: PositiveTimeDelta | None = None
    after: DateTime | None = None
    before: DateTime | None = None
    level: AlertLevel | Sequence[AlertLevel] | None = None
    code: str | Sequence[str] | None = None
    code_regex: str | _StrPattern | None = None
    order: AlertOrder | None = None
    limit: int | None = None


class Environment(ValidateByType):
    def __init__(
        self,
        *,
        database: Database | None = None,
    ) -> None:
        if database is None:
            database = Database()

        self.__database = database

    @property
    def database(self) -> Database:
        return self.__database

    async def get_component_id(
        self,
        address: Address,
        default: UUID | None = None,
    ) -> UUID:
        async with self.__database.session() as session:
            if not (
                component := await (
                    session.scalar(
                        select(ComponentEntity).where(ComponentEntity.address == address)
                    )
                )
            ):
                component = ComponentEntity(
                    id=default or uuid4(),
                    address=address,
                )
                session.add(component)
                await session.commit()

            return component.id

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
                        _like(MessageEntity.timestamp, pattern, query.search_case_sensitive)
                        | _like(MessageEntity.direction, pattern, query.search_case_sensitive)
                        | _like(
                            MessageEntity.content,
                            pattern.encode("utf-8"),
                            query.search_case_sensitive,
                        )
                    )
                case DatabaseKind.POSTGRES:
                    statement = statement.where(
                        _like(
                            func.to_char(MessageEntity.timestamp, "YYYY-MM-DD HH24:MI:SS.MS"),
                            pattern,
                            query.search_case_sensitive,
                        )
                        | _like(MessageEntity.direction, pattern, query.search_case_sensitive)
                        | _like(
                            func.encode(MessageEntity.content, "escape"),
                            pattern.encode("utf-8").decode("unicode-escape"),
                            query.search_case_sensitive,
                        )
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
                MessageEntity.content.like(escape_like_expression(query.prefix + b"%"))
            )
        if query.suffix is not None:
            statement = statement.where(
                MessageEntity.content.like(escape_like_expression(b"%" + query.suffix))
            )

        if query.order is not None:
            match query.order:
                case MessageOrder.OLD_TO_NEW:
                    statement = statement.order_by(MessageEntity.timestamp)
                case MessageOrder.NEW_TO_OLD:
                    statement = statement.order_by(MessageEntity.timestamp.desc())

        if query.limit is not None:
            statement = statement.limit(query.limit)

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

        if where is not None:
            statement = statement.where(where(AlertEntity))
        if order_by is not None:
            statement = statement.order_by(order_by(AlertEntity))

        if query.order is None and order_by is None:
            statement = statement.order_by(AlertEntity.timestamp)

        async with self.__database.session() as session:
            rows = await session.execute(statement)

        return [Alert.construct(**row._asdict()) for row in rows]  # type: ignore


def _like(
    expression: ColumnElement[Any] | InstrumentedAttribute[Any],
    pattern: str | bytes,
    case_sensitive: bool = False,
) -> BinaryExpression[bool]:
    if case_sensitive:
        return expression.like(pattern)
    return expression.ilike(pattern)
