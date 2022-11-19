from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol, Union, runtime_checkable
from uuid import UUID, uuid4

from pydantic import Field
from typing_extensions import Self

from .data import ImmutableDataObject
from .datetime import utc

if TYPE_CHECKING:
    from .internal.database.entity import MessageEntity


class MessageDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


@runtime_checkable
class MessageLike(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def connection_id(self) -> UUID:
        ...

    @property
    def timestamp(self) -> datetime:
        ...

    @property
    def direction(self) -> MessageDirection:
        ...

    @property
    def content(self) -> bytes:
        ...


class Message(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    connection_id: UUID
    timestamp: datetime = Field(default_factory=utc)
    direction: MessageDirection
    content: bytes

    @classmethod
    def create_from(cls, other: Union[MessageLike, "MessageEntity"]) -> Self:
        return cls(
            id=other.id,
            connection_id=other.connection_id,
            timestamp=other.timestamp,
            direction=other.direction,
            content=other.content,
        )
