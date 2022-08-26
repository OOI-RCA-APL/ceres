from datetime import datetime
from typing import TYPE_CHECKING, List, Literal, Optional
from uuid import UUID, uuid4

import sqlalchemy as sql
from sqlalchemy import TIMESTAMP, Column, ForeignKey, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy_utils import UUIDType

from ..path import ConnectionPath, UnitPath

if TYPE_CHECKING:
    from .base import DatabaseManager

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

    connections: List["ConnectionEntity"] = relationship("ConnectionEntity", back_populates="unit")


class ConnectionEntity(Entity):
    __tablename__ = "connections"
    unit_id: UUID = Column(UUIDType(binary=False), ForeignKey("units.id"))
    name: str = Column(String)

    unit: UnitEntity = relationship(UnitEntity, back_populates="connections")


MessageDirection = Literal["send", "receive"]


class MessageEntity(Entity):
    __tablename__ = "messages"
    connection_id: UUID = Column(UUIDType(binary=False), ForeignKey("connections.id"))
    timestamp: datetime = Column(TIMESTAMP(timezone=True))
    direction: MessageDirection = Column(String)
    content: str = Column(String)


class EntityManager:
    def __init__(self, database: "DatabaseManager") -> None:
        self._database = database

    async def get_unit_id(self, path: UnitPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_unit(session, path)).id

    async def get_connection_id(self, path: ConnectionPath) -> UUID:
        async with self._database.session() as session:
            return (await self._get_connection(session, path)).id

    async def _get_unit(
        self,
        session: AsyncSession,
        path: UnitPath,
    ) -> UnitEntity:
        unit: Optional[UnitEntity] = (
            await (session.execute(sql.select(UnitEntity).where(UnitEntity.name == path.unit)))
        ).scalar()

        if not unit:
            unit = UnitEntity(id=eid(), name=path.unit)
            session.add(unit)
            await session.commit()

        return unit

    async def _get_connection(
        self,
        session: AsyncSession,
        path: ConnectionPath,
    ) -> ConnectionEntity:
        unit_id = await self.get_unit_id(UnitPath.create(path.unit))

        connection: Optional[ConnectionEntity] = (
            await (
                session.execute(
                    sql.select(ConnectionEntity).where(
                        sql.and_(
                            ConnectionEntity.unit_id == unit_id,
                            ConnectionEntity.name == path.connection,
                        )
                    )
                )
            )
        ).scalar()

        if not connection:
            connection = ConnectionEntity(
                id=eid(),
                unit_id=unit_id,
                name=path.connection,
            )
            session.add(connection)
            await session.commit()

        return connection
