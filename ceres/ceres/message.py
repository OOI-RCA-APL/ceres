from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4


class MessageDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


@runtime_checkable
class MessageLike(Protocol):
    @property
    def id(self) -> UUID:
        ...

    connection_id: UUID
    timestamp: datetime
    direction: MessageDirection
    content: bytes


@dataclass(kw_only=True, frozen=True)
class Message:
    id: UUID = field(default_factory=uuid4)
    connection_id: UUID
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    direction: MessageDirection
    content: bytes

    @staticmethod
    def create_from(other: MessageLike) -> Message:
        return Message(
            id=other.id,
            connection_id=other.connection_id,
            timestamp=other.timestamp,
            direction=other.direction,
            content=other.content,
        )
