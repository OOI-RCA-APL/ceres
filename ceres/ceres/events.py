from abc import ABC
from enum import Enum
from typing import Literal, cast, final
from uuid import UUID, uuid4

from pydantic import Field

from .address import Address
from .alert import Alert
from .data import DateTime, ImmutableDataObject
from .message import Message
from .timing import utc


class StandardEventKind(str, Enum):
    STARTED = "started"
    STOPPED = "stopped"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTION_LOST = "connection-lost"
    CONNECT_FAILED = "connect-failed"
    MESSAGE_SENT = "message-sent"
    MESSAGE_RECEIVED = "message-received"
    ALERT_EMITTED = "alert-emitted"


class Event(ImmutableDataObject, ABC):
    id: UUID = Field(default_factory=uuid4)
    source: Address = cast(Address, None)
    timestamp: DateTime = Field(default_factory=utc)
    kind: StandardEventKind | str


class BaseStandardEvent(Event, ABC):
    kind: StandardEventKind


@final
class StartedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.STARTED] = StandardEventKind.STARTED


@final
class StoppedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.STOPPED] = StandardEventKind.STOPPED


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


StandardEvent = (
    StartedEvent
    | StoppedEvent
    | ConnectedEvent
    | DisconnectedEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
    | MessageSentEvent
    | MessageReceivedEvent
    | AlertEmittedEvent
)
