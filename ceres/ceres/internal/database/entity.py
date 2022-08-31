from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, TypeVar, cast
from uuid import UUID, uuid4

import sqlalchemy as sql
from sqlalchemy import TIMESTAMP, Column
from sqlalchemy import Enum as StringEnum
from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Mapped, declarative_base, relationship
from sqlalchemy_utils import UUIDType

from ...path import ConnectionPath, DriverPath, UnitComponentPath, UnitPath

if TYPE_CHECKING:
    from .manager import DatabaseManager

BaseEntity = declarative_base()


def eid() -> UUID:
    return uuid4()


class Entity(BaseEntity):
    __abstract__ = True
    __mapper_args__ = {
        "eager_defaults": True,
    }

    id: UUID = Column(UUIDType(binary=False), primary_key=True)


class UnitEntity(Entity):
    __tablename__ = "units"
    name: str = Column(String)

    connections: list[ConnectionEntity] = relationship("ConnectionEntity", back_populates="unit")
    drivers: list[DriverEntity] = relationship("DriverEntity", back_populates="unit")


class ComponentEntity(Entity):
    __abstract__ = True


class UnitComponentEntity(ComponentEntity):
    __abstract__ = True

    @declared_attr
    def unit_id(cls) -> Mapped[UUID]:
        return Column(UUIDType(binary=False), ForeignKey("units.id"))

    name: str = Column(String)

    @declared_attr
    def unit(cls) -> relationship[UUID]:
        return relationship(UnitEntity, back_populates=cls.__tablename__)


class ConnectionEntity(UnitComponentEntity):
    __tablename__ = "connections"


class DriverEntity(UnitComponentEntity):
    __tablename__ = "drivers"


class MessageDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


class MessageEntity(Entity):
    __tablename__ = "messages"
    connection_id: UUID = Column(UUIDType(binary=False), ForeignKey("connections.id"))
    timestamp: datetime = Column(TIMESTAMP(timezone=True))
    direction: MessageDirection = Column(
        StringEnum(*[current.value for current in MessageDirection])
    )
    content: str = Column(String)


UnitComponentEntityT = TypeVar("UnitComponentEntityT", bound=UnitComponentEntity)


class EntityManager:
    def __init__(self, database: "DatabaseManager") -> None:
        self._database = database

    async def get_unit_id(self, path: UnitPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_unit(session, path)).id

    async def get_connection_id(self, path: ConnectionPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_unit_component(session, ConnectionEntity, path)).id

    async def get_driver_id(self, path: DriverPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_unit_component(session, DriverEntity, path)).id

    async def _get_unit(
        self,
        session: AsyncSession,
        path: UnitPath,
    ) -> UnitEntity:
        unit: UnitEntity | None = (
            await (session.execute(sql.select(UnitEntity).where(UnitEntity.name == path.unit)))
        ).scalar()

        if not unit:
            unit = UnitEntity(id=eid(), name=path.unit)
            session.add(unit)
            await session.commit()

        return unit

    async def _get_unit_component(
        self,
        session: AsyncSession,
        UnitComponentEntity: type[UnitComponentEntityT],
        path: UnitComponentPath,
    ) -> ComponentEntity:
        unit_id = await self.get_unit_id(UnitPath.create(path.unit))

        component = cast(
            UnitComponentEntityT | None,
            (
                await (
                    session.execute(
                        sql.select(UnitComponentEntity).where(
                            sql.and_(
                                UnitComponentEntity.unit_id == unit_id,
                                UnitComponentEntity.name == path.name,
                            )
                        )
                    )
                )
            ).scalar(),
        )

        if not component:
            component = UnitComponentEntity(  # type: ignore
                id=eid(),
                unit_id=unit_id,
                name=path.name,
            )
            session.add(component)
            await session.commit()

        return component
