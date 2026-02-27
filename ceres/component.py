import asyncio
import inspect
import traceback
import warnings
from abc import abstractmethod
from asyncio import CancelledError, TaskGroup
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import InitVar, dataclass, field
from datetime import timedelta
from functools import cached_property
from inspect import Parameter
from pathlib import Path
from string import ascii_lowercase
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Final,
    Literal,
    Protocol,
    Self,
    TypeAlias,
    TypedDict,
    Unpack,
    cast,
    final,
    get_args,
    get_type_hints,
    overload,
    override,
    runtime_checkable,
)

from pydantic import (
    AliasChoices,
    AliasPath,
    ConfigDict,
    NonNegativeInt,
    PositiveFloat,
    ValidationError,
)
from pydantic.fields import Deprecated, FieldInfo

from ceres._internal import util
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.lazy import __lazy_imports__
from ceres._internal.protocols import ComponentSource
from ceres._internal.util import OrderedWeakSet, PathLike, Undefined, cached, is_subtype
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.config import (
    ComponentConfig,
    ConnectionConfig,
    JobConfig,
    MethodSieveConfig,
    PrunerConfig,
    SieveConfig,
)
from ceres.data import (
    DataObject,
    MaybeSequence,
    Name,
    OrderedStrEnum,
    PositiveTimeDelta,
    StrEnum,
    WithDefaults,
    adapt,
)
from ceres.error import (
    Failure,
    ProcedureInternalError,
    ProcedureInvalidArgumentsError,
    ProcedureNotFoundError,
    ProcedureNotSubscribableError,
    ValidationProblem,
)
from ceres.event import (
    AttachedEvent,
    DetachedEvent,
    DisabledEvent,
    EnabledEvent,
    Event,
    ProcedureCalledEvent,
    ProcedureCancelledEvent,
    ProcedureCompletedEvent,
    ProcedureExceptionEvent,
    RoutineCancelledEvent,
    RoutineCompletedEvent,
    RoutineExceptionEvent,
    RoutineRestartedEvent,
    RoutineRestartingEvent,
    RoutineStartedEvent,
    RoutineStoppedEvent,
    StoppedEvent,
    StoppingEvent,
    WillDetachEvent,
)
from ceres.message import Message, MessageContent, MessageDirectionInput, MessageFilter
from ceres.node import Node
from ceres.util import concurrently
from ceres.variable import InternalVariableName, Variable

if TYPE_CHECKING:
    from pydantic.config import JsonDict
    from pydantic.types import Discriminator
    from sqlalchemy.ext.asyncio import AsyncConnection
    from starlette.responses import FileResponse, Response, StreamingResponse

    from ceres.connection import Connection, ConnectionField
    from ceres.connectivity import Connectivity
    from ceres.engine import Engine
    from ceres.particle import Particle
    from ceres.status import Status
else:
    Connection = object

with __lazy_imports__(__name__):
    from ceres.connection import ComponentConnectionManager
    from ceres.database import Database
    from ceres.job import ComponentJobManager
    from ceres.pruner import ComponentPrunerManager
    from ceres.reference import Reference, unref
    from ceres.sieve import ComponentSieveManager


class ComponentFilterArgs(BaseFilterArgs, total=False):
    root: Address
    address: AddressSelector | None
    enabled: bool | None
    running: bool | None


class ComponentFilter(BaseFilter):
    root: Address = Address.ROOT
    address: AddressSelector | None = None
    enabled: bool | None = None
    running: bool | None = None

    def matches(self, obj: Component | ComponentSystem) -> bool:
        system = util.as_component_system(obj)

        if self.address is not None:
            if not self.address.matches(system.address, self.root):
                return False
        if self.enabled is not None and system.enabled != self.enabled:
            return False
        if self.running is not None and system.running != self.running:
            return False

        return True


if TYPE_CHECKING:
    type Container = Component | ComponentSystem | Engine | None
else:
    type Container = Any


class Component(DataObject, ComponentSource):
    __slots__ = ("__system",)

    __with_name__: InitVar[Name | None] = field(default=None, kw_only=False)
    __with_config__: InitVar[ComponentConfig | None] = field(default=None)
    __with_container__: InitVar[Container] = field(default=None)

    def __post_init__(
        self,
        __with_name__: Name | None = None,
        __with_config__: ComponentConfig | None = None,
        __with_container__: Component | ComponentSystem | Engine | None = None,
    ) -> None:
        self.__system = ComponentSystem(
            self,
            __with_name__=__with_name__,
            __with_config__=__with_config__,
            __with_container__=__with_container__,
        )

        self.__setup__()

    @final
    @property
    @override
    def __database__(self) -> Database:
        return self.__system.database

    @final
    @override
    def __get_filter_defaults__(self) -> dict[str, Any]:
        return self.__system.__get_filter_defaults__()

    @final
    @property
    @override
    def __node__(self) -> Node:
        return self.__system

    @final
    @property
    @override
    def __system__(self) -> ComponentSystem:
        return self.__system

    @final
    @property
    @override
    def __component__(self) -> Component:
        return self

    @final
    @property
    def system(self) -> ComponentSystem:
        return self.__system

    def __setup__(self) -> None:
        pass

    def __connectivity__(self) -> Connectivity | None:
        return None

    def __static_connections__(self) -> Iterable[ConnectionConfig]:
        return ()

    def __static_sieves__(self) -> Iterable[SieveConfig]:
        return ()

    def __static_jobs__(self) -> Iterable[JobConfig]:
        return ()

    def __static_pruners__(self) -> Iterable[PrunerConfig]:
        return ()

    @final
    def __bind__(self, bind: ComponentSystem, /) -> None:
        self.__system = bind

    @final
    def __unref__(self) -> Self:
        return self


@cached(weak=True)
def get_listener_bindings(cls: type) -> Sequence[ListenerBinding]:
    """
    Get all listener bindings for this component class.
    """
    return get_component_method_bindings(cls, ListenerBinding)


@cached(weak=True)
def get_routine_bindings(cls: type) -> Sequence[RoutineBinding]:
    """
    Get all routine bindings for this component class.
    """
    return get_component_method_bindings(cls, RoutineBinding)


@cached(weak=True)
def get_query_bindings(cls: type) -> Mapping[str, QueryBinding]:
    """
    Get all query bindings for this component class. Returns a mapping of query names to query
    bindings.
    """
    return MappingProxyType(
        {
            name: binding
            for name, binding in get_procedure_bindings(cls).items()
            if isinstance(binding, QueryBinding)
        }
    )


