import inspect
import traceback
from dataclasses import dataclass, field
from inspect import Parameter
from logging import ERROR, INFO, WARNING, Logger
from types import MappingProxyType
from typing import (
    Any,
    AsyncIterable,
    Mapping,
    Sequence,
    TypeVar,
    cast,
    final,
    get_type_hints,
)
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, validate_arguments
from typing_extensions import dataclass_transform

from .address import ComponentAddress
from .alert import Alert, AlertLevel
from .config import ComponentConfig, Config, UnitConfig
from .data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ImmutableDataObject,
    ValidatedDataclass,
    jsonify,
)
from .errors import (
    ProcedureDoesNotExistError,
    ProcedureError,
    ProcedureExceptionError,
    ProcedureInvalidInputError,
)
from .events import AlertEmittedEvent, Event
from .exceptions import ComponentClassInvalidException
from .internal import logs
from .internal.binding import get_bindings
from .internal.database.entity import EntityManager
from .internal.database.manager import DatabaseManager
from .internal.tasklet import Tasklet
from .internal.utilities import (
    awaitify,
    cached,
    get_type_annotations,
    loose_isinstance,
    object_has_field,
    pre_validate_arguments,
)
from .listener import ListenerBinding
from .procedure import (
    ActionBinding,
    BaseProcedureBinding,
    CallableProcedureKind,
    DisplayBinding,
    JobBinding,
    ProcedureKind,
    QueryBinding,
    SubscribableProcedureKind,
    SubscriptionBinding,
)
from .result import Fail, Ok, Result
from .scheduler import Scheduler
from .stream import Stream, StreamView
from .validation import ValidationProblem


@dataclass(kw_only=True)
class ComponentInternal:
    incoming_event_stream: Stream[Event] = field(default_factory=Stream)
    outgoing_event_stream: Stream[Event] = field(default_factory=Stream)
    scheduler: Scheduler = field(default_factory=Scheduler)


