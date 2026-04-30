import asyncio
import inspect
import traceback
from asyncio import Queue as AsyncQueue
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import ByteSize, Field

from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.utilities.typing import lenient_issubclass
from ceres.address import Address
from ceres.channel import Channel, ChannelReader, OutputChannel
from ceres.concurrency import concurrently, sleep
from ceres.data import (
    DataObject,
    DateTime,
    PositiveTimeDelta,
    TimeDelta,
    uuid7,
)
from ceres.error import ExceptionInfo
from ceres.level import Level
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.__internal__.protocols import NodeSource

__all__ = [
    "Event",
    "EventManager",
]


class Event(DataObject, slots=True):
    """Base class for all events emitted through the system.

    Events propagate up through containing components and out to listeners. Each event carries the
    address of its originating component or engine, a timestamp, a stable string `type`
    discriminator, and a severity `level`.
    """

    id: UUID = Field(default_factory=uuid7)
    """Unique identifier for the event, defaulting to a time-ordered UUID7."""

    if TYPE_CHECKING:
        # The address is assigned by `EventManager.emit()` if not provided explicitly, so the static
        # type is relaxed for callers while remaining required at runtime.
        address: Address = cast("Address", None)
        """Address of the component or engine that emitted the event."""
    else:
        address: Address
        """Address of the component or engine that emitted the event."""

    timestamp: DateTime = Field(default_factory=utc)
    """When the event occurred, in UTC."""
    type: str
    """Discriminator string identifying the concrete event class."""
    level: Level = Level.INFO
    """Severity level used for logging and filtering."""


class StartedEvent(Event, slots=True):
    """Emitted when a component or engine finishes starting up."""

    type: Literal["started"] = "started"


class StoppingEvent(Event, slots=True):
    """Emitted when a component or engine begins shutting down, before any cleanup runs."""

    type: Literal["stopping"] = "stopping"


class StoppedEvent(Event, slots=True):
    """Emitted when a component or engine has fully stopped."""

    type: Literal["stopped"] = "stopped"


class EnabledEvent(Event, slots=True):
    """Emitted when a component transitions to the enabled state."""

    type: Literal["enabled"] = "enabled"


class DisabledEvent(Event, slots=True):
    """Emitted when a component transitions to the disabled state."""

    type: Literal["disabled"] = "disabled"


class AttachedEvent(Event, slots=True):
    """Emitted when a component is attached to a parent container."""

    type: Literal["attached"] = "attached"
    level: Level = Level.DEBUG


class WillDetachEvent(Event, slots=True):
    """Emitted just before a component detaches from its container, allowing cleanup."""

    type: Literal["will-detach"] = "will-detach"
    level: Level = Level.DEBUG


class DetachedEvent(Event, slots=True):
    """Emitted after a component has been detached from its container."""

    type: Literal["detached"] = "detached"
    level: Level = Level.DEBUG


LifecycleEvent: TypeAlias = (
    StartedEvent
    | StoppedEvent
    | EnabledEvent
    | DisabledEvent
    | AttachedEvent
    | WillDetachEvent
    | DetachedEvent
)
"""Union of all component lifecycle events."""


class ConnectionAddedEvent(Event, slots=True):
    """Emitted when a connection is registered with a component."""

    type: Literal["connection-added"] = "connection-added"
    connection: str | None = None


class ConnectionRemovedEvent(Event, slots=True):
    """Emitted when a connection is removed from a component."""

    type: Literal["connection-removed"] = "connection-removed"
    connection: str | None = None


class ConnectionStartedEvent(Event, slots=True):
    """Emitted when a connection's worker task starts."""

    type: Literal["connection-started"] = "connection-started"
    connection: str | None = None


class ConnectionStoppedEvent(Event, slots=True):
    """Emitted when a connection's worker task stops."""

    type: Literal["connection-stopped"] = "connection-stopped"
    connection: str | None = None


class ConnectionExceptionEvent(Event, slots=True):
    """Emitted when an unexpected exception occurs inside a connection's worker."""

    type: Literal["connection-exception"] = "connection-exception"
    level: Level = Level.ERROR
    connection: str | None = None


