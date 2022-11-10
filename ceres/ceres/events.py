from dataclasses import field
from datetime import datetime
from typing import Literal

from .address import ComponentAddress
from .alert import Alert
from .message import Message
from .utilities import utc, vdc


@vdc(frozen=True)
class Event:
    kind: str
    address: ComponentAddress
    timestamp: datetime = field(default_factory=utc)


@vdc(frozen=True)
class ConnectedEvent(Event):
    kind: Literal["connected"] = "connected"


@vdc(frozen=True)
class DisconnectedEvent(Event):
    kind: Literal["disconnected"] = "disconnected"


@vdc(frozen=True)
class MessageSentEvent(Event):
    kind: Literal["message-sent"] = "message-sent"
    message: Message


@vdc(frozen=True)
class MessageReceivedEvent(Event):
    kind: Literal["message-received"] = "message-received"
    message: Message


@vdc(frozen=True)
class AlertEmittedEvent(Event):
    kind: Literal["alert-emitted"] = "alert-emitted"
    alert: Alert