_ComponentT = TypeVar("_ComponentT", bound="Component")
_EventT = TypeVar("_EventT", bound=Event)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Component(ValidatedDataclass, Tasklet):
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
            for binding in cls.get_listener_bindings():
                if not object_has_field(references_hint, binding.address.name):
                    raise ComponentClassInvalidException(
                        f"event listener {binding.function} refers to component '{binding.address.name}' which is not defined in {references_hint.__init__} with signature {inspect.signature(references_hint.__init__)}"
                    )

        return cls

    class Parameters(ImmutableDataObject):
        pass

    class Context(ImmutableDataObject):
        id: UUID = Field(default_factory=uuid4)
        address: ComponentAddress

        def __init_subclass__(cls) -> None:
            if cls.__module__ == __name__:
                return

            extra: list[tuple[str, Any]] = []

            for current in cls.__fields__.values():
                if not object_has_field(Component.CompleteContext, current.name, current.type_):
                    extra.append((current.name, current.type_))

            if extra:
                raise ValueError(f"invalid context class, cannot provide fields: {extra}")

    class References(ImmutableDataObject):
        pass

    parameters: Parameters = Field(default_factory=Parameters)
    context: Context
    references: References = Field(default_factory=References)

    class CompleteContext(Context):
        id: UUID
        address: ComponentAddress
        root_config: Config
        unit_config: UnitConfig
        component_config: ComponentConfig
        database: DatabaseManager
        entities: EntityManager

    def __post_init__(self) -> None:
        self.__component_internal__ = ComponentInternal()

    @final
    @classmethod
    def get_parameters_type(cls) -> type[Parameters]:
        return get_type_annotations(cls)["parameters"]  # type: ignore

    @final
    @classmethod
    def get_context_type(cls) -> type[Context]:
        return get_type_annotations(cls)["context"]  # type: ignore

    @final
    @classmethod
    def get_references_type(cls) -> type[References]:
        return get_type_annotations(cls)["references"]  # type: ignore

    @final
    @classmethod
    def get_listener_bindings(cls) -> Sequence[ListenerBinding]:
        return _get_listener_bindings(cls)

    @final
    @classmethod
    def get_query_bindings(cls) -> Mapping[str, QueryBinding]:
        return _get_procedure_bindings(cls, QueryBinding)

    @final
    @classmethod
    def get_action_bindings(cls) -> Mapping[str, ActionBinding]:
        return _get_procedure_bindings(cls, ActionBinding)

    @final
    @classmethod
    def get_job_bindings(cls) -> Mapping[str, JobBinding]:
        return _get_procedure_bindings(cls, JobBinding)

    @final
    @classmethod
    def get_subscription_bindings(cls) -> Mapping[str, SubscriptionBinding]:
        return _get_procedure_bindings(cls, SubscriptionBinding)

    @final
    @classmethod
    def get_display_bindings(cls) -> Mapping[str, DisplayBinding]:
        return _get_procedure_bindings(cls, DisplayBinding)

    @final
    @classmethod
    def get_procedure_bindings(cls, kind: "ProcedureKind") -> Mapping[str, BaseProcedureBinding]:
        match kind:
            case ProcedureKind.QUERY:
                return cls.get_query_bindings()
            case ProcedureKind.ACTION:
                return cls.get_action_bindings()
            case ProcedureKind.JOB:
                return cls.get_job_bindings()
            case ProcedureKind.SUBSCRIPTION:
                return cls.get_subscription_bindings()
            case ProcedureKind.DISPLAY:
                return cls.get_display_bindings()

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

    async def _invoke(
        self,
        kind: "ProcedureKind",
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (
            (binding := self.get_procedure_bindings(kind).get(procedure)) is None
            or (method := getattr(self, binding.function, None)) is None
            or not inspect.ismethod(method)
        ):
            return Fail(ProcedureDoesNotExistError())

        arguments: list[object] = []
        if input is not None:
            arguments.append(input)

        try:
            pre_validate_arguments(method, *arguments)
        except ValidationError as error:
            return Fail(ProcedureInvalidInputError(problems=ValidationProblem.extract(error)))

        try:
            return Ok(await awaitify(validate_arguments(method)(*arguments)))
        except Exception:
            return Fail(ProcedureExceptionError(traceback=traceback.format_exc()))

    async def call(
        self,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        return await self._invoke(kind.upcast(), procedure, input)

    async def subscribe(
        self,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        return cast(
            Result[AsyncIterable[object | None], ProcedureError],
            await self._invoke(kind.upcast(), procedure, input),
        )

    def emit_event(self, event: _EventT) -> _EventT:
        if "component_id" not in event.__fields_set__ or event.component_id == UUID(int=0):
            object.__setattr__(event, "component_id", self.id)

        self.__component_internal__.outgoing_event_stream.put(event)
        return event

    def emit_alert(self, alert: Alert) -> Alert:
        if "component_id" not in alert.__fields_set__ or alert.component_id == UUID(int=0):
            object.__setattr__(alert, "component_id", self.id)

        match alert.level:
            case AlertLevel.INFO:
                log_level = INFO
            case AlertLevel.WARNING:
                log_level = WARNING
            case AlertLevel.ERROR:
                log_level = ERROR

        self.logger.log(
            log_level,
            f"ALERT({alert.code}{' ' + jsonify(alert.info) if alert.info else ''})",
        )

        self.emit_event(AlertEmittedEvent(alert=alert))
        return alert

    def handle_event(self, event: Event) -> None:
        self.__component_internal__.incoming_event_stream.put(event)

    async def __run__(self) -> None:
        self.scheduler.start()

        for job in self.get_job_bindings().values():
            if job.default_schedule is None:
                continue

            if (method := getattr(self, job.function, None)) is None:
                continue

            async def execute() -> None:
                if method is None:
                    return

                try:
                    if job.default_input is ...:
                        await awaitify(method())
                    else:
                        await awaitify(method(job.default_input))
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
        for binding in self.get_listener_bindings():
            if not loose_isinstance(event, binding.event):
                continue
            target = getattr(self.references, binding.address.name, None)
            if not isinstance(target, Component):
                continue
            if target.context.address != event.address:
                continue

            if method := getattr(self, binding.function, None):
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


@cached
def _get_listener_bindings(component_cls: type[Component]) -> Sequence[ListenerBinding]:
    return tuple(get_bindings(component_cls, ListenerBinding))


_ProcedureBindingT = TypeVar("_ProcedureBindingT", bound=BaseProcedureBinding)


@cached
def _get_procedure_bindings(
    component_cls: type[_ComponentT],
    binding_cls: type[_ProcedureBindingT],
) -> Mapping[str, _ProcedureBindingT]:
    return MappingProxyType(
        {binding.name: binding for binding in get_bindings(component_cls, binding_cls)}
    )
