from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from .alert import Alert
from .data import ImmutableDataObject
from .datetime import utc
from .message import Message


class Event(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    component_id: UUID = UUID(int=0)
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
