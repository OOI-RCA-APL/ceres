from enum import Enum
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import AbsoluteAddress
from ceres.data import DateTime, ImmutableDataObject
from ceres.timing import utc


class MessageDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


class Message(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    address: AbsoluteAddress
    timestamp: DateTime = Field(default_factory=utc)
    direction: MessageDirection
    content: bytes