class ConnectingEvent(Event, slots=True):
    """Emitted when a connection attempt begins."""

    type: Literal["connecting"] = "connecting"
    connection: str | None = None


class ConnectedEvent(Event, slots=True):
    """Emitted when a connection has successfully established."""

    type: Literal["connected"] = "connected"
    connection: str | None = None


class DisconnectingEvent(Event, slots=True):
    """Emitted when a graceful disconnect begins."""

    type: Literal["disconnecting"] = "disconnecting"
    connection: str | None = None


class DisconnectedEvent(Event, slots=True):
    """Emitted when a connection has fully closed."""

    type: Literal["disconnected"] = "disconnected"
    connection: str | None = None


class ConnectTimeoutEvent(Event, slots=True):
    """Emitted when a connect attempt exceeds the configured timeout."""

    type: Literal["connect-timeout"] = "connect-timeout"
    level: Level = Level.WARNING
    connection: str | None = None
    timeout: TimeDelta
    """The timeout that was exceeded."""


class ReceiveTimeoutEvent(Event, slots=True):
    """Emitted when no data has been received within the configured timeout."""

    type: Literal["receive-timeout"] = "receive-timeout"
    level: Level = Level.WARNING
    connection: str | None = None
    timeout: TimeDelta
    """The receive timeout that was exceeded."""


class DisconnectVerifyStartedEvent(Event, slots=True):
    """Emitted when the system begins probing a connection to verify it is actually disconnected."""

    type: Literal["disconnect-verify-started"] = "disconnect-verify-started"
    level: Level = Level.WARNING
    connection: str | None = None


class DisconnectVerifiedEvent(Event, slots=True):
    """Emitted when a suspected disconnect is confirmed."""

    type: Literal["disconnect-verified"] = "disconnect-verified"
    level: Level = Level.WARNING
    connection: str | None = None


class DisconnectUnverifiedEvent(Event, slots=True):
    """Emitted when a suspected disconnect could not be confirmed and the connection is still up."""

    type: Literal["disconnect-unverified"] = "disconnect-unverified"
    level: Level = Level.WARNING
    connection: str | None = None


class DisconnectVerifyEndedEvent(Event, slots=True):
    """Emitted when the disconnect verification probe finishes, regardless of outcome."""

    type: Literal["disconnect-verify-ended"] = "disconnect-verify-ended"
    level: Level = Level.WARNING
    connection: str | None = None


class ConnectionLostEvent(Event, slots=True):
    """Emitted when an established connection is lost unexpectedly."""

    type: Literal["connection-lost"] = "connection-lost"
    level: Level = Level.WARNING
    connection: str | None = None


class ConnectFailedEvent(Event, slots=True):
    """Emitted when a connect attempt fails."""

    type: Literal["connect-failed"] = "connect-failed"
    level: Level = Level.ERROR
    connection: str | None = None
    message: str | None = None
    """Optional human-readable description of the failure."""


class ReconnectScheduledEvent(Event, slots=True):
    """Emitted when a reconnect attempt is scheduled after a failure or loss."""

    type: Literal["reconnect-scheduled"] = "reconnect-scheduled"
    connection: str | None = None
    delay: PositiveTimeDelta
    """How long the system will wait before attempting to reconnect."""


class BufferOverflowEvent(Event, slots=True):
    """Emitted when a connection buffer exceeds its configured size limit and drops data."""

    type: Literal["buffer-overflow"] = "buffer-overflow"
    level: Level = Level.ERROR
    connection: str | None = None
    size: ByteSize
    """Buffer size at the moment of overflow."""
    limit: ByteSize
    """Configured maximum buffer size."""
    dropped: ByteSize
    """Number of bytes dropped to bring the buffer back under the limit."""


