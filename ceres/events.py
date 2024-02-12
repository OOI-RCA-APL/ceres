from abc import ABC
from typing import TYPE_CHECKING, Literal, Sequence, cast
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import Address
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.timing import utc


class Event(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)

    if TYPE_CHECKING:
        address: Address = cast(Address, None)
    else:
        address: Address

    timestamp: DateTime = Field(default_factory=utc)
    type: str


class __BaseStandardEvent(Event, ABC):
    pass


class StartedEvent(__BaseStandardEvent):
    type: Literal["started"] = "started"


class StoppingEvent(__BaseStandardEvent):
    type: Literal["stopping"] = "stopping"


class StoppedEvent(__BaseStandardEvent):
    type: Literal["stopped"] = "stopped"


class EnabledEvent(__BaseStandardEvent):
    type: Literal["enabled"] = "enabled"


class DisabledEvent(__BaseStandardEvent):
    type: Literal["disabled"] = "disabled"


class AddedEvent(__BaseStandardEvent):
    type: Literal["added"] = "added"


class RemovedEvent(__BaseStandardEvent):
    type: Literal["removed"] = "removed"


LifecycleEvent = (
    StartedEvent | StoppedEvent | EnabledEvent | DisabledEvent | AddedEvent | RemovedEvent
)


class ConnectingEvent(__BaseStandardEvent):
    type: Literal["connecting"] = "connecting"


class ConnectedEvent(__BaseStandardEvent):
    type: Literal["connected"] = "connected"


class DisconnectingEvent(__BaseStandardEvent):
    type: Literal["disconnecting"] = "disconnecting"


class DisconnectedEvent(__BaseStandardEvent):
    type: Literal["disconnected"] = "disconnected"


class ConnectionLostEvent(__BaseStandardEvent):
    type: Literal["connection-lost"] = "connection-lost"


class ConnectFailedEvent(__BaseStandardEvent):
    type: Literal["connect-failed"] = "connect-failed"


ConnectionEvent = (
    ConnectedEvent
    | DisconnectedEvent
    | DisconnectingEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
)


class MessageSentEvent(__BaseStandardEvent):
    type: Literal["message-sent"] = "message-sent"
    message: Message


class MessageReceivedEvent(__BaseStandardEvent):
    type: Literal["message-received"] = "message-received"
    message: Message


MessageEvent = MessageSentEvent | MessageReceivedEvent


class AlertEvent(__BaseStandardEvent):
    type: Literal["alert"] = "alert"
    alert: Alert


class LogEvent(__BaseStandardEvent):
    type: Literal["log"] = "log"
    entry: LogEntry


class RoutineStartedEvent(__BaseStandardEvent):
    type: Literal["routine-started"] = "routine-started"
    routine: str


class RoutineStoppedEvent(__BaseStandardEvent):
    type: Literal["routine-stopped"] = "routine-stopped"
    routine: str


class RoutineCompletedEvent(__BaseStandardEvent):
    type: Literal["routine-completed"] = "routine-completed"
    routine: str


class RoutineCancelledEvent(__BaseStandardEvent):
    type: Literal["routine-cancelled"] = "routine-cancelled"
    routine: str


class RoutineExceptionEvent(__BaseStandardEvent):
    type: Literal["routine-exception"] = "routine-exception"
    routine: str
    traceback: Sequence[str]


class RoutineRestartingEvent(__BaseStandardEvent):
    type: Literal["routine-restarting"] = "routine-restarting"
    routine: str
    delay: PositiveTimeDelta


class RoutineRestartedEvent(__BaseStandardEvent):
    type: Literal["routine-restarted"] = "routine-restarted"
    routine: str


RoutineEvent = (
    RoutineStartedEvent
    | RoutineStoppedEvent
    | RoutineCompletedEvent
    | RoutineExceptionEvent
    | RoutineRestartedEvent
)


class JobAddedEvent(__BaseStandardEvent):
    type: Literal["job-added"] = "job-added"
    job: str


class JobRemovedEvent(__BaseStandardEvent):
    type: Literal["job-removed"] = "job-removed"
    job: str


class JobStartedEvent(__BaseStandardEvent):
    type: Literal["job-started"] = "job-started"
    job: str


class JobStoppedEvent(__BaseStandardEvent):
    type: Literal["job-stopped"] = "job-stopped"
    job: str


class JobCompletedEvent(__BaseStandardEvent):
    type: Literal["job-completed"] = "job-completed"
    job: str


class JobCancelledEvent(__BaseStandardEvent):
    type: Literal["job-cancelled"] = "job-cancelled"
    job: str


class JobExceptionEvent(__BaseStandardEvent):
    type: Literal["job-exception"] = "job-exception"
    job: str
    traceback: Sequence[str]


class JobRetryPendingEvent(__BaseStandardEvent):
    type: Literal["job-retry-pending"] = "job-retry-pending"
    job: str
    delay: PositiveTimeDelta


class JobRetryEvent(__BaseStandardEvent):
    type: Literal["job-retry"] = "job-retry"
    job: str


JobEvent = (
    JobAddedEvent
    | JobRemovedEvent
    | JobStartedEvent
    | JobStoppedEvent
    | JobCompletedEvent
    | JobCancelledEvent
    | JobExceptionEvent
    | JobRetryPendingEvent
    | JobRetryEvent
)


class ProcedureCalledEvent(__BaseStandardEvent):
    type: Literal["procedure-called"] = "procedure-called"
    procedure: str


class ProcedureCompletedEvent(__BaseStandardEvent):
    type: Literal["procedure-completed"] = "procedure-completed"
    procedure: str


class ProcedureCancelledEvent(__BaseStandardEvent):
    type: Literal["procedure-cancelled"] = "procedure-cancelled"
    procedure: str


class ProcedureExceptionEvent(__BaseStandardEvent):
    type: Literal["procedure-exception"] = "procedure-exception"
    procedure: str
    traceback: Sequence[str]


ProcedureEvent = (
    ProcedureCalledEvent
    | ProcedureCancelledEvent
    | ProcedureCompletedEvent
    | ProcedureExceptionEvent
)


class DatabaseExceptionEvent(__BaseStandardEvent):
    type: Literal["database-exception"] = "database-exception"
    traceback: Sequence[str]


DatabaseEvent = DatabaseExceptionEvent

StandardEvent = (
    LifecycleEvent
    | ConnectionEvent
    | MessageEvent
    | AlertEvent
    | LogEvent
    | RoutineEvent
    | JobEvent
    | ProcedureEvent
    | DatabaseEvent
)

ExceptionEvent = (
    RoutineExceptionEvent | JobExceptionEvent | ProcedureExceptionEvent | DatabaseExceptionEvent
)
