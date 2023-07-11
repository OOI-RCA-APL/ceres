from abc import ABC
from enum import Enum
from typing import TYPE_CHECKING, Literal, cast, final
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import Address
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.timing import utc


class StandardEventKind(str, Enum):
    STARTED = "started"
    STOPPED = "stopped"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTION_LOST = "connection-lost"
    CONNECT_FAILED = "connect-failed"
    MESSAGE_SENT = "message-sent"
    MESSAGE_RECEIVED = "message-received"
    ALERT = "alert"
    LOG = "log"


class Event(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)

    if TYPE_CHECKING:
        address: Address = cast(Address, None)
    else:
        address: Address

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
class AlertEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ALERT] = StandardEventKind.ALERT
    alert: Alert


@final
class LogEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.LOG] = StandardEventKind.LOG
    entry: LogEntry


StandardEvent = (
    StartedEvent
    | StoppedEvent
    | ConnectedEvent
    | DisconnectedEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
    | MessageSentEvent
    | MessageReceivedEvent
    | AlertEvent
    | LogEvent
)
