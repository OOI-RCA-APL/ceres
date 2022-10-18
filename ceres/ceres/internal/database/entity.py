from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import BINARY, JSON, TIMESTAMP
from sqlalchemy import Enum as Enumeration
from sqlalchemy import ForeignKey, String, Uuid, select
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
from ...path import ComponentPath, ConnectionPath, DriverPath, NotifierPath, UnitPath

if TYPE_CHECKING:
    from .manager import DatabaseManager


class Entity(DeclarativeBase):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class UnitEntity(Entity):
    __tablename__ = "units"

    name: Mapped[str] = mapped_column(String)

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

    unit_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("units.id"))
    name: Mapped[str] = mapped_column(String)

    @declared_attr
    def unit(cls) -> Mapped[UnitEntity]:
        return relationship(UnitEntity, back_populates=cls.__tablename__)


class ConnectionEntity(ComponentEntity):
    __tablename__ = "connections"


class DriverEntity(ComponentEntity):
    __tablename__ = "drivers"


class NotifierEntity(ComponentEntity):
    __tablename__ = "notifiers"


class MessageEntity(Entity):
    __tablename__ = "messages"
    connection_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("connections.id"))
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    direction: Mapped[MessageDirection] = mapped_column(
        Enumeration(*(current.value for current in MessageDirection))
    )
    content: Mapped[bytes] = mapped_column(BINARY)


class AlertEntity(Entity):
    __tablename__ = "alerts"
    origin_id: Mapped[UUID] = mapped_column(Uuid)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True))
    kind: Mapped[str] = mapped_column(String)
    level: Mapped[AlertLevel] = mapped_column(
        Enumeration(*(current.value for current in AlertLevel))
    )
    info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


ComponentEntityT = TypeVar("ComponentEntityT", bound=ComponentEntity)


class EntityManager:
    def __init__(self, database: "DatabaseManager") -> None:
        self._database = database

    async def get_unit_id(self, path: UnitPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_unit(session, path)).id

    async def get_connection_id(self, path: ConnectionPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_component(session, ConnectionEntity, path)).id

    async def get_driver_id(self, path: DriverPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_component(session, DriverEntity, path)).id

    async def get_notifier_id(self, path: NotifierPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_component(session, NotifierEntity, path)).id

    async def get_component_id(self, path: ComponentPath) -> UUID:
        if path.kind == "connection":
            return await self.get_connection_id(path)
        if path.kind == "driver":
            return await self.get_driver_id(path)
        if path.kind == "notifier":
            return await self.get_notifier_id(path)

        raise ValueError(path)

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
        unit_id = await self.get_unit_id(UnitPath(path.unit))

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