ConnectionEvent: TypeAlias = (
    ConnectionAddedEvent
    | ConnectionRemovedEvent
    | ConnectionStartedEvent
    | ConnectionStoppedEvent
    | ConnectionExceptionEvent
    | ConnectedEvent
    | DisconnectedEvent
    | DisconnectingEvent
    | ReceiveTimeoutEvent
    | DisconnectVerifyStartedEvent
    | DisconnectVerifiedEvent
    | DisconnectUnverifiedEvent
    | DisconnectVerifyEndedEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
    | ReconnectScheduledEvent
    | BufferOverflowEvent
)
"""Union of all connection-related events."""


class ServerBindEvent(Event, slots=True):
    """Emitted when a server successfully binds to a network address."""

    type: Literal["server-bind"] = "server-bind"
    bind: str
    """String description of the bound address."""


class ServerBindExceptionEvent(Event, slots=True):
    """Emitted when a server fails to bind to its configured address."""

    type: Literal["server-bind-exception"] = "server-bind-exception"
    level: Level = Level.ERROR
    bind: str
    """String description of the address the server attempted to bind to."""
    exception: ExceptionInfo
    """Captured exception information."""


class ClientConnectedEvent(Event, slots=True):
    """Emitted when a remote client connects to a server."""

    type: Literal["client-connected"] = "client-connected"
    level: Level = Level.INFO
    client: str
    """String identifier for the connecting client."""


class ClientDisconnectedEvent(Event, slots=True):
    """Emitted when a remote client disconnects from a server."""

    type: Literal["client-disconnected"] = "client-disconnected"
    level: Level = Level.INFO
    client: str
    """String identifier for the disconnecting client."""


class ServerProcessingExceptionEvent(Event, slots=True):
    """Emitted when an exception occurs while a server processes a client request."""

    type: Literal["server-processing-exception"] = "server-processing-exception"
    level: Level = Level.ERROR
    client: str
    """String identifier for the client whose request failed."""
    exception: ExceptionInfo
    """Captured exception information."""


ServerEvent: TypeAlias = (
    ServerBindEvent
    | ServerBindExceptionEvent
    | ClientConnectedEvent
    | ClientDisconnectedEvent
    | ServerProcessingExceptionEvent
)
"""Union of all server-related events."""


class StartExceptionEvent(Event, slots=True):
    """Emitted when an exception occurs during a component's startup sequence."""

    type: Literal["start-exception"] = "start-exception"
    level: Level = Level.ERROR
    exception: ExceptionInfo
    """Captured exception information."""


class StopExceptionEvent(Event, slots=True):
    """Emitted when an exception occurs during a component's shutdown sequence."""

    type: Literal["stop-exception"] = "stop-exception"
    level: Level = Level.ERROR
    exception: ExceptionInfo
    """Captured exception information."""


class MessageSentEvent(Event, slots=True):
    """Emitted when a `Message` is transmitted on a connection."""

    type: Literal["message-sent"] = "message-sent"
    message: Message
    """The transmitted message."""


class MessageReceivedEvent(Event, slots=True):
    """Emitted when a `Message` is received on a connection."""

    type: Literal["message-received"] = "message-received"
    message: Message
    """The received message."""


MessageEvent: TypeAlias = MessageSentEvent | MessageReceivedEvent
"""Union of message-direction events."""


class AlertEvent(Event, slots=True):
    """Emitted when an `Alert` is raised by the system."""

    type: Literal["alert"] = "alert"
    alert: Alert
    """The raised alert."""


class LogEvent(Event, slots=True):
    """Emitted when a `LogEntry` is recorded."""

    type: Literal["log"] = "log"
    level: Level = Level.DEBUG
    entry: LogEntry
    """The log entry that was recorded."""


class ParticleEvent(Event, slots=True):
    """Emitted when a `Particle` is parsed or otherwise produced."""

    type: Literal["particle"] = "particle"
    particle: Particle
    """The produced particle."""


class VariableAssignedEvent(Event, slots=True):
    """Emitted when a `Variable`'s value is assigned."""

    type: Literal["variable-assigned"] = "variable-assigned"
    variable: Variable
    """The variable that was assigned."""


VariableEvent: TypeAlias = VariableAssignedEvent
"""Union of variable-related events."""


