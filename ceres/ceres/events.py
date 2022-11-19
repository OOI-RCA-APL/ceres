from datetime import datetime

from pydantic import Field

from .address import ComponentAddress
from .alert import Alert
from .data import ImmutableDataObject
from .datetime import utc
from .message import Message


class Event(ImmutableDataObject):
    address: ComponentAddress
    timestamp: datetime = Field(default_factory=utc)


class ConnectedEvent(Event):
    pass


class DisconnectedEvent(Event):
    pass


class MessageSentEvent(Event):
    message: Message


class MessageReceivedEvent(Event):
    message: Message


class AlertEmittedEvent(Event):
    alert: Alert
