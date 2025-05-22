from __future__ import annotations

import asyncio
import inspect
import traceback
from abc import ABC
from asyncio import Queue as AsyncQueue
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    Literal,
    Sequence,
    TypeAlias,
    cast,
)
from uuid import UUID

from pydantic import ByteSize, Field

from ceres._internal import util
from ceres._internal.manager import BaseNodeManager
from ceres._internal.protocols import NodeSource
from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta, uuid7
from ceres.level import Level
from ceres.stream import Stream, WriteStream
from ceres.timing import utc


class Event(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid7)

    if TYPE_CHECKING:
        address: Address = cast(Address, None)
    else:
        address: Address

    timestamp: DateTime = Field(default_factory=utc)
    type: str
    level: Level = Level.INFO


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


class AttachedEvent(__BaseStandardEvent):
    type: Literal["attached"] = "attached"
    level: Level = Level.DEBUG


class WillDetachEvent(__BaseStandardEvent):
    type: Literal["will-detach"] = "will-detach"
    level: Level = Level.DEBUG


class DetachedEvent(__BaseStandardEvent):
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


class ConnectingEvent(__BaseStandardEvent):
    type: Literal["connecting"] = "connecting"


class ConnectedEvent(__BaseStandardEvent):
    type: Literal["connected"] = "connected"


class DisconnectingEvent(__BaseStandardEvent):
    type: Literal["disconnecting"] = "disconnecting"


class DisconnectedEvent(__BaseStandardEvent):
    type: Literal["disconnected"] = "disconnected"


class IdleTimeoutEvent(__BaseStandardEvent):
    type: Literal["idle-timeout"] = "idle-timeout"
    level: Level = Level.WARNING


class DisconnectVerifyStartedEvent(__BaseStandardEvent):
    type: Literal["disconnect-verify-started"] = "disconnect-verify-started"
    level: Level = Level.WARNING


class DisconnectVerifiedEvent(__BaseStandardEvent):
    type: Literal["disconnect-verified"] = "disconnect-verified"
    level: Level = Level.WARNING


class DisconnectUnverifiedEvent(__BaseStandardEvent):
    type: Literal["disconnect-unverified"] = "disconnect-unverified"
    level: Level = Level.WARNING


class DisconnectVerifyEndedEvent(__BaseStandardEvent):
    type: Literal["disconnect-verify-ended"] = "disconnect-verify-ended"
    level: Level = Level.WARNING


class ConnectionLostEvent(__BaseStandardEvent):
    type: Literal["connection-lost"] = "connection-lost"
    level: Level = Level.WARNING


class ConnectFailedEvent(__BaseStandardEvent):
    type: Literal["connect-failed"] = "connect-failed"
    level: Level = Level.ERROR
    reason: str | None = None


class ReconnectScheduledEvent(__BaseStandardEvent):
    type: Literal["reconnect-scheduled"] = "reconnect-scheduled"
    delay: PositiveTimeDelta


class BufferOverflowEvent(__BaseStandardEvent):
    type: Literal["buffer-overflow"] = "buffer-overflow"
    level: Level = Level.ERROR
    size: ByteSize
    limit: ByteSize
    dropped: ByteSize


ConnectionEvent: TypeAlias = (
    ConnectedEvent
    | DisconnectedEvent
    | DisconnectingEvent
    | IdleTimeoutEvent
    | DisconnectVerifyStartedEvent
    | DisconnectVerifiedEvent
    | DisconnectUnverifiedEvent
    | DisconnectVerifyEndedEvent
    | ConnectionLostEvent
    | ConnectFailedEvent
    | ReconnectScheduledEvent
    | BufferOverflowEvent
)


class ServerBindEvent(__BaseStandardEvent):
    type: Literal["server-bind"] = "server-bind"
    bind: str


class ServerBindExceptionEvent(__BaseStandardEvent):
    type: Literal["server-bind-exception"] = "server-bind-exception"
    level: Level = Level.ERROR
    bind: str
    traceback: Sequence[str]


class ClientConnectedEvent(__BaseStandardEvent):
    type: Literal["client-connected"] = "client-connected"
    level: Level = Level.INFO
    client: str


class ClientDisconnectedEvent(__BaseStandardEvent):
    type: Literal["client-disconnected"] = "client-disconnected"
    level: Level = Level.INFO
    client: str


class ServerProcessingExceptionEvent(__BaseStandardEvent):
    type: Literal["server-processing-exception"] = "server-processing-exception"
    level: Level = Level.ERROR
    client: str
    traceback: Sequence[str]


ServerEvent: TypeAlias = (
    ServerBindEvent
    | ServerBindExceptionEvent
    | ClientConnectedEvent
    | ClientDisconnectedEvent
    | ServerProcessingExceptionEvent
)


class MessageSentEvent(__BaseStandardEvent):
    type: Literal["message-sent"] = "message-sent"
    message: Message


class MessageReceivedEvent(__BaseStandardEvent):
    type: Literal["message-received"] = "message-received"
    message: Message


