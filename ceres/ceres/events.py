from abc import ABC
from enum import Enum
from typing import TYPE_CHECKING, Literal, Sequence, cast
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import Address
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.timing import utc


class StandardEventKind(str, Enum):
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ENABLED = "enabled"
    DISABLED = "disabled"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    DISCONNECTING = "disconnecting"
    CONNECTION_LOST = "connection-lost"
    CONNECT_FAILED = "connect-failed"
    MESSAGE_SENT = "message-sent"
    MESSAGE_RECEIVED = "message-received"
    ALERT = "alert"
    LOG = "log"
    ROUTINE_STARTED = "routine-started"
    ROUTINE_STOPPED = "routine-stopped"
    ROUTINE_COMPLETED = "routine-completed"
    ROUTINE_CANCELLED = "routine-cancelled"
    ROUTINE_EXCEPTION = "routine-exception"
    ROUTINE_RESTARTING = "routine-restarting"
    ROUTINE_RESTARTED = "routine-restarted"
    JOB_ADDED = "job-added"
    JOB_REMOVED = "job-removed"
    JOB_STARTED = "job-started"
    JOB_STOPPED = "job-stopped"
    JOB_COMPLETED = "job-completed"
    JOB_CANCELLED = "job-cancelled"
    JOB_EXCEPTION = "job-exception"
    JOB_RETRY_PENDING = "job-retry-pending"
    JOB_RETRY = "job-retry"
    PROCEDURE_CALLED = "procedure-called"
    PROCEDURE_COMPLETED = "procedure-completed"
    PROCEDURE_CANCELLED = "procedure-cancelled"
    PROCEDURE_EXCEPTION = "procedure-exception"
    DATABASE_EXCEPTION = "database-exception"


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


class StartedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.STARTED] = StandardEventKind.STARTED


class StoppingEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.STOPPING] = StandardEventKind.STOPPING


class StoppedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.STOPPED] = StandardEventKind.STOPPED


class EnabledEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ENABLED] = StandardEventKind.ENABLED


class DisabledEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.DISABLED] = StandardEventKind.DISABLED


class ConnectingEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECTING] = StandardEventKind.CONNECTING


class ConnectedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECTED] = StandardEventKind.CONNECTED


class DisconnectingEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.DISCONNECTING] = StandardEventKind.DISCONNECTING


class DisconnectedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.DISCONNECTED] = StandardEventKind.DISCONNECTED


class ConnectionLostEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECTION_LOST] = StandardEventKind.CONNECTION_LOST


class ConnectFailedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.CONNECT_FAILED] = StandardEventKind.CONNECT_FAILED


ConnectionEvent = (
    ConnectedEvent
    | DisconnectedEvent
    | DisconnectingEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
)


class MessageSentEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.MESSAGE_SENT] = StandardEventKind.MESSAGE_SENT
    message: Message


class MessageReceivedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.MESSAGE_RECEIVED] = StandardEventKind.MESSAGE_RECEIVED
    message: Message


MessageEvent = MessageSentEvent | MessageReceivedEvent


class AlertEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ALERT] = StandardEventKind.ALERT
    alert: Alert


class LogEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.LOG] = StandardEventKind.LOG
    entry: LogEntry


class RoutineStartedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_STARTED] = StandardEventKind.ROUTINE_STARTED
    routine: str


class RoutineStoppedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_STOPPED] = StandardEventKind.ROUTINE_STOPPED
    routine: str


class RoutineCompletedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_COMPLETED] = StandardEventKind.ROUTINE_COMPLETED
    routine: str


class RoutineCancelledEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_CANCELLED] = StandardEventKind.ROUTINE_CANCELLED
    routine: str


class RoutineExceptionEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_EXCEPTION] = StandardEventKind.ROUTINE_EXCEPTION
    routine: str
    traceback: Sequence[str]


class RoutineRestartingEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_RESTARTED] = StandardEventKind.ROUTINE_RESTARTED
    routine: str
    delay: PositiveTimeDelta


class RoutineRestartedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.ROUTINE_RESTARTED] = StandardEventKind.ROUTINE_RESTARTED
    routine: str


RoutineEvent = (
    RoutineStartedEvent
    | RoutineStoppedEvent
    | RoutineCompletedEvent
    | RoutineExceptionEvent
    | RoutineRestartedEvent
)


class JobAddedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_ADDED] = StandardEventKind.JOB_ADDED
    job: str


class JobRemovedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_REMOVED] = StandardEventKind.JOB_REMOVED
    job: str


class JobStartedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_STARTED] = StandardEventKind.JOB_STARTED
    job: str


class JobStoppedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_STOPPED] = StandardEventKind.JOB_STOPPED
    job: str


class JobCompletedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_COMPLETED] = StandardEventKind.JOB_COMPLETED
    job: str


class JobCancelledEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_CANCELLED] = StandardEventKind.JOB_CANCELLED
    job: str


class JobExceptionEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_EXCEPTION] = StandardEventKind.JOB_EXCEPTION
    job: str
    traceback: Sequence[str]


class JobRetryPendingEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_RETRY_PENDING] = StandardEventKind.JOB_RETRY_PENDING
    job: str
    delay: PositiveTimeDelta


class JobRetryEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.JOB_RETRY_PENDING] = StandardEventKind.JOB_RETRY_PENDING
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


class ProcedureCalledEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.PROCEDURE_CALLED] = StandardEventKind.PROCEDURE_CALLED
    procedure: str


class ProcedureCompletedEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.PROCEDURE_COMPLETED] = StandardEventKind.PROCEDURE_COMPLETED
    procedure: str


class ProcedureCancelledEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.PROCEDURE_CANCELLED] = StandardEventKind.PROCEDURE_CANCELLED
    procedure: str


class ProcedureExceptionEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.PROCEDURE_EXCEPTION] = StandardEventKind.PROCEDURE_EXCEPTION
    procedure: str
    traceback: Sequence[str]


ProcedureEvent = ProcedureCalledEvent | ProcedureCompletedEvent | ProcedureExceptionEvent


class DatabaseExceptionEvent(BaseStandardEvent):
    kind: Literal[StandardEventKind.DATABASE_EXCEPTION] = StandardEventKind.DATABASE_EXCEPTION
    traceback: Sequence[str]


DatabaseEvent = DatabaseExceptionEvent

StandardEvent = (
    StartedEvent
    | StoppedEvent
    | EnabledEvent
    | DisabledEvent
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