def get_query_binding(cls: type, name: str) -> QueryBinding | None:
    """
    Get a query binding for this component class by name. Returns `None` if the query binding
    does not exist.
    """
    procedure = get_procedure_binding(cls, name)
    if not isinstance(procedure, QueryBinding):
        return None

    return procedure


@cached(weak=True)
def get_action_bindings(cls: type) -> Mapping[str, ActionBinding]:
    """
    Get all action bindings for this component class. Returns a mapping of action names to
    action bindings.
    """
    return MappingProxyType(
        {
            name: binding
            for name, binding in get_procedure_bindings(cls).items()
            if isinstance(binding, ActionBinding)
        }
    )


def get_action_binding(cls: type, name: str) -> ActionBinding | None:
    """
    Get an action binding for this component class by name. Returns `None` if the action binding
    does not exist.
    """
    procedure = get_procedure_binding(cls, name)
    if not isinstance(procedure, ActionBinding):
        return None

    return procedure


@cached(weak=True)
def get_procedure_bindings(cls: type) -> Mapping[Name, ProcedureBinding]:
    """
    Get all procedure bindings (actions and queries) for this component class. Returns a mapping
    of procedure names to procedure bindings.
    """
    queries = get_component_method_bindings(cls, QueryBinding)
    actions = get_component_method_bindings(cls, ActionBinding)
    procedures = sorted([*queries, *actions], key=lambda current: current.name)

    return MappingProxyType({binding.name: binding for binding in procedures})


def get_procedure_binding(cls: type, name: str) -> ProcedureBinding | None:
    """
    Get a procedure binding (action or query) for this component class by name. Returns `None`
    if the procedure does not exist.
    """
    name = _get_normalized_name(name)
    return get_procedure_bindings(cls).get(name)


@cached(weak=True)
def get_sieve_bindings(cls: type) -> Mapping[Name, SieveBinding]:
    """
    Get all sieve bindings for this component class.
    """
    return MappingProxyType(
        {binding.name: binding for binding in get_component_method_bindings(cls, SieveBinding)}
    )


def get_sieve_binding(cls: type, name: str) -> SieveBinding | None:
    """
    Get a sieve binding for this component class by name. Returns `None` if the sieve binding
    does not exist.
    """
    name = _get_normalized_name(name)
    return get_sieve_bindings(cls).get(name)


class ConnectionBinding(DataObject.Frozen):
    name: Name
    field: Name


@cached(weak=True)
def get_connection_bindings(cls: type) -> Mapping[Name, ConnectionBinding]:
    """
    Get all connection bindings for this component class.
    """

    from ceres.connection import Connection

    __pydantic_fields__: dict[str, FieldInfo] = getattr(cls, "__pydantic_fields__", {})

    bindings: Mapping[Name, ConnectionBinding] = {}

    for field, info in __pydantic_fields__.items():
        marker = next(
            (current for current in info.metadata if isinstance(current, BoundField.Marker)), None
        )

        if marker is not None:
            name = marker.name
        else:
            name = None

        if name is None:
            name = _get_normalized_name(field)

        if is_subtype(info.annotation, Connection):
            bindings[name] = ConnectionBinding(name=name, field=field)
        else:
            continue

    return MappingProxyType(bindings)


def get_connection_binding(cls: type, name: str) -> ConnectionBinding | None:
    """
    Get a connection binding for this component class by name. Returns `None` if the connection
    binding does not exist.
    """
    name = _get_normalized_name(name)
    return get_connection_bindings(cls).get(name)


class ListenerBinding(DataObject, config=ConfigDict(arbitrary_types_allowed=True)):
    name: Name
    method: Name
    event: type | UnionType
    local: bool
    reference: tuple[str, ...]
    address: AddressSelector | None


_ListenerMethodReturn = None | Awaitable[None]
_ListenerMethod = (
    Callable[[Any], _ListenerMethodReturn] | Callable[[Any, Any], _ListenerMethodReturn]
)
_ListenerMethodTransform = Callable[[_ListenerMethod], _ListenerMethod]


@overload
def listener(method: _ListenerMethod) -> _ListenerMethod: ...


