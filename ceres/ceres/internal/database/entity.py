from __future__ import annotations

from datetime import datetime
from enum import Enum as BaseEnum
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID, uuid4

from inflection import underscore
from sqlalchemy import (
    JSON,
    TIMESTAMP,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    Uuid,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

from ...alert import AlertLevel
from ...message import MessageDirection
from ...path import (
    ComponentPath,
    ConnectionPath,
    DriverPath,
    NotifierPath,
    Path,
    UnitPath,
)

if TYPE_CHECKING:
    from .manager import DatabaseManager


def TypedEnum(cls: type[BaseEnum]) -> Enum:
    enum = Enum(
        *(current.value for current in cls),
        native_enum=False,
        create_constraint=False,
        name=underscore(cls.__name__),
    )

    enum.length = None
    return enum


def TypedEnumConstraint(column: str, cls: type[BaseEnum], name: str) -> CheckConstraint:
    return CheckConstraint(
        sqltext=f"{column} in ({', '.join([repr(enum.value) for enum in cls])})",
        name=name,
    )


class Entity(DeclarativeBase):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }


class UnitEntity(Entity):
    __tablename__ = "units"

    id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        Index(f"uq_{__tablename__}__name", "name", unique=True),
    )

    connections: Mapped[list[ConnectionEntity]] = relationship(
        "ConnectionEntity",
        back_populates="unit",
    )
    drivers: Mapped[list[DriverEntity]] = relationship(
        "DriverEntity",
        back_populates="unit",
    )
    notifiers: Mapped[list[NotifierEntity]] = relationship(
        "NotifierEntity",
        back_populates="unit",
    )


class ComponentEntity(Entity):
    __abstract__ = True

    @declared_attr
    def id(cls) -> Mapped[UUID]:
        return mapped_column(Uuid)

    @declared_attr
    def unit_id(cls) -> Mapped[UUID]:
        return mapped_column(
            Uuid,
            ForeignKey("units.id", name=f"fk_{cls.__tablename__}__unit_id__units"),
        )

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String)

    @declared_attr
    def unit(cls) -> Mapped[UnitEntity]:
        return relationship(UnitEntity, back_populates=cls.__tablename__)

    @declared_attr
    def __table_args__(cls) -> Any:
        return (
            PrimaryKeyConstraint("id", name=f"pk_{cls.__tablename__}"),
            Index(f"uq_{cls.__tablename__}__unit_id__name", "unit_id", "name", unique=True),
        )


class ConnectionEntity(ComponentEntity):
    __tablename__ = "connections"


class DriverEntity(ComponentEntity):
    __tablename__ = "drivers"


class NotifierEntity(ComponentEntity):
    __tablename__ = "notifiers"


class MessageEntity(Entity):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("connections.id", name=f"fk_{__tablename__}__connection_id__connection"),
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    direction: Mapped[MessageDirection] = mapped_column(TypedEnum(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        TypedEnumConstraint("direction", MessageDirection, name=f"ck_{__tablename__}__direction"),
        Index(f"ix_{__tablename__}__connection_id", "connection_id"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__content", "content"),
    )


class AlertEntity(Entity):
    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(Uuid)
    origin_id: Mapped[UUID] = mapped_column(Uuid)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    kind: Mapped[str] = mapped_column(String)
    level: Mapped[AlertLevel] = mapped_column(TypedEnum(AlertLevel))
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        TypedEnumConstraint("level", AlertLevel, name=f"ck_{__tablename__}__level"),
        Index(f"ix_{__tablename__}__origin_id", "origin_id"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__kind", "kind"),
        Index(f"ix_{__tablename__}__level", "level"),
    )


ComponentEntityT = TypeVar("ComponentEntityT", bound=ComponentEntity)


class EntityManager:
    def __init__(self, database: "DatabaseManager") -> None:
        self._database = database

    async def get_id(self, path: Path) -> UUID:
        async with self._database.session() as session:
            match path:
                case UnitPath():
                    return (await self._get_unit(session, path)).id
                case ConnectionPath():
                    return (await self._get_component(session, ConnectionEntity, path)).id
                case DriverPath():
                    return (await self._get_component(session, DriverEntity, path)).id
                case NotifierPath():
                    return (await self._get_component(session, NotifierEntity, path)).id

    async def _get_unit(
        self,
        session: AsyncSession,
        path: UnitPath,
    ) -> UnitEntity:
        if not (
            unit := await session.scalar(select(UnitEntity).where(UnitEntity.name == path.name))
        ):
            unit = UnitEntity(id=uuid4(), name=path.name)
            session.add(unit)
            await session.commit()

        return unit

    async def _get_component(
        self,
        session: AsyncSession,
        cls: type[ComponentEntityT],
        path: ComponentPath,
    ) -> ComponentEntity:
        unit_id = (await self._get_unit(session, UnitPath(path.unit))).id

        if not (
            component := await (
                session.scalar(
                    select(cls).where((cls.unit_id == unit_id) & (cls.name == path.name))
                )
            )
        ):
            component = cls(
                id=uuid4(),
                unit_id=unit_id,
                name=path.name,
            )
            session.add(component)
            await session.commit()

        return component
