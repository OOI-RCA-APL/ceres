import dataclasses
from datetime import datetime
from enum import Enum as BaseEnum
from typing import TYPE_CHECKING, Any, Callable, TypeVar, final
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    CheckConstraint,
    ColumnElement,
    Dialect,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    Result,
    Text,
    TypeDecorator,
    Uuid,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    declared_attr,
    mapped_column,
    relationship,
)
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import Self

from ..address import ComponentAddress
from ..alert import Alert, AlertLevel
from ..internal.utilities import snakecase
from ..message import Message, MessageDirection

if TYPE_CHECKING:
    from . import Database
else:
    Database = "DatabaseManager"


def _TypedEnum(cls: type[BaseEnum]) -> Enum:
    enum = Enum(
        *(current.value for current in cls),
        native_enum=False,
        create_constraint=False,
        name=snakecase(cls.__name__),
    )

    enum.length = None
    return enum


def _TypedEnumConstraint(column: str, cls: type[BaseEnum], name: str) -> CheckConstraint:
    return CheckConstraint(
        sqltext=f"{column} in ({', '.join([repr(enum.value) for enum in cls])})",
        name=name,
    )


class ComponentAddressMapper(TypeDecorator[ComponentAddress]):
    impl = Text
    cache_ok = False

    def process_bind_param(
        self,
        value: ComponentAddress | None,
        dialect: Dialect,
    ) -> str | None:
        if value is None:
            return None

        return str(value)

    def process_result_value(
        self,
        value: ComponentAddress | None,
        dialect: Dialect,
    ) -> ComponentAddress | None:
        if value is None:
            return None

        return ComponentAddress(value)

    def copy(self, **kwargs: Any) -> Self:
        return type(self)(**kwargs)


class Entity(MappedAsDataclass, DeclarativeBase):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    def values(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@final
class ComponentEntity(Entity):
    __tablename__ = "components"
    id: Mapped[UUID] = mapped_column(Uuid)
    address: Mapped[ComponentAddress] = mapped_column(ComponentAddressMapper)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        Index(f"uq_{__tablename__}__address", "address", unique=True),
    )


@final
class MessageEntity(Entity):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid)
    component_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(ComponentEntity.id, name=f"fk_{__tablename__}__component_id__components"),
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    direction: Mapped[MessageDirection] = mapped_column(_TypedEnum(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @declared_attr
    def component(cls) -> Mapped[ComponentEntity]:
        return relationship(ComponentEntity)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        _TypedEnumConstraint("direction", MessageDirection, name=f"ck_{__tablename__}__direction"),
        Index(f"ix_{__tablename__}__component_id", "component_id"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__content", "content"),
    )


@final
class AlertEntity(Entity):
    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(Uuid)
    component_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(ComponentEntity.id, name=f"fk_{__tablename__}__component_id__components"),
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    level: Mapped[AlertLevel] = mapped_column(_TypedEnum(AlertLevel))
    code: Mapped[str] = mapped_column(Text)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    @declared_attr
    def component(cls) -> Mapped[ComponentEntity]:
        return relationship(ComponentEntity)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        _TypedEnumConstraint("level", AlertLevel, name=f"ck_{__tablename__}__level"),
        Index(f"ix_{__tablename__}__component_id", "component_id"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__level", "level"),
        Index(f"ix_{__tablename__}__code", "code"),
    )


_EntityT = TypeVar("_EntityT", bound=Entity)
WhereExpression = ColumnElement[bool] | ExpressionElementRole[bool]
OrderByExpression = ColumnElement[Any] | ExpressionElementRole[Any]


@final
class EntityManager:
    def __init__(self, database: Database) -> None:
        self.__database = database

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
        *,
        where: Callable[[type[MessageEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[MessageEntity]], OrderByExpression]
        | None = lambda message: message.timestamp,
        limit: int | None = None,
    ) -> list[Message]:
        rows = await self.__get_entity_rows(
            MessageEntity,
            where=where,
            order_by=order_by,
            limit=limit,
        )

        return [Message.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_alerts(
        self,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression]
        | None = lambda alert: alert.timestamp,
        limit: int | None = None,
    ) -> list[Alert]:
        rows = await self.__get_entity_rows(
            AlertEntity,
            where=where,
            order_by=order_by,
            limit=limit,
        )

        return [Alert.construct(**row._asdict()) for row in rows]  # type: ignore

    async def __get_entity_rows(
        self,
        cls: type[_EntityT],
        *,
        where: Callable[[type[_EntityT]], WhereExpression] | None = None,
        order_by: Callable[[type[_EntityT]], OrderByExpression] | None = None,
        limit: int | None = None,
    ) -> Result[Any]:
        query = select(*cls.__table__.columns)
        if where is not None:
            query = query.where(where(cls))
        if order_by is not None:
            query = query.order_by(order_by(cls))
        if limit is not None:
            query = query.limit(limit)

        async with self.__database.session() as session:
            return await session.execute(query)
