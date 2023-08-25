from enum import Enum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BeforeValidator, Field, PlainSerializer

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject
from ceres.timing import utc


class MessageDirection(str, Enum):
    SEND = "send"
    RECEIVE = "receive"


def _serialize_message_content_json(value: bytes) -> str:
    return value.decode("latin-1")


def _deserialize_message_content_json(value: Any) -> Any | None:
    if isinstance(value, str):
        return value.encode("latin-1", "replace")

    return value


MessageContent = Annotated[
    bytes,
    BeforeValidator(_deserialize_message_content_json),
    PlainSerializer(_serialize_message_content_json, str, "json-unless-none"),
]


class Message(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    address: Address
    timestamp: DateTime = Field(default_factory=utc)
    direction: MessageDirection
    content: MessageContent
