from abc import ABC
from datetime import datetime
from enum import Enum
from typing import Literal, cast, final
from uuid import UUID, uuid4

from pydantic import Field

from .address import ComponentAddress
from .alert import Alert
from .data import ImmutableDataObject
from .message import Message
from .timing import utc


class Event(ImmutableDataObject, ABC):
    id: UUID = Field(default_factory=uuid4)
    source: ComponentAddress = cast(ComponentAddress, None)
    timestamp: datetime = Field(default_factory=utc)
    kind: str


class StandardEventKind(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTION_LOST = "connection-lost"
    CONNECT_FAILED = "connect-failed"
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
class ConnectionLostEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECTION_LOST] = StandardEventKind.CONNECTION_LOST


@final
class ConnectFailedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECT_FAILED] = StandardEventKind.CONNECT_FAILED


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
