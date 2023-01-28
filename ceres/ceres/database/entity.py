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
    Text,
    TypeDecorator,
    Uuid,
    select,
)
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
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


class Entity(DeclarativeBase):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    def values(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__table__.columns.keys()}


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

    component: Mapped[ComponentEntity] = relationship(ComponentEntity, lazy="joined")
    source: AssociationProxy[ComponentAddress] = association_proxy("component", "address")

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

    component = relationship(ComponentEntity, lazy="joined")
    source: AssociationProxy[ComponentAddress] = association_proxy("component", "address")

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
        *,
        where: Callable[[type[MessageEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[MessageEntity]], OrderByExpression]
        | None = lambda message: message.timestamp,
        limit: int | None = None,
    ) -> list[Message]:
        query = select(
            MessageEntity.id,
            ComponentEntity.address.label("source"),
            MessageEntity.timestamp,
            MessageEntity.direction,
            MessageEntity.content,
        ).join(ComponentEntity)

        if where is not None:
            query = query.where(where(MessageEntity))
        if order_by is not None:
            query = query.order_by(order_by(MessageEntity))
        if limit is not None:
            query = query.limit(limit)

        async with self.__database.session() as session:
            rows = await session.execute(query)

        return [Message.construct(**row._asdict()) for row in rows]  # type: ignore

    async def get_alerts(
        self,
        *,
        where: Callable[[type[AlertEntity]], WhereExpression] | None = None,
        order_by: Callable[[type[AlertEntity]], OrderByExpression]
        | None = lambda alert: alert.timestamp,
        limit: int | None = None,
    ) -> list[Alert]:
        query = select(
            AlertEntity.id,
            ComponentEntity.address.label("source"),
            AlertEntity.timestamp,
            AlertEntity.level,
            AlertEntity.code,
            AlertEntity.info,
        ).join(ComponentEntity)

        if where is not None:
            query = query.where(where(AlertEntity))
        if order_by is not None:
            query = query.order_by(order_by(AlertEntity))
        if limit is not None:
            query = query.limit(limit)

        async with self.__database.session() as session:
            rows = await session.execute(query)

        return [Alert.construct(**row._asdict()) for row in rows]  # type: ignore
