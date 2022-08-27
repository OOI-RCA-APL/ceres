from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import Field

from .data import DataObject
from .database.entity import MessageDirection as EntityMessageDirection
from .database.entity import MessageEntity, eid

MessageDirection = EntityMessageDirection


class Message(DataObject):
    class Config:
        orm_mode = True

    id: UUID = Field(default_factory=eid)
    connection_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    direction: MessageDirection
    content: str

    @staticmethod
    def from_entity(entity: MessageEntity) -> Message:
        return Message.from_orm(entity)
