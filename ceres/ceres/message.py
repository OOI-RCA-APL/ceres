from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field

from .internal.database.entity import MessageDirection as MessageDirection
from .internal.database.entity import MessageEntity, eid


class Message(BaseModel):
    class Config:
        orm_mode = True

    id: UUID = Field(default_factory=eid)
    connection_id: UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    direction: MessageDirection
    content: bytes

    @staticmethod
    def from_entity(entity: MessageEntity) -> Message:
        return Message.from_orm(entity)