class SettingAssignedEvent(Event, slots=True):
    """Emitted when a `Setting`'s value is assigned."""

    type: Literal["setting-assigned"] = "setting-assigned"
    setting: Setting
    """The setting that was assigned."""


SettingEvent: TypeAlias = SettingAssignedEvent
"""Union of setting-related events."""


class RoutineStartedEvent(Event, slots=True):
    """Emitted when a routine begins running."""

    type: Literal["routine-started"] = "routine-started"
    routine: str
    """Name of the routine."""


class RoutineStoppedEvent(Event, slots=True):
    """Emitted when a routine stops, regardless of completion status."""

    type: Literal["routine-stopped"] = "routine-stopped"
    routine: str
    """Name of the routine."""


class RoutineCompletedEvent(Event, slots=True):
    """Emitted when a routine finishes its work successfully."""

    type: Literal["routine-completed"] = "routine-completed"
    routine: str
    """Name of the routine."""


class RoutineCancelledEvent(Event, slots=True):
    """Emitted when a routine is cancelled before completing."""

    type: Literal["routine-cancelled"] = "routine-cancelled"
    routine: str
    """Name of the routine."""


class RoutineExceptionEvent(Event, slots=True):
    """Emitted when a routine raises an unhandled exception."""

    type: Literal["routine-exception"] = "routine-exception"
    level: Level = Level.ERROR
    routine: str
    """Name of the routine."""
    exception: ExceptionInfo
    """Captured exception information."""


class RoutineRestartingEvent(Event, slots=True):
    """Emitted when a routine is scheduled to restart after stopping."""

    type: Literal["routine-restarting"] = "routine-restarting"
    routine: str
    """Name of the routine."""
    delay: PositiveTimeDelta
    """How long the system will wait before restarting the routine."""


class RoutineRestartedEvent(Event, slots=True):
    """Emitted when a routine has restarted successfully."""

    type: Literal["routine-restarted"] = "routine-restarted"
    routine: str
    """Name of the routine."""


RoutineEvent: TypeAlias = (
    RoutineStartedEvent
    | RoutineStoppedEvent
    | RoutineCompletedEvent
    | RoutineExceptionEvent
    | RoutineRestartedEvent
)
"""Union of routine lifecycle events."""


class JobAddedEvent(Event, slots=True):
    """Emitted when a job is registered with the scheduler."""

    type: Literal["job-added"] = "job-added"
    job: str
    """Name of the job."""


class JobRemovedEvent(Event, slots=True):
    """Emitted when a job is removed from the scheduler."""

    type: Literal["job-removed"] = "job-removed"
    job: str
    """Name of the job."""


class JobStartedEvent(Event, slots=True):
    """Emitted when a scheduled job begins running."""

    type: Literal["job-started"] = "job-started"
    job: str
    """Name of the job."""


class JobEndedEvent(Event, slots=True):
    """Emitted when a job finishes, regardless of outcome."""

    type: Literal["job-ended"] = "job-ended"
    job: str
    """Name of the job."""


class JobCompletedEvent(Event, slots=True):
    """Emitted when a job finishes successfully."""

    type: Literal["job-completed"] = "job-completed"
    job: str
    """Name of the job."""


class JobCancelledEvent(Event, slots=True):
    """Emitted when a job is cancelled before completing."""

    type: Literal["job-cancelled"] = "job-cancelled"
    job: str
    """Name of the job."""


class JobExceptionEvent(Event, slots=True):
    """Emitted when a job raises an unhandled exception."""

    type: Literal["job-exception"] = "job-exception"
    job: str
    """Name of the job."""
    exception: ExceptionInfo
    """Captured exception information."""


class JobRetryPendingEvent(Event, slots=True):
    """Emitted when a failed job is scheduled for retry."""

    type: Literal["job-retry-pending"] = "job-retry-pending"
    job: str
    """Name of the job."""
    delay: PositiveTimeDelta
    """How long the system will wait before retrying."""


class JobRetryEvent(Event, slots=True):
    """Emitted when a failed job is retried."""

    type: Literal["job-retry"] = "job-retry"
    job: str
    """Name of the job."""