MessageEvent: TypeAlias = MessageSentEvent | MessageReceivedEvent


class AlertEvent(__BaseStandardEvent):
    type: Literal["alert"] = "alert"
    alert: Alert


class LogEvent(__BaseStandardEvent):
    type: Literal["log"] = "log"
    level: Level = Level.DEBUG
    entry: LogEntry


class ParticleEvent(__BaseStandardEvent):
    type: Literal["particle"] = "particle"
    particle: Particle


class VariableAssignedEvent(__BaseStandardEvent):
    type: Literal["variable-assigned"] = "variable-assigned"
    variable: Variable


VariableEvent: TypeAlias = VariableAssignedEvent


class SettingAssignedEvent(__BaseStandardEvent):
    type: Literal["setting-assigned"] = "setting-assigned"
    setting: Setting


SettingEvent: TypeAlias = SettingAssignedEvent


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
    level: Level = Level.ERROR
    routine: str
    traceback: Sequence[str]


class RoutineRestartingEvent(__BaseStandardEvent):
    type: Literal["routine-restarting"] = "routine-restarting"
    routine: str
    delay: PositiveTimeDelta


class RoutineRestartedEvent(__BaseStandardEvent):
    type: Literal["routine-restarted"] = "routine-restarted"
    routine: str


RoutineEvent: TypeAlias = (
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


class JobEndedEvent(__BaseStandardEvent):
    type: Literal["job-ended"] = "job-ended"
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


class PrunerAddedEvent(__BaseStandardEvent):
    type: Literal["pruner-added"] = "pruner-added"
    pruner: str


class PrunerRemovedEvent(__BaseStandardEvent):
    type: Literal["pruner-removed"] = "pruner-removed"
    pruner: str


class PruneStartedEvent(__BaseStandardEvent):
    type: Literal["prune-started"] = "prune-started"
    pruner: str


class PruneEndedEvent(__BaseStandardEvent):
    type: Literal["prune-ended"] = "prune-ended"
    pruner: str


class PruneCompletedEvent(__BaseStandardEvent):
    type: Literal["prune-completed"] = "prune-completed"
    pruner: str
    deleted: int


class PruneCancelledEvent(__BaseStandardEvent):
    type: Literal["prune-cancelled"] = "prune-cancelled"
    pruner: str


class PruneExceptionEvent(__BaseStandardEvent):
    type: Literal["prune-exception"] = "prune-exception"
    level: Level = Level.ERROR
    pruner: str
    traceback: Sequence[str]


PrunerEvent: TypeAlias = (
    PrunerAddedEvent
    | PrunerRemovedEvent
    | PruneStartedEvent
    | PruneEndedEvent
    | PruneCompletedEvent
    | PruneCancelledEvent
    | PruneExceptionEvent
)


class SieveAddedEvent(__BaseStandardEvent):
    type: Literal["sieve-added"] = "sieve-added"
    sieve: str


class SieveRemovedEvent(__BaseStandardEvent):
    type: Literal["sieve-removed"] = "sieve-removed"
    sieve: str


class SieveStartedEvent(__BaseStandardEvent):
    type: Literal["sieve-started"] = "sieve-started"
    sieve: str


class SieveStoppedEvent(__BaseStandardEvent):
    type: Literal["sieve-stopped"] = "sieve-stopped"
    sieve: str


class SieveCancelledEvent(__BaseStandardEvent):
    type: Literal["sieve-cancelled"] = "sieve-cancelled"
    sieve: str


class SieveExceptionEvent(__BaseStandardEvent):
    type: Literal["sieve-exception"] = "sieve-exception"
    level: Level = Level.ERROR
    sieve: str
    traceback: Sequence[str]


class SieveRetryPendingEvent(__BaseStandardEvent):
    type: Literal["sieve-retry-pending"] = "sieve-retry-pending"
    sieve: str
    delay: PositiveTimeDelta


class SieveRetryEvent(__BaseStandardEvent):
    type: Literal["sieve-retry"] = "sieve-retry"
    sieve: str


class SieveParticleErrorEvent(__BaseStandardEvent):
    level: Level = Level.ERROR
    type: Literal["sieve-particle-error"] = "sieve-particle-error"
    sieve: str
    error: ParticleError


SieveEvent: TypeAlias = (
    SieveAddedEvent
    | SieveRemovedEvent
    | SieveStartedEvent
    | SieveStoppedEvent
    | SieveCancelledEvent
    | SieveExceptionEvent
    | SieveRetryPendingEvent
    | SieveRetryEvent
    | SieveParticleErrorEvent
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
    level: Level = Level.ERROR
    procedure: str
    traceback: Sequence[str]


ProcedureEvent: TypeAlias = (
    ProcedureCalledEvent
    | ProcedureCancelledEvent
    | ProcedureCompletedEvent
    | ProcedureExceptionEvent
)


class DatabaseExceptionEvent(__BaseStandardEvent):
    type: Literal["database-exception"] = "database-exception"
    level: Level = Level.ERROR
    traceback: Sequence[str]


DatabaseEvent: TypeAlias = DatabaseExceptionEvent

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


from ceres.alert import Alert  # noqa: E402
from ceres.error import ParticleError  # noqa: E402
from ceres.logs import LogEntry  # noqa: E402
from ceres.message import Message  # noqa: E402
from ceres.particle import Particle  # noqa: E402
from ceres.setting import Setting  # noqa: E402
from ceres.variable import Variable  # noqa: E402

if TYPE_CHECKING:
    from ceres.component import ComponentSystem, ListenerBinding
    from ceres.config import LoggingConfig
    from ceres.node import Node


class NodeEventManager(BaseNodeManager):
    __slots__ = (
        "__stream",
        "__listeners",
    )

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)
        self.__stream: WriteStream[Event] = WriteStream()
        self.__listeners = (
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
        from ceres.component import ComponentSystem

        if isinstance(self.__node__, ComponentSystem):
            return self.__node__

    @property
    def settled(self) -> bool:
        return all(listener.settled for listener in self.__listeners)

    async def __run__(self) -> None:
        if not self.__listeners:
            await util.sleep_forever()
            return

        await util.concurrently(listener.__run__() for listener in self.__listeners)

    async def settle(self) -> None:
        while not self.settled:
            await util.concurrently(listener.settle() for listener in self.__listeners)

    def follow(self) -> Stream[Event]:
        return self.__stream.view()

    def emit[**P, T: Event](
        self,
        event_cls: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """
        Construct and `propagate` an event, assigning the address of the event to this node's
        address if unset.
        """
        if "address" not in kwargs:
            kwargs["address"] = self.__node__.address

        event = event_cls(*args, **kwargs)

        self.propagate(event, logging=self.__node__.get_resolved_logging_config())
        return event

    def propagate(self, event: Event, *, logging: LoggingConfig | None = None) -> None:
        """
        Propagate an event to all systems in the tree, any systems holding a direct or indirect
        reference to a system in the tree, and the containing engine.
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
        self.__stream.put(event)

        container = self.__node__.__container__

        # If there is a containing node, defer propagation to it.
        if container is not None:
            container.events.propagate(event)
            return

        seen: set[Node] = set()
        seen.add(self.__node__)

        # Handle the event ourselves.
        self.handle(event)

        # Traverse the tree, calling `handle(event)` for every component.
        for component in self.__node__.get_components(inclusive=False):
            if component.system not in seen:
                seen.add(component.system)
                component.system.events.handle(event)

            for referencer in component.system.get_referencing_components():
                if referencer.system not in seen:
                    seen.add(referencer.system)
                    referencer.system.events.handle(event)

    def listening(self, event_cls: type[Event], address: Address) -> bool:
        for listener in self.__listeners:
            if listener.handles(event_cls, address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        if not self.would_handle(event):
            return False

        handled = False
        for listener in self.__listeners:
            if listener.handle(event):
                handled = True

        return handled

    def would_handle(self, event: Event) -> bool:
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
    __slots__ = (
        "__system",
        "__binding",
        "__handler",
        "__handler_arity",
        "__queue",
        "__running",
    )

    def __init__(
        self,
        *,
        system: ComponentSystem,
        binding: ListenerBinding,
    ) -> None:
        self.__system = system
        self.__binding = binding
        self.__handler: _ComponentEventHandler = getattr(system.component, binding.method)
        self.__handler_arity = len(inspect.signature(self.__handler).parameters)
        self.__queue: AsyncQueue[Event] = AsyncQueue()
        self.__running = False

    @property
    def settled(self) -> bool:
        return self.__queue._finished.is_set()  # type: ignore

    def would_handle(self, event: Event) -> bool:
        return self.handles(type(event), event.address)

    async def __run__(self) -> None:
        self.__running = True
        try:
            while True:
                event = await self.__queue.get()
                await self._process(event)
        finally:
            self.__running = False

    async def settle(self) -> None:
        if self.__queue.empty():
            return

        while True:
            try:
                event = self.__queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            await self._process(event)

    def clear(self) -> None:
        while not self.__queue.empty():
            self.__queue.get_nowait()
            self.__queue.task_done()

    def handles(self, event_cls: type[Event], address: Address) -> bool:
        if not util.lenient_issubclass(event_cls, self.__binding.event):
            return False

        if self.__binding.local:
            if address == self.__system.address:
                return True

        if self.__binding.reference:
            for alias in self.__binding.reference:
                if any(
                    component.system.address == address
                    for component in self.__system.get_referenced_components(alias)
                ):
                    return True

        if self.__binding.address is not None:
            if self.__binding.address.matches(address, self.__system.address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        if not self.would_handle(event):
            return False

        self.__queue.put_nowait(event)
        return True

    async def _process(self, event: Event) -> None:
        try:
            result = self.__handler(*[event][: self.__handler_arity])
            if inspect.iscoroutine(result):
                await result
        except Exception:
            self.__system.log.error(
                f"An exception occurred while processing event {event}: "
                f"{traceback.format_exc()}"
            )
        finally:
            self.__queue.task_done()
