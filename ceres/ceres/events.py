from datetime import datetime
from typing import Literal

from pydantic import Field

from .address import ComponentAddress
from .alert import Alert
from .data import ImmutableDataObject
from .datetime import utc
from .message import Message


class Event(ImmutableDataObject):
    kind: str
    address: ComponentAddress
    timestamp: datetime = Field(default_factory=utc)


class ConnectedEvent(Event):
    kind: Literal["connected"] = "connected"


class DisconnectedEvent(Event):
    kind: Literal["disconnected"] = "disconnected"


class MessageSentEvent(Event):
    kind: Literal["message-sent"] = "message-sent"
    message: Message


class MessageReceivedEvent(Event):
    kind: Literal["message-received"] = "message-received"
    message: Message


class AlertEmittedEvent(Event):
    kind: Literal["alert-emitted"] = "alert-emitted"
    alert: Alert
