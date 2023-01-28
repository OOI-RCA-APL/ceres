from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import Field

from .address import ComponentAddress
from .data import ImmutableDataObject
from .datetime import utc


class MessageDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


class Message(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    source: ComponentAddress
    timestamp: datetime = Field(default_factory=utc)
    direction: MessageDirection
    content: bytes
