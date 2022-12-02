import inspect
import traceback
from dataclasses import dataclass, field
from enum import Enum
from inspect import Parameter
from logging import ERROR, INFO, WARNING, Logger
from types import MappingProxyType, UnionType
from typing import (
    Any,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    Sequence,
    TypeVar,
    get_type_hints,
    overload,
)
from uuid import UUID, uuid4

from pydantic import Field, ValidationError, schema_of, validate_arguments
from typing_extensions import dataclass_transform

from .address import ComponentAddress, LocalComponentAddress
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
from .internal.database.entity import EntityManager
from .internal.database.manager import DatabaseManager
from .internal.tasklet import Tasklet
from .internal.utilities import (
    awaitify,
    cached,
    get_bindings,
    get_type_annotations,
    loose_isinstance,
    object_has_field,
    pre_validate_arguments,
    strify,
)
from .result import Fail, Ok, Result
from .schedule import Schedule
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
    def get_listener_bindings(cls) -> Sequence["ListenerBinding"]:
        return _get_listener_bindings(cls)

    @classmethod
    def get_query_bindings(cls) -> Mapping[str, "QueryBinding"]:
        return _get_query_bindings(cls)

    @classmethod
    def get_action_bindings(cls) -> Mapping[str, "ActionBinding"]:
        return _get_action_bindings(cls)

    @classmethod
    def get_job_bindings(cls) -> Mapping[str, "JobBinding"]:
        return _get_job_bindings(cls)

    @classmethod
    def get_procedure_bindings(cls, kind: "ProcedureKind") -> Mapping[str, "ProcedureBinding"]:
        match kind:
            case ProcedureKind.QUERY:
                return cls.get_query_bindings()
            case ProcedureKind.ACTION:
                return cls.get_action_bindings()
            case ProcedureKind.JOB:
                return cls.get_job_bindings()

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

    async def call(
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
            return Fail(ProcedureExceptionError(exception=traceback.format_exc()))

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


_T = TypeVar("_T")


def _bind(function: Callable[..., Any], attribute: str, binding: _T) -> tuple[_T, ...]:
    bindings: Sequence[_T] | None = getattr(function, attribute, None)

    if not isinstance(bindings, Sequence):
        bindings = ()

    bindings = (*bindings, binding)
    setattr(function, attribute, bindings)

    return bindings


LISTENER_BINDINGS_ATTRIBUTE = "__listener_bindings__"


class ListenerBinding(ImmutableDataObject):
    address: LocalComponentAddress
    event: type | UnionType
    function: str


@overload
def listen(
    source: str,
    event: type[_EventT],
) -> Callable[
    [Callable[[Any, _EventT], None | Awaitable[None]]], Callable[[Any, _EventT], Awaitable[None]]
]:
    ...


@overload
def listen(
    source: str,
    event: UnionType,
) -> Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    ...


def listen(
    source: str,
    event: type[_EventT] | UnionType,
) -> Callable[
    [Callable[[Any, _EventT], None | Awaitable[None]]], Callable[[Any, _EventT], Awaitable[None]]
] | Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    def inner(function: Callable[[Any, Event], None | Awaitable[None]]) -> Any:
        _bind(
            function,
            LISTENER_BINDINGS_ATTRIBUTE,
            ListenerBinding(
                address=LocalComponentAddress(source),
                event=event,
                function=function.__name__,
            ),
        )

        return function

    return inner


PROCEDURE_BINDINGS_ATTRIBUTE = "__procedure_bindings__"


class ProcedureKind(str, Enum):
    QUERY = "query"
    ACTION = "action"
    JOB = "job"


class ProcedureSchemas(ImmutableDataObject):
    input: Mapping[str, Any] | None
    output: Mapping[str, Any]


class BaseProcedureBinding(ImmutableDataObject):
    kind: ProcedureKind
    name: str
    function: str
    schemas: ProcedureSchemas


class QueryBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.QUERY] = ProcedureKind.QUERY


class ActionBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.ACTION] = ProcedureKind.ACTION


class JobBinding(BaseProcedureBinding):
    kind: Literal[ProcedureKind.JOB] = ProcedureKind.JOB
    default_schedule: Schedule | None = None
    default_input: object | None = None


ProcedureBinding = QueryBinding | ActionBinding | JobBinding


