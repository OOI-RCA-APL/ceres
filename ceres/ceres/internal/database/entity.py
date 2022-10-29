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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ...address import Address, ComponentAddress, UnitAddress
from ...alert import AlertLevel
from ...message import MessageDirection

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

    components: Mapped[list[ComponentEntity]] = relationship(
        "ComponentEntity",
        back_populates="unit",
    )


class ComponentEntity(Entity):
    __tablename__ = "components"
    id: Mapped[UUID] = mapped_column(Uuid)
    unit_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(UnitEntity.id, name=f"fk_{__tablename__}__unit_id__units"),
    )

    name: Mapped[str] = mapped_column(String)

    unit: Mapped[UnitEntity] = relationship(UnitEntity, back_populates=__tablename__)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        Index(f"uq_{__tablename__}__unit_id__name", "unit_id", "name", unique=True),
    )


class MessageEntity(Entity):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(Uuid)
    connection_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(ComponentEntity.id, name=f"fk_{__tablename__}__connection_id__connection"),
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
    level: Mapped[AlertLevel] = mapped_column(TypedEnum(AlertLevel))
    kind: Mapped[str] = mapped_column(String)
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        PrimaryKeyConstraint("id", name=f"pk_{__tablename__}"),
        TypedEnumConstraint("level", AlertLevel, name=f"ck_{__tablename__}__level"),
        Index(f"ix_{__tablename__}__origin_id", "origin_id"),
        Index(f"ix_{__tablename__}__timestamp", "timestamp"),
        Index(f"ix_{__tablename__}__level", "level"),
        Index(f"ix_{__tablename__}__kind", "kind"),
    )


ComponentEntityT = TypeVar("ComponentEntityT", bound=ComponentEntity)


class EntityManager:
    def __init__(self, database: "DatabaseManager") -> None:
        self._database = database

    async def get_id(self, address: Address) -> UUID:
        async with self._database.session() as session:
            match address:
                case UnitAddress():
                    return (await self._get_unit(session, address)).id
                case ComponentAddress():
                    return (await self._get_component(session, address)).id

    async def _get_unit(
        self,
        session: AsyncSession,
        address: UnitAddress,
    ) -> UnitEntity:
        if not (
            unit := await session.scalar(select(UnitEntity).where(UnitEntity.name == address.name))
        ):
            unit = UnitEntity(
                id=uuid4(),
                name=address.name,
            )
            session.add(unit)
            await session.commit()

        return unit

    async def _get_component(
        self,
        session: AsyncSession,
        address: ComponentAddress,
    ) -> ComponentEntity:
        unit_id = (await self._get_unit(session, UnitAddress(address.unit))).id

        if not (
            component := await (
                session.scalar(
                    select(ComponentEntity).where(
                        (ComponentEntity.unit_id == unit_id)
                        & (ComponentEntity.name == address.name)
                    )
                )
            )
        ):
            component = ComponentEntity(
                id=uuid4(),
                unit_id=unit_id,
                name=address.name,
            )
            session.add(component)
            await session.commit()

        return component
