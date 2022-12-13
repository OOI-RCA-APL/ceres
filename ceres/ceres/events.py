from abc import ABC
from datetime import datetime
from enum import Enum
from typing import Literal, final
from uuid import UUID, uuid4

from pydantic import Field

from .alert import Alert
from .data import ImmutableDataObject
from .datetime import utc
from .message import Message


class Event(ImmutableDataObject, ABC):
    id: UUID = Field(default_factory=uuid4)
    component_id: UUID = UUID(int=0)
    timestamp: datetime = Field(default_factory=utc)
    kind: str


class StandardEventKind(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    MESSAGE_SENT = "message-sent"
    MESSAGE_RECEIVED = "message-received"
    ALERT_EMITTED = "alert-emitted"


class BaseStandardEvent(Event, ABC):
    kind: StandardEventKind


@final
class ConnectedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECTED] = StandardEventKind.CONNECTED


@final
class DisconnectedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.DISCONNECTED] = StandardEventKind.DISCONNECTED


@final
class MessageSentEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.MESSAGE_SENT] = StandardEventKind.MESSAGE_SENT
    message: Message


@final
class MessageReceivedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.MESSAGE_RECEIVED] = StandardEventKind.MESSAGE_RECEIVED
    message: Message


@final
class AlertEmittedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ALERT_EMITTED] = StandardEventKind.ALERT_EMITTED
    alert: Alert