@overload
def listener(
    *,
    event: type | UnionType | None = None,
    local: bool | None = None,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerMethodTransform: ...


@util.validated_function
def listener(
    method: _ListenerMethod | None = None,
    *,
    event: type | UnionType | None = None,
    local: bool | None = None,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerMethod | _ListenerMethodTransform:
    reference = util.seq(reference or ())

    if address is not None:
        address = AddressSelector(address)

    if local is None:
        local = len(reference) == 0 and address is None

    def listener(method: _ListenerMethod) -> _ListenerMethod:
        signature = inspect.signature(method)

        assigned_event_type = event

        if assigned_event_type is None:
            hints = get_type_hints(method)
            parameters = list(signature.parameters.values())
            if len(parameters) > 1:
                event_parameter = parameters[1]
                assigned_event_type = hints.get(event_parameter.name)

        if assigned_event_type is None:
            assigned_event_type = Event

        _add_binding(
            method,
            ListenerBinding(
                name=_get_bound_name(method),
                method=util.get_function_name(method),
                reference=tuple(reference),
                address=address,
                local=local,
                event=assigned_event_type,
            ),
        )

        return method

    if method is None:
        return listener

    return listener(method)


class ProcedureType(StrEnum):
    QUERY = "query"
    ACTION = "action"


class ProcedureOutputType(StrEnum):
    VALUE = "value"
    STREAMING = "streaming"
    FILE = "file"


class ProcedureArgumentsInfo(DataObject.Frozen):
    json_schema: Mapping[str, Any]
    required: bool


class ProcedureValueOutputInfo(DataObject.Frozen):
    type: Literal[ProcedureOutputType.VALUE] = ProcedureOutputType.VALUE
    json_schema: Mapping[str, Any]


class ProcedureFileOutputInfo(DataObject.Frozen):
    type: Literal[ProcedureOutputType.FILE] = ProcedureOutputType.FILE
    media: str | None = None


class ProcedureStreamingOutputInfo(DataObject.Frozen):
    type: Literal[ProcedureOutputType.STREAMING] = ProcedureOutputType.STREAMING
    media: str


ProcedureOutputInfo: TypeAlias = (
    ProcedureValueOutputInfo | ProcedureFileOutputInfo | ProcedureStreamingOutputInfo
)


class ProcedureAccessLevel(OrderedStrEnum):
    @classmethod
    @override
    def __order_mapping__(cls) -> dict[ProcedureAccessLevel, int]:
        from ceres.user import UserRole

        return {
            cls.PUBLIC: UserRole.VIEWER.order - 1,
            cls.VIEWERS: UserRole.VIEWER.order,
            cls.OPERATORS: UserRole.OPERATOR.order,
            cls.ADMINS: UserRole.ADMIN.order,
        }

    PUBLIC = "public"
    VIEWERS = "viewers"
    OPERATORS = "operators"
    ADMINS = "admins"


RawProcedureAccessLevel = Literal["public", "viewers", "operators", "admins"]
ProcedureAccessLevelInput = ProcedureAccessLevel | RawProcedureAccessLevel

ProcedurePermissions = ProcedureAccessLevel
ProcedurePermissionsInput = ProcedureAccessLevelInput


class _ProcedureBinding(DataObject.Frozen):
    type: ProcedureType
    name: Name
    permissions: ProcedurePermissions
    method: str
    live: bool
    arguments: ProcedureArgumentsInfo | None
    output: ProcedureOutputInfo


class QueryBinding(_ProcedureBinding):
    type: Literal[ProcedureType.QUERY] = ProcedureType.QUERY
    poll: PositiveTimeDelta = timedelta(seconds=1)


class ActionBinding(_ProcedureBinding):
    type: Literal[ProcedureType.ACTION] = ProcedureType.ACTION


ProcedureBinding: TypeAlias = QueryBinding | ActionBinding


type OutputResponse = Response
type OutputMediaType = str


class BaseOutput:
    @abstractmethod
    def to_response(self) -> OutputResponse: ...


class FileOutput(BaseOutput):
    __slots__ = (
        "path",
        "media",
        "http_status",
        "http_headers",
        "http_filename",
        "on_exit",
    )

    def __init__(
        self,
        path: PathLike,
        media: OutputMediaType | None = None,
        *,
        http_status: int = 200,
        http_headers: Mapping[str, str] | None = None,
        http_filename: str | None = None,
        on_exit: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.path = Path(path)
        self.media = media
        self.http_status = http_status
        self.http_headers = http_headers
        self.http_filename = http_filename
        self.on_exit = on_exit

    @override
    def to_response(self) -> FileResponse:
        from starlette.background import BackgroundTask
        from starlette.responses import FileResponse

        if self.on_exit is not None:
            background = BackgroundTask(self.on_exit)
        else:
            background = None

        return FileResponse(
            self.path,
            media_type=self.media,
            status_code=self.http_status,
            headers=self.http_headers,
            filename=self.http_filename,
            background=background,
        )


type DataStreamChunk = bytes | memoryview
type DataStream = AsyncIterable[DataStreamChunk] | Callable[[], AsyncIterable[DataStreamChunk]]


class StreamingOutput(BaseOutput):
    __slots__ = (
        "stream",
        "media",
        "http_status",
        "http_headers",
        "on_exit",
    )

    def __init__(
        self,
        stream: DataStream,
        media: OutputMediaType,
        *,
        http_status: int = 200,
        http_headers: Mapping[str, str] | None = None,
        on_exit: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.stream = stream
        self.media = media
        self.http_status = http_status
        self.http_headers = http_headers
        self.on_exit = on_exit

    @override
    def to_response(self) -> StreamingResponse:
        from starlette.background import BackgroundTask
        from starlette.responses import StreamingResponse

        if callable(self.stream):
            stream = self.stream()
        else:
            stream = self.stream

        if self.on_exit is not None:
            background = BackgroundTask(self.on_exit)
        else:
            background = None

        return StreamingResponse(
            stream,
            media_type=self.media,
            status_code=self.http_status,
            headers=self.http_headers,
            background=background,
        )


Output: TypeAlias = FileOutput | StreamingOutput


@overload
def query[**P, T](method: Callable[P, T]) -> Callable[P, T]: ...


@overload
def query[**P, T: BaseOutput | Awaitable[BaseOutput]](
    *,
    media: str,
    permit: ProcedurePermissionsInput = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


@overload
def query[**P, T](
    *,
    poll: float | timedelta = ...,
    permit: ProcedurePermissionsInput = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def query[**P, T](
    method: Callable[P, T] | None = None,
    *,
    poll: float | timedelta = timedelta(seconds=5),
    media: str | None = None,
    permit: ProcedurePermissionsInput = ProcedureAccessLevel.PUBLIC,
) -> Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]:
    def query(method: Callable[P, T]) -> Callable[P, T]:
        info = _get_procedure_method_info(method, ProcedureType.QUERY, media)
        _add_binding(
            method,
            QueryBinding(
                name=_get_bound_name(method),
                permissions=ProcedureAccessLevel(permit),
                method=util.get_function_name(method),
                arguments=info.arguments,
                output=info.output,
                live=info.live,
                poll=poll if isinstance(poll, timedelta) else timedelta(seconds=poll),
            ),
        )

        return method

    if method is None:
        return query

    return query(method)


@overload
def action[**P, T](method: Callable[P, T]) -> Callable[P, T]: ...


@overload
def action[**P, T](
    *,
    media: str | None = None,
    permit: ProcedurePermissionsInput = ...,
) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def action[**P, T](
    method: Callable[P, T] | None = None,
    *,
    media: str | None = None,
    permit: ProcedurePermissionsInput = ProcedureAccessLevel.OPERATORS,
) -> Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]:
    def action(method: Callable[P, T]) -> Callable[P, T]:
        validated = _get_procedure_method_info(method, ProcedureType.ACTION, media)
        _add_binding(
            method,
            ActionBinding(
                name=_get_bound_name(method),
                permissions=ProcedureAccessLevel(permit),
                method=util.get_function_name(method),
                arguments=validated.arguments,
                output=validated.output,
                live=validated.live,
            ),
        )

        return method

    if method is None:
        return action

    return action(method)


class _ProcedureMethodInfo(DataObject.Frozen):
    name: str
    method: str
    arguments: ProcedureArgumentsInfo | None
    output: ProcedureOutputInfo
    live: bool


def _get_procedure_method_info(
    method: Callable[..., Any],
    type_: ProcedureType,
    media: str | None,
    /,
) -> _ProcedureMethodInfo:
    method = util.get_inner_function(method)
    signature = inspect.signature(method)

    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{type_} {util.strify(method)} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{type_} {util.strify(method)} cannot have positional-only arguments")

    arguments_json_schema = util.get_args_model(method).model_json_schema()
    arguments_required = len(arguments_json_schema.get("properties", {}).get("required", [])) > 0
    arguments = ProcedureArgumentsInfo(
        json_schema=arguments_json_schema,
        required=arguments_required,
    )

    output_annotation = util.get_return_annotation(method, Undefined)
    if output_annotation is Undefined:
        raise ValueError(f"return type of {type_} {util.strify(method)} must be specified")

    live = inspect.isasyncgenfunction(method)

    if live:
        error = ValueError(
            f"return type of live {type_} {util.strify(method)} must be AsyncIterable[T]"
        )

        try:
            if output_annotation.__name__ != "AsyncIterable":
                raise error

            output_annotation = get_args(output_annotation)[0]
        except Exception:
            raise error

    if isinstance(output_annotation, type) and issubclass(output_annotation, BaseOutput):
        if issubclass(output_annotation, StreamingOutput):
            if media is None:
                raise ValueError(
                    f"`media` type must be specified for {type_} {util.strify(method)}"
                )

            output = ProcedureStreamingOutputInfo(media=media)
        elif issubclass(output_annotation, FileOutput):
            output = ProcedureFileOutputInfo(media=media)
        else:
            raise ValueError(
                f"output type of {type_} {util.strify(method)} must be either `FileOutput` or `StreamingOutput` if it is a subtype of `Output`."
            )
    else:
        try:
            output_json_schema = adapt(output_annotation).json_schema()
            output = ProcedureValueOutputInfo(json_schema=output_json_schema)
        except Exception as exception:
            raise ValueError(
                f"output type of {type_} {util.strify(method)} must be either a JSON serializable type, `FileOutput` or `StreamingOutput`. Type is not JSON serializable: "
                f"{exception}"
            )

    return _ProcedureMethodInfo(
        name=_get_bound_name(method),
        method=util.get_function_name(method),
        arguments=arguments,
        output=output,
        live=live,
    )


_BINDINGS_ATTRIBUTE = "__bindings__"


class RoutineRestartPolicy(StrEnum):
    NEVER = "never"
    ALWAYS = "always"
    ON_COMPLETED = "on-completed"
    ON_EXCEPTION = "on-exception"


RoutineRestartPolicyLiteral = Literal[
    "never",
    "always",
    "on-completed",
    "on-exception",
]


class RoutineBinding(DataObject.Frozen):
    method: Name
    restart: RoutineRestartPolicy
    restart_delay: PositiveTimeDelta


_RoutineMethodReturn = Awaitable[None]
_RoutineMethod = Callable[[Any], _RoutineMethodReturn]
_RoutineMethodHandler = Callable[[_RoutineMethod], _RoutineMethod]


@overload
def routine(
    *,
    restart: RoutineRestartPolicy | RoutineRestartPolicyLiteral = RoutineRestartPolicy.NEVER,
    restart_delay: PositiveFloat | PositiveTimeDelta = timedelta(seconds=1),
) -> _RoutineMethodHandler: ...


@overload
def routine(method: _RoutineMethod) -> _RoutineMethod: ...


@util.validated_function
def routine(
    method: _RoutineMethod | None = None,
    *,
    restart: RoutineRestartPolicy | RoutineRestartPolicyLiteral = RoutineRestartPolicy.NEVER,
    restart_delay: PositiveFloat | PositiveTimeDelta = timedelta(seconds=1),
) -> _RoutineMethod | _RoutineMethodHandler:
    def routine(method: _RoutineMethod) -> _RoutineMethod:
        _add_binding(
            method,
            RoutineBinding(
                method=util.get_function_name(method),
                restart=RoutineRestartPolicy(restart),
                restart_delay=util.decode_td(restart_delay),
            ),
        )

        return method

    if method is None:
        return routine

    return routine(method)


@runtime_checkable
class _MethodBinding(Protocol):
    @property
    def method(self) -> str: ...


def get_component_method_bindings_on[T: _MethodBinding](
    method: Callable[..., Any],
    binding_cls: type[T],
    /,
) -> Sequence[T]:
    method = util.get_inner_function(method)
    output: list[T] = []

    if values := getattr(method, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_component_method_binding_on[T: _MethodBinding](
    method: Callable[..., Any],
    binding_cls: type[T],
    /,
) -> T | None:
    bindings = get_component_method_bindings_on(method, binding_cls)
    if bindings:
        return bindings[0]

    return None


def get_component_method_bindings[T: _MethodBinding](
    cls: type,
    binding_cls: type[T],
) -> Sequence[T]:
    bindings: dict[str, T] = {}

    for cls in reversed(cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_component_method_bindings_on(member, binding_cls):
                bindings[binding.method] = binding

    return sorted(bindings.values(), key=lambda current: current.method)


class SieveBinding(DataObject.Frozen):
    name: Name
    method: Name
    retries: NonNegativeInt | None
    retry_delay: PositiveTimeDelta
    filter: MessageFilter | None
    connections: tuple[Name, ...] | None = None


type SieveMethod[S, T: Particle] = (
    Callable[[S, Message], T | None | Awaitable[T | None]]
    | Callable[[S, AsyncIterable[Message]], AsyncIterable[T]]
)


@overload
def sieve[S, T: Particle](method: SieveMethod[S, T], /) -> SieveMethod[S, T]: ...


@overload
def sieve[S, T: Particle](
    connection: MaybeSequence[ConnectionField] | None = None,
    /,
    direction: MaybeSequence[MessageDirectionInput] | None = "receive",
    *,
    name: Name | None = None,
    retries: NonNegativeInt | None = None,
    retry_delay: PositiveTimeDelta = timedelta(seconds=5),
    contains: MaybeSequence[MessageContent] | None = None,
    prefix: MaybeSequence[MessageContent] | None = None,
    suffix: MaybeSequence[MessageContent] | None = None,
) -> Callable[[SieveMethod[S, T]], SieveMethod[S, T]]: ...


def sieve[S, T: Particle](
    first: SieveMethod[S, T] | MaybeSequence[ConnectionField] | None = None,
    /,
    direction: MaybeSequence[MessageDirectionInput] | None = "receive",
    *,
    name: Name | None = None,
    retries: NonNegativeInt | None = None,
    retry_delay: PositiveTimeDelta = timedelta(seconds=5),
    contains: MaybeSequence[MessageContent] | None = None,
    prefix: MaybeSequence[MessageContent] | None = None,
    suffix: MaybeSequence[MessageContent] | None = None,
) -> SieveMethod[S, T] | Callable[[SieveMethod[S, T]], SieveMethod[S, T]]:
    if first is None:
        method = None
        connections = None
    elif inspect.ismethod(first):
        method = first
        connections = None
    else:
        method = None
        connections = tuple(
            [
                current.name
                for current in cast("Sequence[ConnectionField]", util.seq(first))
                if current.name is not None
            ]
        )

    from ceres.message import Message

    filtering = Message.FilterArgs()
    if direction is not None:
        filtering["direction"] = direction
    if contains is not None:
        filtering["contains"] = contains
    if suffix is not None:
        filtering["suffix"] = suffix
    if prefix is not None:
        filtering["prefix"] = prefix

    if filtering:
        filter = Message.Filter.model_validate(filtering)
    else:
        filter = None

    def sieve(method: SieveMethod[S, T]) -> SieveMethod[S, T]:
        _add_binding(
            method,
            SieveBinding(
                name=name or _get_bound_name(method),
                method=util.get_function_name(method),
                retries=retries,
                retry_delay=retry_delay,
                filter=filter,
                connections=connections,
            ),
        )
        return method

    if method is None:
        return sieve

    return sieve(method)


def _add_binding(method: Callable[..., object], binding: _MethodBinding) -> None:
    method = util.get_inner_function(method)
    bindings: Sequence[_MethodBinding] | None = getattr(method, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    bindings = list(bindings)
    bindings.append(binding)
    setattr(method, _BINDINGS_ATTRIBUTE, tuple(bindings))


def _get_bound_name(function: Callable[..., Any]) -> str:
    return _get_normalized_name(util.get_function_name(function))


def _get_normalized_name(name: str) -> Name:
    return name.replace("_", "-").strip().strip("-")


warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


@final
class ComponentSystem(Node, ComponentSource):
    __slots__ = (
        "_name",
        "_config",
        "_referencers",
        "_container",
        "_children",
        "_enabled",
        "_database",
        "_component",
    )

    def __init__(
        self,
        component: Component,
        /,
        *,
        __with_name__: Name | None = None,
        __with_config__: ComponentConfig | None = None,
        __with_container__: Component | ComponentSystem | Engine | None = None,
    ) -> None:
        super().__init__()

        if __with_name__ is None:
            __with_name__ = util.randstr(ascii_lowercase, 8)
        if isinstance(__with_container__, Component):
            __with_container__ = __with_container__.system

        self._name = __with_name__
        self._config: ComponentConfig | None = __with_config__
        self._referencers: Final[OrderedWeakSet[ComponentSystem]] = OrderedWeakSet()
        self._container: ComponentSystem | Engine | None = None
        self._children: Final[dict[Name, ComponentSystem]] = {}
        self._enabled = False
        self._database: Database | None = None
        self._component: Final[Component] = component
        self._component.__bind__(self)

        if __with_container__ is not None:
            __with_container__.attach(self)
            assert self._container is __with_container__

        self.sync_references()

        # Add connections from bindings, static connections, then configuration.
        connections: dict[str, Connection] = {}

        # Load connections from bindings.
        for connection in self.get_connection_bindings().values():
            instance = getattr(self.component, connection.field, None)
            if instance is not None:
                if instance.name is None:
                    instance.name = connection.name

                connections[instance.name] = instance

        # Load connections from static connections.
        connections.update(
            {
                connection.name: connection.create()
                for connection in self.component.__static_connections__()
            }
        )

        # Load connections from configuration.
        if self.config is not None:
            for config in self.config.connections:
                connections[config.name] = config.create()

        # Add loaded connections to manager.
        for connection in connections.values():
            self.connections.add(connection)

        # Load sieves from static sieves.
        sieves = {sieve.name: sieve for sieve in self.component.__static_sieves__()}
        # Load sieves from bindings.
        sieves.update(
            {
                binding.name: MethodSieveConfig(
                    name=binding.name,
                    method=binding.method,
                    retries=binding.retries,
                    retry_delay=binding.retry_delay,
                    filter=binding.filter,
                )
                for binding in self.get_sieve_bindings().values()
            }
        )
        # Load sieves from configuration.
        if self.config is not None:
            sieves.update({sieve.name: sieve for sieve in self.config.sieves})
        # Add loaded sieves to manager.
        for sieve in sieves.values():
            self.sieves.add(sieve)

        # Load jobs from static jobs.
        jobs = {job.name: job for job in self.component.__static_jobs__()}
        # Load jobs from configuration.
        if self.config is not None:
            jobs.update({job.name: job for job in self.config.jobs})
        # Add loaded jobs to manager.
        for job in jobs.values():
            self.jobs.add(job)

        # Load pruners from static pruners.
        pruners = {pruner.name: pruner for pruner in self.component.__static_pruners__()}
        # Load pruners from configuration.
        if self.config is not None:
            pruners.update({pruner.name: pruner for pruner in self.config.pruners})
        # Add loaded pruners to manager.
        for pruner in pruners.values():
            self.pruners.add(pruner)

    @override
    def __str__(self) -> str:
        return repr(self)

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({util.reprify(self.component)})"

    @property
    @override
    def __container__(self) -> Node | None:
        return self._container

    @property
    @override
    def __node__(self) -> Node:
        return self

    @property
    @override
    def __component__(self) -> Component:
        return self._component

    @property
    @override
    def __system__(self) -> ComponentSystem:
        return self

    @property
    @override
    def address(self) -> Address:
        """
        The current address of the component.
        """
        if self.parent is not None:
            return self.parent.address / self.name

        return Address.ROOT

    @property
    def container(self) -> ComponentSystem | Engine | None:
        """
        Get the container of the component system. This can be either another `ComponentSystem` as
        its parent, or an `Engine`. Returns `None` if the component has no parent or containing
        engine.
        """
        return self._container

    @container.setter
    def container(self, container: ComponentSystem | Engine | None) -> None:
        from ceres.engine import Engine

        self._container = container
        if isinstance(container, Engine):
            if container.root is not self:
                container.attach(self)
        elif isinstance(container, ComponentSystem):
            if container._children.get(self._name) is not self:
                container.attach(self)

    @property
    @override
    def engine(self) -> Engine | None:
        """
        Get the engine this component is contained by. Returns `None` if the component is not
        contained by any engine.
        """
        container = self._container
        if container is None:
            return None

        return container.engine

    @property
    @override
    def database(self) -> Database:
        container = self._container
        if container is not None:
            return container.database

        if self._database is None:
            self._database = Database()
        return self._database

    @property
    @override
    def config(self) -> ComponentConfig | None:
        """
        The configuration of the component, if available.
        """
        return self._config

    @config.setter
    def config(self, config: ComponentConfig | None) -> None:
        """
        Set the configuration of the component. Note this doesn't actually sync the component with
        the configuration. It will only indicate to the engine, that this configuration is the one
        currently applied. Generally, this is only for internal use and should not be used directly.
        """
        self._config = config

    @property
    @override
    def root(self) -> ComponentSystem:
        current: ComponentSystem | None = self
        while current.parent is not None:
            current = current.parent

        return current

    @property
    def parent(self) -> ComponentSystem | None:
        """
        Get the parent component's system if it exists, or return `None`.
        """
        return util.as_component_system(self._container)

    @cached_property
    def jobs(self) -> ComponentJobManager:
        return ComponentJobManager(self)

    @cached_property
    def connections(self) -> ComponentConnectionManager:
        return ComponentConnectionManager(self)

    @cached_property
    def sieves(self) -> ComponentSieveManager:
        return ComponentSieveManager(self)

    @cached_property
    def pruners(self) -> ComponentPrunerManager:
        return ComponentPrunerManager(self)

    @override
    async def __node_sync__(self, connection: AsyncConnection | None = None) -> None:
        await super().__node_sync__(connection)
        self._enabled = await self.__get_enabled_in_database()

    @property
    def name(self) -> Name:
        return self._name

    @name.setter
    def name(self, name: Name) -> None:
        if self.parent is None:
            self._name = name
            return

        if name in self.parent._children:
            raise ValueError(f"parent already has child named {self._name!r}")

        self._name = name
        self.parent._children[name] = self
        self.__propagate_tree_change()

        self._name = name

    @property
    def component(self) -> Component:
        """
        Get the underlying component of the component system.
        """
        return self._component

    @property
    def enabled(self) -> bool:
        """
        `True` if the component is enabled. Enabled components start automatically when their parent
        or containing engine starts.
        """
        return self._enabled

    async def enable(self) -> None:
        """
        Enable the component. Enabled components start automatically when their parent or containing
        engine starts.
        """
        await self.__set_enabled_in_database(True)
        self._enabled = True
        self.events.emit(EnabledEvent)

    async def disable(self) -> None:
        """
        Disable the component. Disabled components will not start automatically when their parent
        or containing engine starts.
        """
        await self.__set_enabled_in_database(False)
        self._enabled = False
        self.events.emit(DisabledEvent)

    async def up(self) -> None:
        """
        Enable and start the component.
        """
        await self.enable()
        self.start()

    async def down(self) -> None:
        """
        Disable and stop the component.
        """
        await self.disable()
        await self.stop()

    async def __get_enabled_in_database(self) -> bool:
        return await self.variables.read(
            InternalVariableName.ENABLED,
            parse=bool,
            default=False,
        )

    async def __set_enabled_in_database(self, enabled: bool) -> None:
        await self.variables.create(
            Variable(
                address=self.address,
                name=InternalVariableName.ENABLED,
                value=enabled,
            ),
            upsert=True,
        )

    @property
    def children(self) -> Sequence[ComponentSystem]:
        """
        Get all child component systems of this component.
        """
        return list(self._children.values())

    def get_listener_bindings(self) -> Sequence[ListenerBinding]:
        """
        Get all listener bindings for this component.
        """
        return get_listener_bindings(type(self.component))

    def get_routine_bindings(self) -> Sequence[RoutineBinding]:
        """
        Get all routine bindings for this component.
        """
        return get_routine_bindings(type(self.component))

    def get_query_bindings(self) -> Mapping[Name, QueryBinding]:
        """
        Get all query bindings for this component. Returns a mapping of query names to query
        bindings.
        """
        return get_query_bindings(type(self.component))

    def get_query_binding(self, name: str) -> QueryBinding | None:
        """
        Get a query binding for this component by name. Returns `None` if the query binding does not
        exist.
        """
        return get_query_binding(type(self.component), name)

    def get_action_bindings(self) -> Mapping[Name, ActionBinding]:
        """
        Get all action bindings for this component. Returns a mapping of action names to action
        bindings.
        """
        return get_action_bindings(type(self.component))

    def get_action_binding(self, name: str) -> ActionBinding | None:
        """
        Get an action binding for this component by name. Returns `None` if the action binding does
        not exist.
        """
        return get_action_binding(type(self.component), name)

    def get_procedure_bindings(self) -> Mapping[Name, ProcedureBinding]:
        """
        Get all procedure bindings (actions and queries) for this component. Returns a mapping of
        procedure names to procedure bindings.
        """
        return get_procedure_bindings(type(self.component))

    def get_procedure_binding(self, name: str) -> ProcedureBinding | None:
        """
        Get a procedure binding (action or query) for this component by name. Returns `None` if the
        procedure does not exist.
        """
        return get_procedure_binding(type(self.component), name)

    def get_sieve_bindings(self) -> Mapping[Name, SieveBinding]:
        """
        Get all sieve bindings for this component.
        """
        return get_sieve_bindings(type(self.component))

    def get_sieve_binding(self, name: str) -> SieveBinding | None:
        """
        Get a sieve binding for this component by name. Returns `None` if the sieve binding does not
        exist.
        """
        return get_sieve_binding(type(self.component), name)

    def get_connection_bindings(self) -> Mapping[Name, ConnectionBinding]:
        """
        Get all connection bindings for this component.
        """
        return get_connection_bindings(type(self.component))

    def get_connection_binding(self, name: str) -> ConnectionBinding | None:
        """
        Get a connection binding for this component by name. Returns `None` if the connection
        binding does not exist.
        """
        return get_connection_binding(type(self.component), name)

    def __propagate_tree_change(self) -> None:
        for component in self.root.get_components():
            component.system.__on_tree_change()

    def __on_tree_change(self) -> None:
        self.sync_child_order()
        self.sync_references()

    def sync_references(self) -> tuple[list[Reference], list[Reference]]:
        resolved: list[Reference] = []
        unresolved: list[Reference] = []

        references = self.get_references()
        for reference in references:
            reference.__reference_root__ = self.component
            component = unref(reference)

            if component is not None:
                resolved.append(reference)
                component.system._referencers.add(self)
            else:
                unresolved.append(reference)

        discard: list[ComponentSystem] = []
        for referencer in self._referencers:
            if self.component not in referencer.get_referenced_components():
                discard.append(referencer)

        self._referencers.difference_update(discard)
        return resolved, unresolved

    def get_references(self) -> list[Reference]:
        from ceres.reference import Reference

        references: list[Reference] = []

        def visit(obj: Any) -> bool:
            if isinstance(obj, Reference):
                references.append(obj)
                return False

            return True

        util.traverse(self.component, visit)
        return references

    def has_reference_to(self, component: Component) -> bool:
        from ceres.reference import unref

        referenced = self.get_referenced_components()
        for other in referenced:
            if id(other) == id(unref(component)):
                return True

        return False

    def get_referenced_components(self, reference: str | None = None) -> list[Component]:
        from ceres.reference import Reference, unref

        root = self.component

        if reference is not None:
            for segment in reference.split("."):
                root = getattr(root, segment, None)
                if root is None:
                    break

        components: list[Component] = []
        if root is None:
            return components

        def visit(obj: Any) -> bool:
            if util.lenient_isinstance(obj, (Component, Reference)):
                obj = unref(obj)
                if obj is not self and obj is not self.component:
                    components.append(obj)
                    return False

            return True

        util.traverse(root, visit)
        return components

    def get_referencing_components(self, recursive: bool = False) -> list[Component]:
        if recursive:
            return self.__get_referencing_components_recursive()

        return util.as_components(self._referencers)

    def __get_referencing_components_recursive(self) -> list[Component]:
        seen: set[int] = set()
        direct = self.get_referencing_components(recursive=False)
        referencers = list(direct)

        for referencer in direct:
            if id(referencer) not in seen:
                seen.add(id(referencer))
                referencers.extend(referencer.system.__get_referencing_components_recursive())

        return referencers

    def attach(
        self,
        child: Component | ComponentSystem,
        /,
        name: Name | None = None,
    ) -> None:
        """
        Add a child component to this component's children.
        """
        if isinstance(child, Component):
            child = child.system

        if child is self or self.contains(child):
            raise ValueError("component cannot contain itself")

        child.detach()

        name = name or child.name
        current = self._children.get(name)
        if current is not None:
            raise ValueError(f"child with name '{name}' already exists")

        if child.name != name:
            child.name = name

        self._children[child.name] = child
        child._container = self

        self.__propagate_tree_change()
        child.events.emit(AttachedEvent)

    def detach(self) -> None:
        """
        Remove the component from its container (either its parent component, or its containing
        engine). If the component has no container, this does nothing.
        """
        if self._container is None:
            return

        engine = util.as_engine(self._container)
        if engine is not None:
            self.events.emit(WillDetachEvent)
            address_before = self.address
            logging_before = self.get_resolved_logging_config()

            self._container = None
            engine.root = None
            self.__propagate_tree_change()

            engine.events.propagate(
                DetachedEvent(address=address_before),
                logging=logging_before,
            )
            return

        parent = self.parent
        if parent is None:
            return

        current = parent._children.get(self.name)

        try:
            if current is not None and current is self:
                self.events.emit(WillDetachEvent)

                address_before = self.address
                logging_before = self.get_resolved_logging_config()

                parent._children.pop(self.name, None)
                self._container = None

                self.__propagate_tree_change()
                parent.__propagate_tree_change()

                parent.events.propagate(
                    DetachedEvent(address=address_before),
                    logging=logging_before,
                )
                self.events.emit(DetachedEvent)
        finally:
            self._container = None

    @override
    def get_component(
        self,
        address: str | DynamicAddress | None = None,  # TODO: Don't allow this to be `None`.
        /,
    ) -> Component | None:
        if not address:
            return self.component

        if not isinstance(address, DynamicAddress):
            address = DynamicAddress(address)

        if address.is_absolute and self.parent is not None:
            return self.root.get_component(address)

        current: ComponentSystem | None = self
        for name in address.names:
            if current is None:
                break

            current = current._children.get(name)

        if current is None:
            return None

        return current.component

    @override
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Component]:
        components: list[Component] = []

        overrides = ComponentFilter(**kwargs)
        if isinstance(filter, ComponentFilter):
            filter = filter.with_overrides(overrides)
        elif isinstance(filter, AddressSelector):
            filter = ComponentFilter(address=filter).with_overrides(overrides)
        else:
            filter = overrides

        filter = filter.with_defaults(ComponentFilter(root=self.address))

        def traverse(current: ComponentSystem) -> None:
            if (inclusive or current is not self) and filter.matches(current):
                components.append(current.component)

            for component in current._children.values():
                traverse(component)

        traverse(self)

        return components

    @override
    async def get_status(self) -> Status:
        status = await super().get_status()
        status.enabled = self.enabled
        status.connectivity = self.component.__connectivity__()
        return status

    def contains(
        self,
        component: Component | ComponentSystem,
        *,
        inclusive: bool = False,
    ) -> bool:
        system = util.as_component_system(component)
        current: ComponentSystem | None = system if inclusive else system.parent
        while current is not None:
            if current is system:
                return True

            current = current.parent

        return False

    def get_ancestor_components(self, *, inclusive: bool = False) -> list[Component]:
        """
        Return a group of all ancestor components in ascending order. If `inclusive` is `True`,
        include this component itself as the first component in the sequence.
        """
        ancestors: list[Component] = []

        current: ComponentSystem | None = self if inclusive else self.parent
        while current is not None:
            ancestors.append(current.component)
            current = current.parent

        return ancestors

    @override
    def start(
        self,
        *,
        on_completed: Callable[[Self], None] | None = None,
        on_exception: Callable[[Self, BaseException], None] | None = None,
        all_enabled: bool = True,
    ) -> None:
        for component in reversed(self.get_ancestor_components()):
            component.system.start(all_enabled=False)

        super().start(
            on_completed=on_completed,
            on_exception=on_exception,
        )

        if all_enabled:
            for child in self.children:
                if child.enabled:
                    child.start(all_enabled=True)

    @override
    async def __run__(self) -> None:
        try:
            for component in reversed(self.get_ancestor_components()):
                component.system.start(all_enabled=False)

            await self.__node_sync__()

            await concurrently(
                super().__run__(),
                self.__run_routines(),
                self.jobs.__run__(),
                self.connections.__run__(),
                self.sieves.__run__(),
                self.pruners.__run__(),
            )
        except Exception:
            self.log.error("An error occurred during component system execution.", exc_info=True)
            traceback.print_exc()
            raise

    async def __run_routine(self, binding: RoutineBinding) -> None:
        routine = getattr(self.component, binding.method, None)
        if routine is None:
            return

        self.events.emit(RoutineStartedEvent, routine=binding.method)

        try:
            while True:
                try:
                    await routine()
                    self.events.emit(RoutineCompletedEvent, routine=binding.method)
                    if binding.restart == RoutineRestartPolicy.ON_COMPLETED:
                        break
                except Exception as exception:
                    self.events.emit(
                        RoutineExceptionEvent,
                        routine=binding.method,
                        traceback=util.get_traceback(exception),
                    )
                    if binding.restart == RoutineRestartPolicy.ON_EXCEPTION:
                        break

                if binding.restart == RoutineRestartPolicy.NEVER:
                    break

                self.events.emit(
                    RoutineRestartingEvent,
                    routine=binding.method,
                    delay=binding.restart_delay,
                )
                await asyncio.sleep(binding.restart_delay.total_seconds())
                self.events.emit(RoutineRestartedEvent, routine=binding.method)
        except CancelledError:
            self.events.emit(RoutineCancelledEvent, routine=binding.method)
            raise
        finally:
            self.events.emit(RoutineStoppedEvent, routine=binding.method)

    async def __run_routines(self) -> None:
        async with TaskGroup() as tasks:
            for binding in self.get_routine_bindings():
                tasks.create_task(self.__run_routine(binding))

    @override
    def __stopping__(self) -> None:
        self.events.emit(StoppingEvent)

    @override
    async def __stop__(self) -> None:
        while any(child.running for child in self.children):
            await concurrently(child.stop() for child in self.children if child.running)

        await self.settle()

    @override
    async def __post_stop__(self) -> None:
        await super().__post_stop__()
        await self.flush()

        if self._database is not None:
            await self._database.dispose()
            self._database = None

        self.events.emit(StoppedEvent)

    async def __invoke(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> Any:
        if arguments is None:
            arguments = {}

        if (
            (binding := self.get_procedure_binding(procedure)) is None
            or (method := getattr(self.component, binding.method, None)) is None
            or not inspect.ismethod(method)
        ):
            raise Failure(ProcedureNotFoundError)

        validated = util.create_validated_function(method)

        try:
            self.events.emit(ProcedureCalledEvent, procedure=procedure)
            return await util.awaitify(validated(**arguments))
        except CancelledError:
            self.events.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except ValidationError as error:
            if method.__name__ in error.title:
                raise Failure(
                    ProcedureInvalidArgumentsError(
                        problems=ValidationProblem.extract(error, arguments)
                    )
                )

            raise
        except Exception as exception:
            traceback = util.get_traceback(exception)
            self.events.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))

    async def call(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> object | None:
        """
        Call a procedure with the given `arguments`.
        """
        binding = self.get_procedure_binding(procedure)
        if binding is None:
            raise Failure(ProcedureNotFoundError)

        output = await self.__invoke(procedure, arguments)

        if isinstance(output, BaseOutput):
            # If the result is an `Output` object, just return it directly.
            return output

        if not binding.live:
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)
            return output

        try:
            match binding:
                # If the procedure is a live query, we just return the first output.
                case QueryBinding():
                    async for current in output:
                        return current

                    return None
                # If the procedure is a live action, iterate through all outputs and return the
                # last one.
                case ActionBinding():
                    last: object | None = None
                    async for current in output:
                        last = current
                    return last
        except Exception as exception:
            traceback = util.get_traceback(exception)
            self.events.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))
        finally:
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)

    async def subscribe(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> AsyncIterable[object | None]:
        """
        Subscribe to a procedure with the given `arguments`. Not all procedures are subscribable.
        """
        binding = self.get_procedure_binding(procedure)
        if binding is None:
            raise Failure(ProcedureNotFoundError)

        output = await self.__invoke(procedure, arguments)

        if not binding.live:
            if isinstance(binding, ActionBinding):
                raise Failure(ProcedureNotSubscribableError)

            try:
                while True:
                    yield await self.__invoke(procedure, arguments)
                    await asyncio.sleep(binding.poll.total_seconds())
            except CancelledError:
                self.events.emit(ProcedureCancelledEvent, procedure=procedure)
                raise
            except Exception as exception:
                traceback = util.get_traceback(exception)
                self.events.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
                raise Failure(ProcedureInternalError(traceback=list(traceback)))

        try:
            if output is not None:
                async for current in output:
                    yield current
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)
        except CancelledError:
            self.events.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except Exception as exception:
            traceback = util.get_traceback(exception)
            self.events.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))

    def sync_child_order(self) -> None:
        if self._config is None:
            return

        order: list[ComponentSystem] = []
        for config in self._config.components:
            component = self._children.get(config.name)
            if component is not None:
                order.append(component)

        for component in self._children.values():
            if not any(current is component for current in order):
                order.append(component)

        self._children.clear()
        for component in order:
            self._children[component.name] = component


