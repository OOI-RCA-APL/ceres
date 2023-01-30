from datetime import datetime, timedelta
from enum import Enum
from re import Pattern
from typing import Any, Callable, Sequence
from uuid import UUID, uuid4

from pydantic import validator
from sqlalchemy import BinaryExpression, ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.roles import ExpressionElementRole

from .address import ComponentAddress
from .alert import Alert, AlertLevel
from .config import DatabaseKind
from .data import ImmutableDataObject
from .database import Database
from .database.entity import AlertEntity, ComponentEntity, MessageEntity
from .datetime import utc
from .internal.utilities import (
    ValidateByType,
    escape_like_expression,
    validate_positive_timedelta,
)
from .message import Message, MessageDirection

WhereExpression = ColumnElement[bool] | ExpressionElementRole[bool]
OrderByExpression = ColumnElement[Any] | ExpressionElementRole[Any]


class MessageOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class MessageQuery(ImmutableDataObject):
    source: ComponentAddress | Sequence[ComponentAddress] | None = None
    search: str | None = None
    search_case_sensitive: bool = False
    within: timedelta | None = None
    after: datetime | None = None
    before: datetime | None = None
    direction: MessageDirection | None = None
    prefix: bytes | None = None
    suffix: bytes | None = None

    order: MessageOrder | None = None
    limit: int | None = None

    @validator("within", pre=True)
    def _validate_within(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class AlertOrder(str, Enum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class AlertQuery(ImmutableDataObject):
    source: ComponentAddress | Sequence[ComponentAddress] | None = None
    within: timedelta | None = None
    after: datetime | None = None
    before: datetime | None = None
    levels: Sequence[AlertLevel] | None = None
    codes: Sequence[str] | None = None
    code_regex: str | Pattern[str] | None = None

    order: AlertOrder = AlertOrder.OLD_TO_NEW
    limit: int | None = None

    @validator("within", pre=True)
    def _validate_within(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


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
        address: ComponentAddress,
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
        order_by: Callable[[type[MessageEntity]], OrderByExpression]
        | None = lambda message: message.timestamp,
    ) -> list[Message]:
        statement = select(
            MessageEntity.id,
            ComponentEntity.address.label("source"),
            MessageEntity.timestamp,
            MessageEntity.direction,
            MessageEntity.content,
        ).join(ComponentEntity)

        if query is not None:
            if query.source is not None:
                if isinstance(query.source, ComponentAddress):
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

        if (query is None or query.order is None) and order_by is None:
            statement = statement.order_by(MessageEntity.timestamp)

        async with self.__database.session() as session:
            rows = await session.execute(statement)

        return [Message.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_alerts(
        self,
        query: AlertQuery | None = None,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression]
        | None = lambda alert: alert.timestamp,
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
            if query.source is not None:
                if isinstance(query.source, ComponentAddress):
                    statement = statement.where(AlertEntity.source == query.source)
                else:
                    statement = statement.where(AlertEntity.source.in_(query.source))
            if query.within is not None:
                statement = statement.where(AlertEntity.timestamp >= utc() - query.within)
            if query.after is not None:
                statement = statement.where(AlertEntity.timestamp >= query.after)
            if query.before is not None:
                statement = statement.where(AlertEntity.timestamp < query.before)
            if query.levels is not None:
                statement = statement.where(AlertEntity.level.in_(query.levels))
            if query.codes is not None:
                statement = statement.where(AlertEntity.code.in_(query.codes))
            if query.code_regex is not None:
                statement = statement.where(AlertEntity.code.regexp_match(query.code_regex))

            if query.order is not None:
                order = query.order if query.order is not None else AlertOrder.OLD_TO_NEW
                match order:
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

        if (query is None or query.order is None) and order_by is None:
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