JobEvent: TypeAlias = (
    JobAddedEvent
    | JobRemovedEvent
    | JobStartedEvent
    | JobEndedEvent
    | JobCompletedEvent
    | JobCancelledEvent
    | JobExceptionEvent
    | JobRetryPendingEvent
    | JobRetryEvent
)
"""Union of job lifecycle events."""


class PrunerAddedEvent(Event, slots=True):
    """Emitted when a pruner is registered."""

    type: Literal["pruner-added"] = "pruner-added"
    pruner: str
    """Name of the pruner."""


class PrunerRemovedEvent(Event, slots=True):
    """Emitted when a pruner is removed."""

    type: Literal["pruner-removed"] = "pruner-removed"
    pruner: str
    """Name of the pruner."""


class PruneStartedEvent(Event, slots=True):
    """Emitted when a pruner begins a pruning pass."""

    type: Literal["prune-started"] = "prune-started"
    pruner: str
    """Name of the pruner."""


class PruneEndedEvent(Event, slots=True):
    """Emitted when a pruning pass ends, regardless of outcome."""

    type: Literal["prune-ended"] = "prune-ended"
    pruner: str
    """Name of the pruner."""


class PruneCompletedEvent(Event, slots=True):
    """Emitted when a pruning pass completes successfully."""

    type: Literal["prune-completed"] = "prune-completed"
    pruner: str
    """Name of the pruner."""
    deleted: int
    """Number of records deleted during this pass."""


class PruneCancelledEvent(Event, slots=True):
    """Emitted when a pruning pass is cancelled before completing."""

    type: Literal["prune-cancelled"] = "prune-cancelled"
    pruner: str
    """Name of the pruner."""


class PruneExceptionEvent(Event, slots=True):
    """Emitted when a pruning pass raises an unhandled exception."""

    type: Literal["prune-exception"] = "prune-exception"
    level: Level = Level.ERROR
    pruner: str
    """Name of the pruner."""
    exception: ExceptionInfo
    """Captured exception information."""


PrunerEvent: TypeAlias = (
    PrunerAddedEvent
    | PrunerRemovedEvent
    | PruneStartedEvent
    | PruneEndedEvent
    | PruneCompletedEvent
    | PruneCancelledEvent
    | PruneExceptionEvent
)
"""Union of pruner lifecycle events."""


class SieveAddedEvent(Event, slots=True):
    """Emitted when a sieve is registered."""

    type: Literal["sieve-added"] = "sieve-added"
    sieve: str
    """Name of the sieve."""


class SieveRemovedEvent(Event, slots=True):
    """Emitted when a sieve is removed."""

    type: Literal["sieve-removed"] = "sieve-removed"
    sieve: str
    """Name of the sieve."""


class SieveStartedEvent(Event, slots=True):
    """Emitted when a sieve begins processing."""

    type: Literal["sieve-started"] = "sieve-started"
    sieve: str
    """Name of the sieve."""


class SieveStoppedEvent(Event, slots=True):
    """Emitted when a sieve stops processing."""

    type: Literal["sieve-stopped"] = "sieve-stopped"
    sieve: str
    """Name of the sieve."""


class SieveCancelledEvent(Event, slots=True):
    """Emitted when a sieve is cancelled before completing."""

    type: Literal["sieve-cancelled"] = "sieve-cancelled"
    sieve: str
    """Name of the sieve."""


class SieveExceptionEvent(Event, slots=True):
    """Emitted when a sieve raises an unhandled exception."""

    type: Literal["sieve-exception"] = "sieve-exception"
    level: Level = Level.ERROR
    sieve: str
    """Name of the sieve."""
    exception: ExceptionInfo
    """Captured exception information."""


class SieveRetryPendingEvent(Event, slots=True):
    """Emitted when a failed sieve is scheduled for retry."""

    type: Literal["sieve-retry-pending"] = "sieve-retry-pending"
    sieve: str
    """Name of the sieve."""
    delay: PositiveTimeDelta
    """How long the system will wait before retrying."""