class Bound[T]:
    if TYPE_CHECKING:

        @overload
        def __get__(self, instance: None, owner: type[Connection]) -> ConnectionField: ...
        @overload
        def __get__(self, instance: Any, owner: type[Connection]) -> ConnectionField | T: ...
        @overload
        def __get__(self, instance: Any, owner: type[Connection]) -> T: ...

        @overload
        def __get__(self, instance: None, owner: type[Any]) -> BoundField: ...
        @overload
        def __get__(self, instance: Any, owner: type[Any]) -> T: ...
        def __get__(self, instance: Any, owner: type[Any]) -> BoundField | T: ...

        def __set__(self, instance: Any, value: T) -> None: ...


@classmethod
def __class_getitem__(cls: Any, args: Any | tuple[Any]) -> Any:
    if not isinstance(args, tuple):
        args = (args,)

    return Annotated[args[0], BoundField.Marker(), *args[1:]]


Bound.__class_getitem__ = __class_getitem__  # type: ignore


class BoundFieldArgs(TypedDict, total=False):
    name: Name
    defaults: Mapping[str, Any] | None

    # Common Pydantic arguments for `FieldInfo`.
    annotation: type[Any] | None
    default_factory: Callable[[], Any] | Callable[[dict[str, Any]], Any] | None
    alias: str | None
    alias_priority: int | None
    validation_alias: str | AliasPath | AliasChoices | None
    serialization_alias: str | None
    title: str | None
    field_title_generator: Callable[[str, FieldInfo], str] | None
    description: str | None
    examples: list[Any] | None
    discriminator: str | Discriminator | None
    deprecated: Deprecated | str | bool | None
    json_schema_extra: JsonDict | Callable[[JsonDict], None] | None
    frozen: bool | None
    validate_default: bool | None
    repr: bool
    init: bool | None
    init_var: bool | None
    kw_only: bool | None
    coerce_numbers_to_str: bool | None
    fail_fast: bool | None


try:

    class _FieldInfo(FieldInfo):  # type: ignore
        pass
except Exception as exception:
    raise RuntimeError("Could not inherit from `pydantic.fields.FieldInfo`.") from exception


class _Empty:
    pass


class BoundField[T](_FieldInfo, Bound[T] if TYPE_CHECKING else _Empty):
    __slots__ = ("name", "marker")

    @dataclass(slots=True)
    class Marker:
        """
        Metadata marker for a bound object. Currently only `Connection` objects can be bound to a
        component.
        """

        name: str | None = None

    def __init__(
        self,
        default: Any = Undefined,
        **kwargs: Unpack[BoundFieldArgs],
    ) -> None:
        name = kwargs.pop("name", None)
        defaults = kwargs.pop("defaults", None)

        if name is None and defaults is not None and "name" in defaults:
            name = defaults["name"]

        super().__init__(default=default, **kwargs)

        self.name = name
        self.marker = BoundField.Marker(name=name)
        self.metadata.append(self.marker)

        if defaults:
            self.metadata.append(WithDefaults(**defaults))

    def __set_name__(self, owner: type[Any], name: str) -> None:
        if self.marker.name is None:
            self.marker.name = name
