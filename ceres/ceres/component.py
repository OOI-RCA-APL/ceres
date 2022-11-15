import dataclasses
import inspect
import traceback
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from functools import cache
from inspect import Parameter
from logging import Logger
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    Sequence,
    TypeVar,
    final,
    get_type_hints,
    overload,
)
from uuid import UUID, uuid4

from typing_extensions import dataclass_transform

from .address import ComponentAddress, LocalComponentAddress
from .alert import Alert, AlertLevel, RawAlertLevel
from .config import ComponentConfig, Config, UnitConfig
from .events import AlertEmittedEvent, Event
from .exceptions import ComponentClassInvalidException
from .internal import logs
from .internal.database.entity import EntityManager
from .internal.database.manager import DatabaseManager
from .internal.tasklet import Tasklet
from .internal.utilities import (
    add_binding,
    get_bindings,
    get_type_annotations,
    loose_isinstance,
    object_has_field,
    strify,
)
from .schedule import Schedule
from .scheduler import Scheduler
from .stream import Stream, StreamView
from .utilities import VDC, VDC_FIELD_SPECIFIERS, awaitify, utc


@dataclass(kw_only=True)
class ComponentInteral:
    incoming_event_stream: Stream[Event] = field(default_factory=Stream)
    outgoing_event_stream: Stream[Event] = field(default_factory=Stream)
    scheduler: Scheduler = field(default_factory=Scheduler)


