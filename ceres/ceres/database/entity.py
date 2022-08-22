from datetime import datetime
from typing import TYPE_CHECKING, List, Literal, Optional
from uuid import UUID, uuid4

import sqlalchemy as sql
from sqlalchemy import TIMESTAMP, Column, ForeignKey, String
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy_utils import UUIDType

from ..path import ConnectionPath, UnitPath

if TYPE_CHECKING:
    from . import Database

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
    __tablename__ = "unit"
    name: str = Column(String)

    connections: List["ConnectionEntity"] = relationship("ConnectionEntity", back_populates="unit")


class ConnectionEntity(Entity):
    __tablename__ = "connection"
    unit_id: UUID = Column(UUIDType(binary=False), ForeignKey("unit.id"))
    name: str = Column(String)

    unit: UnitEntity = relationship(UnitEntity, back_populates="connections")


MessageDirection = Literal["send", "receive"]


class MessageEntity(Entity):
    __tablename__ = "message"
    connection_id: UUID = Column(UUIDType(binary=False), ForeignKey("connection.id"))
    timestamp: datetime = Column(TIMESTAMP(timezone=True))
    direction: MessageDirection = Column(String)
    content: str = Column(String)


class EntityManager:
    def __init__(self, database: "Database") -> None:
        self._database = database

    async def get_unit(self, path: UnitPath) -> UnitEntity:
        async with self._database.session() as session:
            unit: Optional[UnitEntity] = (
                await (session.execute(sql.select(UnitEntity).where(UnitEntity.name == path.unit)))
            ).scalar()

            if not unit:
                unit = UnitEntity(id=eid(), name=path.unit)
                session.add(unit)
                await session.commit()

            return unit

    async def get_connection(self, path: ConnectionPath) -> ConnectionEntity:
        async with self._database.session() as session:
            connection: Optional[ConnectionEntity] = (
                await (
                    session.execute(
                        sql.select(ConnectionEntity).where(ConnectionEntity.name == path.connection)
                    )
                )
            ).scalar()

            if not connection:
                unit: Optional[UnitEntity] = (
                    await (
                        session.execute(sql.select(UnitEntity).where(UnitEntity.name == path.unit))
                    )
                ).scalar()

                if not unit:
                    unit = UnitEntity(
                        id=eid(),
                        name=path.unit,
                    )
                    session.add(unit)

                connection = ConnectionEntity(
                    id=eid(),
                    unit=unit,
                    name=path.unit,
                )
                session.add(connection)
                await session.commit()

            return connection

    async def get_unit_id(self, path: UnitPath) -> UUID:
        return (await self.get_unit(path)).id

    async def get_connection_id(self, path: ConnectionPath) -> UUID:
        return (await self.get_connection(path)).id
