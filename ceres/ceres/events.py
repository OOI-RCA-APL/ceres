from dataclasses import field
from datetime import datetime
from typing import Literal

from .address import ComponentAddress
from .alert import Alert
from .message import Message
from .utilities import VDC, utc


class Event(VDC, frozen=True):
    kind: str
    address: ComponentAddress
    timestamp: datetime = field(default_factory=utc)


class ConnectedEvent(Event, frozen=True):
    kind: Literal["connected"] = "connected"


class DisconnectedEvent(Event, frozen=True):
    kind: Literal["disconnected"] = "disconnected"


class MessageSentEvent(Event, frozen=True):
    kind: Literal["message-sent"] = "message-sent"
    message: Message


class MessageReceivedEvent(Event, frozen=True):
    kind: Literal["message-received"] = "message-received"
    message: Message


class AlertEmittedEvent(Event, frozen=True):
    kind: Literal["alert-emitted"] = "alert-emitted"
    alert: Alert
