from abc import ABC
from typing import TYPE_CHECKING, Literal, Sequence, cast
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import Address
from ceres.alert import Alert
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.internal.utilities import StrEnum
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.timing import utc


class StandardEventType(StrEnum):
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ADDED = "added"
    REMOVED = "removed"
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
    type: StandardEventType | str


class BaseStandardEvent(Event, ABC):
    type: StandardEventType


class StartedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.STARTED] = StandardEventType.STARTED


class StoppingEvent(BaseStandardEvent):
    type: Literal[StandardEventType.STOPPING] = StandardEventType.STOPPING


class StoppedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.STOPPED] = StandardEventType.STOPPED


class EnabledEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ENABLED] = StandardEventType.ENABLED


class DisabledEvent(BaseStandardEvent):
    type: Literal[StandardEventType.DISABLED] = StandardEventType.DISABLED


class AddedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ADDED] = StandardEventType.ADDED


class RemovedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.REMOVED] = StandardEventType.REMOVED


class ConnectingEvent(BaseStandardEvent):
    type: Literal[StandardEventType.CONNECTING] = StandardEventType.CONNECTING


class ConnectedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.CONNECTED] = StandardEventType.CONNECTED


class DisconnectingEvent(BaseStandardEvent):
    type: Literal[StandardEventType.DISCONNECTING] = StandardEventType.DISCONNECTING


class DisconnectedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.DISCONNECTED] = StandardEventType.DISCONNECTED


class ConnectionLostEvent(BaseStandardEvent):
    type: Literal[StandardEventType.CONNECTION_LOST] = StandardEventType.CONNECTION_LOST


class ConnectFailedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.CONNECT_FAILED] = StandardEventType.CONNECT_FAILED


ConnectionEvent = (
    ConnectedEvent
    | DisconnectedEvent
    | DisconnectingEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
)


class MessageSentEvent(BaseStandardEvent):
    type: Literal[StandardEventType.MESSAGE_SENT] = StandardEventType.MESSAGE_SENT
    message: Message


class MessageReceivedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.MESSAGE_RECEIVED] = StandardEventType.MESSAGE_RECEIVED
    message: Message


MessageEvent = MessageSentEvent | MessageReceivedEvent


class AlertEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ALERT] = StandardEventType.ALERT
    alert: Alert


class LogEvent(BaseStandardEvent):
    type: Literal[StandardEventType.LOG] = StandardEventType.LOG
    entry: LogEntry


class RoutineStartedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_STARTED] = StandardEventType.ROUTINE_STARTED
    routine: str


class RoutineStoppedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_STOPPED] = StandardEventType.ROUTINE_STOPPED
    routine: str


class RoutineCompletedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_COMPLETED] = StandardEventType.ROUTINE_COMPLETED
    routine: str


class RoutineCancelledEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_CANCELLED] = StandardEventType.ROUTINE_CANCELLED
    routine: str


class RoutineExceptionEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_EXCEPTION] = StandardEventType.ROUTINE_EXCEPTION
    routine: str
    traceback: Sequence[str]


class RoutineRestartingEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_RESTARTED] = StandardEventType.ROUTINE_RESTARTED
    routine: str
    delay: PositiveTimeDelta


class RoutineRestartedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.ROUTINE_RESTARTED] = StandardEventType.ROUTINE_RESTARTED
    routine: str


RoutineEvent = (
    RoutineStartedEvent
    | RoutineStoppedEvent
    | RoutineCompletedEvent
    | RoutineExceptionEvent
    | RoutineRestartedEvent
)


class JobAddedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_ADDED] = StandardEventType.JOB_ADDED
    job: str


class JobRemovedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_REMOVED] = StandardEventType.JOB_REMOVED
    job: str


class JobStartedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_STARTED] = StandardEventType.JOB_STARTED
    job: str


class JobStoppedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_STOPPED] = StandardEventType.JOB_STOPPED
    job: str


class JobCompletedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_COMPLETED] = StandardEventType.JOB_COMPLETED
    job: str


class JobCancelledEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_CANCELLED] = StandardEventType.JOB_CANCELLED
    job: str


class JobExceptionEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_EXCEPTION] = StandardEventType.JOB_EXCEPTION
    job: str
    traceback: Sequence[str]


class JobRetryPendingEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_RETRY_PENDING] = StandardEventType.JOB_RETRY_PENDING
    job: str
    delay: PositiveTimeDelta


class JobRetryEvent(BaseStandardEvent):
    type: Literal[StandardEventType.JOB_RETRY_PENDING] = StandardEventType.JOB_RETRY_PENDING
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
    type: Literal[StandardEventType.PROCEDURE_CALLED] = StandardEventType.PROCEDURE_CALLED
    procedure: str


class ProcedureCompletedEvent(BaseStandardEvent):
    type: Literal[StandardEventType.PROCEDURE_COMPLETED] = StandardEventType.PROCEDURE_COMPLETED
    procedure: str


class ProcedureCancelledEvent(BaseStandardEvent):
    type: Literal[StandardEventType.PROCEDURE_CANCELLED] = StandardEventType.PROCEDURE_CANCELLED
    procedure: str


class ProcedureExceptionEvent(BaseStandardEvent):
    type: Literal[StandardEventType.PROCEDURE_EXCEPTION] = StandardEventType.PROCEDURE_EXCEPTION
    procedure: str
    traceback: Sequence[str]


ProcedureEvent = ProcedureCalledEvent | ProcedureCompletedEvent | ProcedureExceptionEvent


class DatabaseExceptionEvent(BaseStandardEvent):
    type: Literal[StandardEventType.DATABASE_EXCEPTION] = StandardEventType.DATABASE_EXCEPTION
    traceback: Sequence[str]


DatabaseEvent = DatabaseExceptionEvent

StandardEvent = (
    StartedEvent
    | StoppedEvent
    | EnabledEvent
    | DisabledEvent
    | AddedEvent
    | RemovedEvent
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