class SieveRetryEvent(Event, slots=True):
    """Emitted when a failed sieve is retried."""

    type: Literal["sieve-retry"] = "sieve-retry"
    sieve: str
    """Name of the sieve."""


SieveEvent: TypeAlias = (
    SieveAddedEvent
    | SieveRemovedEvent
    | SieveStartedEvent
    | SieveStoppedEvent
    | SieveCancelledEvent
    | SieveExceptionEvent
    | SieveRetryPendingEvent
    | SieveRetryEvent
)
"""Union of sieve lifecycle events."""


class ProcedureCalledEvent(Event, slots=True):
    """Emitted when a procedure is invoked."""

    type: Literal["procedure-called"] = "procedure-called"
    procedure: str
    """Name of the procedure."""


class ProcedureCompletedEvent(Event, slots=True):
    """Emitted when a procedure finishes successfully."""

    type: Literal["procedure-completed"] = "procedure-completed"
    procedure: str
    """Name of the procedure."""


class ProcedureCancelledEvent(Event, slots=True):
    """Emitted when a procedure is cancelled before completing."""

    type: Literal["procedure-cancelled"] = "procedure-cancelled"
    procedure: str
    """Name of the procedure."""


class ProcedureExceptionEvent(Event, slots=True):
    """Emitted when a procedure raises an unhandled exception."""

    type: Literal["procedure-exception"] = "procedure-exception"
    level: Level = Level.ERROR
    procedure: str
    """Name of the procedure."""
    exception: ExceptionInfo
    """Captured exception information."""


ProcedureEvent: TypeAlias = (
    ProcedureCalledEvent
    | ProcedureCancelledEvent
    | ProcedureCompletedEvent
    | ProcedureExceptionEvent
)
"""Union of procedure-related events."""


class DatabaseExceptionEvent(Event, slots=True):
    """Emitted when a database operation raises an unhandled exception."""

    type: Literal["database-exception"] = "database-exception"
    level: Level = Level.ERROR
    exception: ExceptionInfo
    """Captured exception information."""


DatabaseEvent: TypeAlias = DatabaseExceptionEvent
"""Union of database-related events."""

StandardEvent: TypeAlias = (
    LifecycleEvent
    | ConnectionEvent
    | ServerEvent
    | MessageEvent
    | AlertEvent
    | LogEvent
    | RoutineEvent
    | JobEvent
    | PrunerEvent
    | SieveEvent
    | ProcedureEvent
    | DatabaseEvent
)
"""Union of every event type defined in the standard ceres distribution."""


# These imports are deferred to the bottom of the module to avoid circular imports, the event
# classes above only reference these names through forward typing.
from ceres.alert import Alert  # noqa: E402
from ceres.logs import LogEntry  # noqa: E402
from ceres.message import Message  # noqa: E402
from ceres.particle import Particle  # noqa: E402
from ceres.setting import Setting  # noqa: E402
from ceres.variable import Variable  # noqa: E402

if TYPE_CHECKING:
    from ceres.component import ComponentSystem, ListenerBinding
    from ceres.config import LoggingConfig
    from ceres.node import Node


