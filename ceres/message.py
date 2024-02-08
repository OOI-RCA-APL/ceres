from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BeforeValidator, Field, PlainSerializer
from typing_extensions import TypedDict

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject
from ceres.internal.cli.plumbing import CLIOption
from ceres.internal.utilities import StrEnum
from ceres.timing import utc


class MessageDirection(StrEnum):
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
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    address: Annotated[Address, CLIOption(str)]
    timestamp: Annotated[DateTime, CLIOption(datetime)] = Field(default_factory=utc)
    direction: Annotated[MessageDirection, CLIOption(MessageDirection)]
    content: Annotated[MessageContent, CLIOption(str)]


class MessageUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    direction: MessageDirection
    content: MessageContent
