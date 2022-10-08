from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from .internal.database.entity import MessageDirection as MessageDirection
from .internal.database.entity import MessageEntity, eid


@dataclass(kw_only=True, frozen=True)
class Message:
    id: UUID = field(default_factory=eid)
    connection_id: UUID
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    direction: MessageDirection
    content: bytes

    @staticmethod
    def from_entity(entity: MessageEntity) -> Message:
        return Message(
            id=entity.id,
            connection_id=entity.connection_id,
            timestamp=entity.timestamp,
            direction=entity.direction,
            content=entity.content,
        )