def _get_schema(hint: Any) -> Mapping[str, Any]:
    schema = schema_of(hint)

    if schema.get("type") == "null":
        schema = {"title": "Null", "type": "null"}
    elif "definitions" in schema and schema["definitions"]:
        schema = list(schema["definitions"].values())[0]

    title = schema.get("title")
    if title is not None:
        if title.startswith("ParsingModel[") and title.endswith("]"):
            title = title[len("ParsingModel[") : -1]

        schema["title"] = title

    return schema


def _validate_procedure(
    function: Callable[..., Any],
    kind: ProcedureKind,
) -> ProcedureSchemas:
    signature = inspect.signature(function)
    parameters = [*signature.parameters.values()]
    if len(parameters) not in (1, 2) or any(
        parameter.kind not in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.POSITIONAL_ONLY)
        for parameter in parameters
    ):
        raise ValueError(
            f"{kind} {strify(function)} have exactly one or two positional parameters, 'self', and optionally, an input parameter"
        )

    hints = get_type_hints(function)

    if len(parameters) == 1:
        input_schema: Mapping[str, Any] | None = None
    else:
        input_parameter = parameters[1]
        if input_parameter.name not in hints:
            raise ValueError(
                f"second positional parameter '{input_parameter.name}' of {kind} {strify(function)} must have a type hint"
            )

        input_hint = hints[input_parameter.name]
        try:
            input_schema = _get_schema(input_hint)
        except Exception:
            raise ValueError(
                f"second positional parameter '{input_parameter.name}' of {kind} {strify(function)} must be parseable as a JSON object"
            )

    if "return" not in hints:
        raise ValueError(f"return type of {kind} {strify(function)} must be specified")

    output_hint = hints["return"]
    try:
        output_schema = _get_schema(output_hint)
    except Exception:
        raise ValueError(
            f"return type of of {kind} {strify(function)} must be serializable as a JSON object"
        )

    return ProcedureSchemas(
        input=input_schema,
        output=output_schema,
    )


_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def query(name: str) -> Callable[[_FunctionT], _FunctionT]:
    def bind(function: _FunctionT) -> _FunctionT:
        schemas = _validate_procedure(function, ProcedureKind.QUERY)
        _bind(
            function,
            PROCEDURE_BINDINGS_ATTRIBUTE,
            QueryBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
            ),
        )

        return function

    return bind


def action(name: str) -> Callable[[_FunctionT], _FunctionT]:
    def bind(function: _FunctionT) -> _FunctionT:
        schemas = _validate_procedure(function, ProcedureKind.ACTION)
        _bind(
            function,
            PROCEDURE_BINDINGS_ATTRIBUTE,
            ActionBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
            ),
        )

        return function

    return bind


def job(
    name: str,
    *,
    default_schedule: Schedule | None = None,
    default_input: object | None = None,
) -> Callable[[_FunctionT], _FunctionT]:
    def bind(function: _FunctionT) -> _FunctionT:
        parameters = inspect.signature(function).parameters
        if len(parameters) == 1 and default_input is not None:
            raise ValueError("job does not take any input, but a default input has been specified")

        schemas = _validate_procedure(function, ProcedureKind.JOB)
        _bind(
            function,
            PROCEDURE_BINDINGS_ATTRIBUTE,
            JobBinding(
                name=name,
                function=function.__name__,
                schemas=schemas,
                default_schedule=default_schedule,
                default_input=default_input,
            ),
        )

        return function

    return bind


@cached
def _get_listener_bindings(cls: type[_ComponentT]) -> Sequence[ListenerBinding]:
    return tuple(get_bindings(cls, LISTENER_BINDINGS_ATTRIBUTE, ListenerBinding))


@cached
def _get_query_bindings(cls: type[_ComponentT]) -> Mapping[str, QueryBinding]:
    return MappingProxyType(
        {
            binding.name: binding
            for binding in get_bindings(cls, PROCEDURE_BINDINGS_ATTRIBUTE, QueryBinding)
        }
    )


@cached
def _get_action_bindings(cls: type[_ComponentT]) -> Mapping[str, ActionBinding]:
    return MappingProxyType(
        {
            binding.name: binding
            for binding in get_bindings(cls, PROCEDURE_BINDINGS_ATTRIBUTE, ActionBinding)
        }
    )


@cached
def _get_job_bindings(cls: type[_ComponentT]) -> Mapping[str, JobBinding]:
    return MappingProxyType(
        {
            binding.name: binding
            for binding in get_bindings(cls, PROCEDURE_BINDINGS_ATTRIBUTE, JobBinding)
        }
    )