_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VDC_FIELD_SPECIFIERS,
)
class Component(VDC, Tasklet):
    def __init_subclass__(cls, **kwargs: Any) -> type[Any]:
        super().__init_subclass__(**kwargs)

        __init__ = cls.__init__
        hints = get_type_hints(__init__)
        signature = inspect.signature(__init__)

        def is_subclass_or_typevar(subcls: type, cls: type) -> bool:
            if isinstance(subcls, TypeVar):
                return True

            return isinstance(cls, type) and isinstance(subcls, type) and issubclass(subcls, cls)

        parameters_hint = hints.get("parameters")
        context_hint = hints.get("context")
        references_hint = hints.get("references")

        if (
            not all(
                i == 0
                or (
                    parameter.kind == Parameter.KEYWORD_ONLY
                    and (
                        parameter.name in ("parameters", "context", "references")
                        or parameter.default != Parameter.empty
                    )
                )
                for i, parameter in enumerate(signature.parameters.values())
            )
            or not parameters_hint
            or not context_hint
            or not references_hint
            or not is_subclass_or_typevar(parameters_hint, Component.Parameters)
            or not is_subclass_or_typevar(context_hint, Component.Context)
            or not is_subclass_or_typevar(references_hint, Component.References)
        ):
            raise ComponentClassInvalidException(
                f"signature of {__init__} must be compatible with {inspect.signature(Component.__init__)}, got {signature}"
            )

        if isinstance(references_hint, type) and issubclass(references_hint, Component.References):
            for binding in cls.get_event_bindings():
                if not object_has_field(references_hint, binding.address.name):
                    raise ComponentClassInvalidException(
                        f"event listener {binding.function} refers to component '{binding.address.name}' which is not defined in {references_hint.__init__} with signature {inspect.signature(references_hint.__init__)}"
                    )

        return cls

    class Parameters(VDC, immutable=True):
        pass

    class Context(VDC, immutable=True):
        id: UUID = field(default_factory=uuid4)
        address: ComponentAddress

        def __post_init__(self) -> None:
            extra: list[tuple[str, Any]] = []

            for current in dataclasses.fields(self):
                if not object_has_field(Component.CompleteContext, current.name, current.type):
                    extra.append((current.name, current.type))

            if extra:
                raise ValueError(f"invalid context class, cannot provide fields: {extra}")

    class References(VDC, immutable=True):
        pass

    parameters: Parameters = field(default_factory=Parameters)
    context: Context
    references: References = field(default_factory=References)

    @final
    class CompleteContext(Context):
        id: UUID
        address: ComponentAddress
        root_config: Config
        unit_config: UnitConfig
        component_config: ComponentConfig
        database: DatabaseManager
        entities: EntityManager

    def __post_init__(self) -> None:
        self.__component_internal__ = ComponentInteral()

    @classmethod
    def get_parameters_type(cls) -> type[Parameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

    @classmethod
    def get_context_type(cls) -> type[Context]:
        return get_type_annotations(cls)["context"]  # type: ignore

    @classmethod
    def get_references_type(cls) -> type[References]:
        return get_type_annotations(cls)["references"]  # type: ignore

    @classmethod
    def get_event_bindings(cls) -> Sequence["EventBinding"]:
        return _get_event_bindings(cls)

    @classmethod
    def get_rpc_bindings(cls) -> Mapping[str, "RPCBinding"]:
        return _get_rpc_bindings(cls)

    @classmethod
    def get_job_bindings(cls) -> Mapping[str, "JobBinding"]:
        return _get_job_bindings(cls)

    @property
    def id(self) -> UUID:
        return self.context.id

    @property
    def address(self) -> ComponentAddress:
        return self.context.address

    @property
    def scheduler(self) -> Scheduler:
        return self.__component_internal__.scheduler

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.context.address))

    @property
    def event_stream(self) -> StreamView[Event]:
        return self.__component_internal__.outgoing_event_stream.view()

    def emit_event(self, event: _EventT) -> _EventT:
        self.__component_internal__.outgoing_event_stream.put(event)
        return event

    def emit_alert(
        self,
        level: AlertLevel | RawAlertLevel,
        kind: str,
        info: dict[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            origin_id=self.context.id,
            timestamp=utc(),
            level=AlertLevel.create_from(level),
            kind=kind,
            info=info or {},
        )

        self.emit_event(
            AlertEmittedEvent(
                address=self.address,
                alert=alert,
            )
        )

        return alert

    def handle_event(self, event: Event) -> None:
        self.__component_internal__.incoming_event_stream.put(event)

    async def __run__(self) -> None:
        self.scheduler.start()

        for job in self.get_job_bindings().values():
            if job.default_schedule is None:
                continue

            if (method := getattr(self, job.action.function.__name__, None)) is None:
                continue

            async def execute() -> None:
                if method is None:
                    return

                try:
                    if job.default_parameters is ...:
                        await awaitify(method())
                    else:
                        await awaitify(method(job.default_parameters))
                except Exception:
                    self.logger.error(
                        f"An exception occurred while running job '{job.name}': {traceback.format_exc()}"
                    )

            self.logger.info(f"Scheduling job '{job.name}' as: {job.default_schedule}")
            self.scheduler.add_job(execute, job.default_schedule, name=job.name)

        await self._process_incoming_events()

    async def _process_incoming_events(self) -> None:
        async for event in self.__component_internal__.incoming_event_stream:
            await self._process_incoming_event(event)

    async def _process_incoming_event(self, event: Event) -> None:
        for binding in self.get_event_bindings():
            if not loose_isinstance(event, binding.event_cls):
                continue
            target = getattr(self.references, binding.address.name, None)
            if not isinstance(target, Component):
                continue
            if target.context.address != event.address:
                continue

            if method := getattr(self, binding.function.__name__, None):
                try:
                    if len(inspect.signature(method).parameters) == 0:
                        await awaitify(method())
                    else:
                        await awaitify(method(event))
                except Exception:
                    self.logger.error(
                        f"An exception occurred while processing event {event}: {traceback.format_exc()}"
                    )

    async def __stop__(self) -> None:
        self.scheduler.stop()


EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"
RPC_BINDINGS_ATTRIBUTE = "__rpc_bindings__"
JOB_BINDINGS_ATTRIBUTE = "__job_bindings__"


class EventBinding(VDC):
    address: LocalComponentAddress
    event_cls: type | UnionType
    function: Callable[..., Any]


@overload
def listen(
    source: str,
    cls: type[_EventT],
) -> Callable[
    [Callable[[Any, _EventT], None | Awaitable[None]]], Callable[[Any, _EventT], Awaitable[None]]
]:
    ...


@overload
def listen(
    source: str,
    cls: UnionType,
) -> Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    ...


def listen(
    source: str,
    cls: type[_EventT] | UnionType,
) -> Callable[
    [Callable[[Any, _EventT], None | Awaitable[None]]], Callable[[Any, _EventT], Awaitable[None]]
] | Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    def inner(function: Callable[[Any, Event], None | Awaitable[None]]) -> Any:
        bindings: Sequence[EventBinding] | None = getattr(function, EVENT_BINDINGS_ATTRIBUTE, None)
        if not isinstance(bindings, list):
            bindings = list(bindings or [])
            setattr(function, EVENT_BINDINGS_ATTRIBUTE, bindings)

        bindings.append(
            EventBinding(
                address=LocalComponentAddress(source),
                event_cls=cls,
                function=function,
            )
        )

        return function

    return inner


class RPCKind(str, Enum):
    QUERY = "query"
    ACTION = "action"


class RPCBinding(VDC, ABC, frozen=True):
    kind: RPCKind
    name: str
    function: Callable[..., Any]


class QueryBinding(RPCBinding, frozen=True):
    kind: Literal[RPCKind.QUERY] = RPCKind.QUERY


class ActionBinding(RPCBinding, frozen=True):
    kind: Literal[RPCKind.ACTION] = RPCKind.ACTION


class JobBinding(VDC, frozen=True):
    name: str
    action: ActionBinding
    default_schedule: Schedule | None = None
    default_parameters: object | None = ...


_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def query(name: str) -> Callable[[_FunctionT], _FunctionT]:
    def bind(function: _FunctionT) -> _FunctionT:
        add_binding(
            function,
            RPC_BINDINGS_ATTRIBUTE,
            QueryBinding(
                name=name,
                function=function,
            ),
        )
        return function

    return bind


def action(name: str) -> Callable[[_FunctionT], _FunctionT]:
    def bind(function: _FunctionT) -> _FunctionT:
        parameters = inspect.signature(function).parameters

        if len(parameters) not in (1, 2):
            raise ValueError(
                f"action {strify(function)} must receive exactly one or two positional arguments, 'self' and the action's parameters"
            )

        add_binding(
            function,
            RPC_BINDINGS_ATTRIBUTE,
            ActionBinding(
                name=name,
                function=function,
            ),
        )
        return function

    return bind


def job(
    name: str,
    *,
    default_schedule: Schedule | None = None,
    default_parameters: object | None = None,
) -> Callable[[_FunctionT], _FunctionT]:
    def bind(function: _FunctionT) -> _FunctionT:
        action = next(
            (
                rpc
                for rpc in getattr(function, RPC_BINDINGS_ATTRIBUTE, [])
                if isinstance(rpc, ActionBinding)
            ),
            None,
        )

        if action is None:
            raise ValueError("job must be bound to an action")

        parameters = inspect.signature(action.function).parameters
        if len(parameters) == 1 and default_parameters is not ...:
            raise ValueError(
                "job action does not take any parameters, but default parameters have been specified"
            )

        add_binding(
            function,
            JOB_BINDINGS_ATTRIBUTE,
            JobBinding(
                name=name,
                action=action,
                default_schedule=default_schedule,
                default_parameters=default_parameters,
            ),
        )

        return function

    return bind


def _get_event_bindings(cls: type[_ComponentT]) -> Sequence[EventBinding]:
    return tuple(get_bindings(cls, EVENT_BINDINGS_ATTRIBUTE, EventBinding))


def _get_rpc_bindings(cls: type[_ComponentT]) -> Mapping[str, RPCBinding]:
    return MappingProxyType(
        {
            rpc.name: rpc
            for rpc in sorted(
                get_bindings(cls, RPC_BINDINGS_ATTRIBUTE, RPCBinding),
                key=lambda rpc: 0 if rpc.kind == RPCKind.QUERY else 1,
            )
        }
    )


def _get_job_bindings(cls: type[_ComponentT]) -> Mapping[str, JobBinding]:
    return MappingProxyType(
        {job.name: job for job in get_bindings(cls, JOB_BINDINGS_ATTRIBUTE, JobBinding)}
    )


if not TYPE_CHECKING:
    _get_event_bindings = cache(_get_event_bindings)
    _get_rpc_bindings = cache(_get_rpc_bindings)
    _get_job_bindings = cache(_get_job_bindings)