class EventManager(BaseNodeManager):
    """Manages event emission, propagation, and listener dispatch for a single node.

    The manager maintains an internal `Channel` that fan-outs events to subscribers and tracks a
    list of `_ComponentEventListener` instances that bridge events into component listener methods.
    Events flow upward through containers and laterally through referencing components.
    """

    __slots__ = (
        "_events",
        "_listeners",
    )

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)
        self._events: Channel[Event] = Channel()
        # Listeners are only created when the node is part of a component system, otherwise the
        # node has no components to dispatch to.
        self._listeners = (
            []
            if self.__system__ is None
            else [
                _ComponentEventListener(
                    system=self.__system__,
                    binding=binding,
                )
                for binding in self.__system__.get_listener_bindings()
            ]
        )

    @property
    def __system__(self) -> ComponentSystem | None:
        """Return the underlying `ComponentSystem` if this node is one, otherwise `None`."""
        from ceres.component import ComponentSystem

        if isinstance(self.__node__, ComponentSystem):
            return self.__node__

    @property
    def settled(self) -> bool:
        """Return `True` once every listener has finished processing its queued events."""
        return all(listener.settled for listener in self._listeners)

    @property
    def stream(self) -> OutputChannel[Event]:
        """Return a fresh output channel that yields every event emitted on this node."""
        return self._events.output()

    def __aiter__(self) -> ChannelReader[Event]:
        return self._events.__aiter__()

    async def __run__(self) -> None:
        """Run all listener loops concurrently, sleeping forever if there are none."""
        if not self._listeners:
            await sleep(...)
            return

        await concurrently(listener.__run__() for listener in self._listeners)

    async def settle(self) -> None:
        """Block until every listener has drained its event queue."""
        while not self.settled:
            await concurrently(listener.settle() for listener in self._listeners)

    def read(self) -> ChannelReader[Event]:
        """Return a new reader for the event stream."""
        return self._events.read()

    def every[O](self, cls: type[O], /, *classes: type[O]) -> OutputChannel[O]:
        """Return an output channel filtered to events that are instances of any of `classes`."""
        return self._events.every(cls, *classes)

    def where(self, where: Callable[[Event], bool], /) -> OutputChannel[Event]:
        """Return an output channel filtered by the given predicate."""
        return self._events.where(where)

    def map[O](self, transform: Callable[[Event], O], /) -> OutputChannel[O]:
        """Return an output channel that applies `transform` to every emitted event."""
        return self._events.map(transform)

    def emit[**P, T: Event](
        self,
        event_cls: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Construct an event and propagate it through the system.

        The address of the event defaults to this node's address if not supplied.

        Args:
            event_cls: Event class (or factory) to construct.
            *args: Positional arguments forwarded to `event_cls`.
            **kwargs: Keyword arguments forwarded to `event_cls`.

        Returns:
            The constructed event after it has been propagated.
        """
        if "address" not in kwargs:
            kwargs["address"] = self.__node__.address

        event = event_cls(*args, **kwargs)

        self.propagate(event, logging=self.__node__.get_resolved_logging_config())
        return event

    def propagate(self, event: Event, *, logging: LoggingConfig | None = None) -> None:
        """Propagate an event through the system tree.

        The event is delivered to all systems in the tree, any systems holding a direct or indirect
        reference to a system in the tree, and the containing engine. When `logging` is supplied,
        the event is also written to the appropriate log channel.

        Args:
            event: The event to propagate.
            logging: Optional logging configuration controlling whether and how the event is logged
                before propagation.
        """
        if logging is not None:
            if logging.events and not isinstance(event, LogEvent):
                level = logging.events if isinstance(logging.events, Level) else None
                self.__node__.log.event(event, level)

            if logging.messages and isinstance(event, MessageEvent):
                level = logging.messages if isinstance(logging.messages, Level) else Level.INFO
                self.__node__.log.message(event.message, level)
            elif logging.particles and isinstance(event, ParticleEvent):
                level = logging.particles if isinstance(logging.particles, Level) else Level.INFO
                self.__node__.log.particle(event.particle, level)
            elif logging.alerts and isinstance(event, AlertEvent):
                level = logging.alerts if isinstance(logging.alerts, Level) else Level.INFO
                if event.alert.level >= level:
                    self.__node__.log.alert(event.alert)

        # Add the event to the outgoing event stream.
        self._events.put(event)

        container = self.__node__.__container__

        # If there is a containing node, defer propagation to it so the event walks the tree from
        # the root down rather than being dispatched twice.
        if container is not None:
            container.events.propagate(event)
            return

        seen: set[Node] = set()
        seen.add(self.__node__)

        # Handle the event ourselves.
        self.handle(event)

        # Traverse the tree, calling `handle(event)` for every component, including any components
        # that hold a reference to a component in the tree.
        for component in self.__node__.get_components(inclusive=False):
            if component.system not in seen:
                seen.add(component.system)
                component.system.events.handle(event)

            for referencer in component.system.get_referencing_components():
                if referencer.system not in seen:
                    seen.add(referencer.system)
                    referencer.system.events.handle(event)

    def listening(self, event_cls: type[Event], address: Address) -> bool:
        """Return `True` if any listener would handle an event of the given class and address."""
        for listener in self._listeners:
            if listener.handles(event_cls, address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        """Dispatch an event to every applicable listener.

        Args:
            event: The event to dispatch.

        Returns:
            `True` if at least one listener accepted the event, `False` otherwise.
        """
        if not self.would_handle(event):
            return False

        handled = False
        for listener in self._listeners:
            if listener.handle(event):
                handled = True

        return handled

    def would_handle(self, event: Event) -> bool:
        """Return `True` if `handle()` would dispatch the given event to at least one listener.

        A stopped node never handles events. A stopping node only handles events from nodes it
        contains, allowing in-progress shutdown to observe its children.
        """
        # If the node is not running, the event is not handled.
        if not self.__node__.running:
            return False

        # If the node is stopping, only handle events from nodes it contains.
        if self.__node__.stopping:
            if not self.__node__.address.contains(event.address):
                return False

        return self.listening(type(event), event.address)


_ComponentEventHandler = (
    Callable[[Event], None | Awaitable[None]] | Callable[[], None | Awaitable[None]]
)


class _ComponentEventListener:
    """Bridges a component's listener method to the event manager via a queued background task."""

    __slots__ = (
        "_system",
        "_binding",
        "_handler",
        "_handler_arity",
        "_queue",
        "_running",
    )

    def __init__(
        self,
        *,
        system: ComponentSystem,
        binding: ListenerBinding,
    ) -> None:
        self._system = system
        self._binding = binding
        self._handler: _ComponentEventHandler = getattr(system.component, binding.method)
        # The handler may accept either zero or one positional argument, so call sites pass the
        # event only when the handler signature requires it.
        self._handler_arity = len(inspect.signature(self._handler).parameters)
        self._queue: AsyncQueue[Event] = AsyncQueue()
        self._running = False

    @property
    def settled(self) -> bool:
        """Return `True` if every queued event has been processed."""
        # `_finished` is a private `asyncio` attribute, used because there is no public way to
        # observe queue settlement without consuming a join token.
        return self._queue._finished.is_set()  # type: ignore

    def would_handle(self, event: Event) -> bool:
        """Return `True` if this listener would accept the given event."""
        return self.handles(type(event), event.address)

    async def __run__(self) -> None:
        """Continuously process queued events until cancelled."""
        self._running = True
        try:
            while True:
                event = await self._queue.get()
                await self._process(event)
        finally:
            self._running = False

    async def settle(self) -> None:
        """Drain and process all currently queued events synchronously."""
        if self._queue.empty():
            return

        while True:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            await self._process(event)

    def clear(self) -> None:
        """Discard every queued event without processing it."""
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    def handles(self, event_cls: type[Event], address: Address) -> bool:
        """Return `True` if this listener should receive an event of the given class and address.

        The decision combines three independent checks, the listener handles the event if any of
        them passes, the event class is a subclass of the bound event type, and one of the binding's
        address matchers (local, reference, or address pattern) matches.
        """
        if not lenient_issubclass(event_cls, self._binding.event):
            return False

        if self._binding.local:
            if address == self._system.address:
                return True

        if self._binding.reference:
            for alias in self._binding.reference:
                if any(
                    component.system.address == address
                    for component in self._system.get_referenced_components(alias)
                ):
                    return True

        if self._binding.address is not None:
            if self._binding.address.matches(address, self._system.address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        """Enqueue the event for processing if this listener accepts it.

        Returns:
            `True` if the event was queued, `False` if it was filtered out.
        """
        if not self.would_handle(event):
            return False

        self._queue.put_nowait(event)
        return True

    async def _process(self, event: Event) -> None:
        try:
            result = self._handler(*[event][: self._handler_arity])
            if inspect.iscoroutine(result):
                await result
        except Exception:
            self._system.log.error(
                f"An exception occurred while processing event {event}: {traceback.format_exc()}"
            )
        finally:
            self._queue.task_done()
