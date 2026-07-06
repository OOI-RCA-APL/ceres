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
    ByteSize,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    ValidationError,
)
from pydantic.fields import Deprecated, FieldInfo

from ceres.__internal__.filter import BaseFilter, BaseFilterArgs
from ceres.__internal__.lazy import __lazy_imports__
from ceres.__internal__.protocols import ComponentSource
from ceres.__internal__.utilities.algorithms import traverse
from ceres.__internal__.utilities.caching import cached
from ceres.__internal__.utilities.collections import OrderedWeakSet, seq
from ceres.__internal__.utilities.functions import get_function_name, get_inner_function
from ceres.__internal__.utilities.randomize import randstr
from ceres.__internal__.utilities.text import reprify
from ceres.__internal__.utilities.typing import (
    as_component_system,
    as_components,
    as_engine,
    extract_annotation,
    get_return_annotation,
    lenient_isinstance,
)
from ceres.__internal__.utilities.undefined import Undefined
from ceres.__internal__.utilities.validation import (
    create_validated_function,
    get_args_model,
    validated_function,
)
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.concurrency import awaitify, concurrently, sleep
from ceres.config import ComponentAccessLevel as ComponentAccessLevel
from ceres.config import ComponentAccessLevelInput as ComponentAccessLevelInput
from ceres.config import (
    ComponentConfig,
    ConnectionConfig,
    JobConfig,
    MethodSieveConfig,
    PrunerConfig,
    SieveConfig,
)
from ceres.config import RawComponentAccessLevel as RawComponentAccessLevel
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
    ProcedureInternalError,
    ProcedureInvalidArgumentsError,
    ProcedureNotFoundError,
    ProcedureNotSubscribableError,
    ValidationProblem,
    trace,
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
    StartExceptionEvent,
    StopExceptionEvent,
    StoppedEvent,
    StoppingEvent,
    WillDetachEvent,
)
from ceres.message import Message, MessageData, MessageDirectionInput, MessageFilter
from ceres.node import Node
from ceres.timing import delta
from ceres.variable import InternalVariableName, Variable

if TYPE_CHECKING:
    from os import PathLike

    from pydantic.config import JsonDict
    from pydantic.types import Discriminator
    from sqlalchemy.ext.asyncio import AsyncConnection
    from starlette.responses import FileResponse, Response, StreamingResponse

    from ceres.connection import Buffer, Connection, ConnectionField
    from ceres.connectivity import Connectivity
    from ceres.engine import Engine
    from ceres.particle import Particle
    from ceres.status import Status
else:
    Connection = Any
    ConnectionField = Any

with __lazy_imports__(__name__):
    from ceres.connection import ComponentConnectionManager
    from ceres.database import Database
    from ceres.job import JobManager
    from ceres.pruner import PrunerManager
    from ceres.reference import Reference, unref
    from ceres.sieve import SieveManager

__all__ = [
    "Component",
    "listener",
    "query",
    "action",
    "routine",
    "sieve",
]


class ComponentFilterArgs(BaseFilterArgs, total=False):
    """Keyword-form arguments for `ComponentFilter`, used by helpers like `get_components`."""

    root: Address
    address: AddressSelector | None
    enabled: bool | None
    running: bool | None


class ComponentFilter(BaseFilter):
    """Filter for selecting components by address and lifecycle state."""

    root: Address = Address.ROOT
    """Address to interpret relative selectors against, defaults to the absolute root."""

    address: AddressSelector | None = None
    """Optional selector restricting matches by address."""

    enabled: bool | None = None
    """When set, only match components whose `enabled` flag equals this value."""

    running: bool | None = None
    """When set, only match components whose `running` flag equals this value."""

    def matches(self, obj: Component | ComponentSystem) -> bool:
        """Return `True` if `obj` satisfies every configured criterion."""
        system = as_component_system(obj)

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
    """Primary unit of organization in Ceres.

    A `Component` is a Pydantic-style dataclass that bundles configurable state with decorated
    methods (`@listener`, `@routine`, `@query`, `@action`, `@sieve`) and child components. Each
    driver, simulator, sieve container, etc. is a `Component`.

    Components are arranged in a tree, each with an address like `@parent.child`. The runtime
    behaviour (lifecycle, event bus, references) lives on the paired `ComponentSystem` accessible
    via `system`. The component class itself stays focused on declarative state and the methods
    the user writes.

    Subclasses typically override `__setup__`, `__start__`, `__stop__`, and the
    `__static_connections__` / `__static_sieves__` / `__static_jobs__` / `__static_pruners__`
    hooks to declare static behaviour, or define methods decorated with `@listener`, `@routine`,
    `@query`, `@action`, and `@sieve`.
    """

    __slots__ = ("__system",)

    __with_name__: InitVar[Name | None] = field(default=None, kw_only=False)
    """Internal init-only argument, the name to register the component under."""

    __with_config__: InitVar[ComponentConfig | None] = field(default=None)
    """Internal init-only argument, the configuration that produced this component."""

    __with_container__: InitVar[Container] = field(default=None)
    """Internal init-only argument, the parent component, system, or engine."""

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
        """The runtime system that owns this component's lifecycle, events, and managers."""
        return self.__system

    def __setup__(self) -> None:
        """Hook called after the component is constructed and bound to its system.

        Override to perform initialization that depends on `self.system` being available.
        """

    def __start__(self) -> None | Awaitable[None]:
        """Hook called when the component starts.

        Override to perform startup work. May be synchronous or return an awaitable.
        """

    def __stop__(self) -> None | Awaitable[None]:
        """Hook called when the component stops.

        Override to release resources. May be synchronous or return an awaitable. Always called
        even if `__start__` raised.
        """

    def __connectivity__(self) -> Connectivity | None:
        """Return the component's connectivity status, or `None` if not applicable."""
        return None

    def __static_connections__(self) -> Iterable[ConnectionConfig]:
        """Return connection configurations declared statically by this component class."""
        return ()

    def __static_sieves__(self) -> Iterable[SieveConfig]:
        """Return sieve configurations declared statically by this component class."""
        return ()

    def __static_jobs__(self) -> Iterable[JobConfig]:
        """Return job configurations declared statically by this component class."""
        return ()

    def __static_pruners__(self) -> Iterable[PrunerConfig]:
        """Return pruner configurations declared statically by this component class."""
        return ()

    @final
    def __bind__(self, bind: ComponentSystem, /) -> None:
        """Re-bind this component to a different `ComponentSystem`.

        Used internally when a system is constructed for a component, or when the engine swaps a
        component into a fresh system during reconfiguration.
        """
        self.__system = bind

    @final
    def __unref__(self) -> Self:
        return self


@cached(weak=True)
def get_listener_bindings(cls: type) -> Sequence[ListenerBinding]:
    """Return every listener binding declared by `cls` and its bases."""
    return _get_component_method_bindings(cls, ListenerBinding)


@cached(weak=True)
def get_routine_bindings(cls: type, /) -> Sequence[RoutineBinding]:
    """Return every routine binding declared by `cls` and its bases."""
    return _get_component_method_bindings(cls, RoutineBinding)


@cached(weak=True)
def get_query_bindings(cls: type, /) -> Mapping[str, QueryBinding]:
    """Return a mapping of query names to query bindings declared on `cls`."""
    return MappingProxyType(
        {
            name: binding
            for name, binding in get_procedure_bindings(cls).items()
            if isinstance(binding, QueryBinding)
        }
    )


@cached(weak=True)
def get_action_bindings(cls: type, /) -> Mapping[str, ActionBinding]:
    """Return a mapping of action names to action bindings declared on `cls`."""
    return MappingProxyType(
        {
            name: binding
            for name, binding in get_procedure_bindings(cls).items()
            if isinstance(binding, ActionBinding)
        }
    )


@cached(weak=True)
def get_procedure_bindings(cls: type, /) -> Mapping[Name, ProcedureBinding]:
    """Return a name-keyed mapping of every procedure binding (queries plus actions) on `cls`."""
    queries = _get_component_method_bindings(cls, QueryBinding)
    actions = _get_component_method_bindings(cls, ActionBinding)
    procedures = sorted([*queries, *actions], key=lambda current: current.name)

    return MappingProxyType({binding.name: binding for binding in procedures})


@cached(weak=True)
def get_sieve_bindings(cls: type, /) -> Mapping[Name, SieveBinding]:
    """Return a name-keyed mapping of every sieve binding declared on `cls`."""
    return MappingProxyType(
        {binding.name: binding for binding in _get_component_method_bindings(cls, SieveBinding)}
    )


class ConnectionBinding(DataObject.Frozen):
    """Pairing of a connection's exposed name with the field that holds it on the component."""

    name: Name
    """Name to register the connection under."""

    field: Name
    """Attribute name on the component class that holds the `Connection` instance."""


@cached(weak=True)
def get_connection_bindings(cls: type, /) -> Mapping[Name, ConnectionBinding]:
    """Discover every `Bound[ConnectionField]` field on `cls` and return their bindings.

    Args:
        cls: A component class to inspect.

    Returns:
        A mapping of connection name to `ConnectionBinding` for every bound connection field.

    Raises:
        TypeError: If a bound field is missing a recognized bound-object marker, or has more
            than one.
    """
    from ceres.connection import ConnectionField

    __pydantic_fields__: dict[str, FieldInfo] = getattr(cls, "__pydantic_fields__", {})

    bindings: Mapping[Name, ConnectionBinding] = {}

    def get_marker[T: BoundField.Marker](
        metadata: Sequence[Any],
        marker_class: type[T],
    ) -> T | None:
        return next((current for current in metadata if isinstance(current, marker_class)), None)

    for field, info in __pydantic_fields__.items():
        if info.init_var:
            continue

        metadata = extract_annotation(info).metadata
        if get_marker(metadata, BoundField.Marker) is None:
            continue

        exact = []
        connection = get_marker(metadata, ConnectionField.Marker)
        if connection is not None:
            exact.append(connection)

        if not exact:
            raise TypeError(
                f"Field '{field}' in component '{cls}' is marked as bound but does not have a "
                "specific bound object type."
            )
        if len(exact) > 1:
            raise TypeError(
                f"Field '{field}' in component '{cls}' has multiple possible bound types."
                f"{', '.join(type(marker).__name__ for marker in exact)}."
            )

        marker = exact[0]
        name: str | None = None
        if marker is not None:
            name = marker.name
        if name is None:
            name = field

        if isinstance(marker, ConnectionField.Marker):
            bindings[name] = ConnectionBinding(name=name, field=field)
        else:
            raise TypeError(
                f"Field '{field}' in component '{cls}' is marked as bound but is not of a "
                "known object type."
            )

    return MappingProxyType(bindings)


class ListenerBinding(DataObject.Frozen, config=ConfigDict(arbitrary_types_allowed=True)):
    """Description of a single listener method registered on a component class."""

    name: Name
    """Normalized listener name, derived from the method name."""

    method: Name
    """Name of the underlying method to invoke when the event fires."""

    event: type | UnionType
    """Event type (or union of types) the listener responds to."""

    local: bool
    """When `True`, only events emitted on this component itself are delivered."""

    reference: tuple[str, ...]
    """Dotted reference paths whose target components also forward matching events."""

    address: AddressSelector | None
    """Optional address selector restricting which other components forward events."""


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


@validated_function
def listener(
    method: _ListenerMethod | None = None,
    *,
    event: type | UnionType | None = None,
    local: bool | None = None,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerMethod | _ListenerMethodTransform:
    """Mark a method as a listener that runs in response to events on the event bus.

    The decorated method may take just `self`, or `self` plus the event instance. The event type
    is inferred from the second parameter's type hint when `event` is not given explicitly,
    falling back to the base `Event` so the listener fires on every event.

    Args:
        method: When used without arguments, the method being decorated.
        event: Specific event type (or union of types) to listen for. If omitted, inferred from
            the method's second parameter type hint.
        local: When `True`, only events emitted on the listener's own component are delivered.
            Defaults to `True` when neither `reference` nor `address` is given, otherwise
            `False`.
        reference: One or more dotted reference paths (relative to the component) whose targets'
            events should also be delivered.
        address: One or more address selectors identifying additional components whose events
            should be delivered.

    Returns:
        Either the decorated method (when used without arguments) or a decorator returning the
        decorated method.
    """
    reference = seq(reference or ())

    if address is not None:
        address = AddressSelector(address)

    if local is None:
        # Default to local when no explicit cross-component routing was requested, this keeps
        # listeners isolated by default and matches what most components expect.
        local = len(reference) == 0 and address is None

    def listener(method: _ListenerMethod) -> _ListenerMethod:
        signature = inspect.signature(method)

        assigned_event_type = event

        if assigned_event_type is None:
            # Infer the event type from the second parameter (the first is `self`).
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
                method=get_function_name(method),
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
    """Discriminator for the two RPC-style procedures, queries and actions."""

    QUERY = "query"
    """Read-only procedure that returns a value derived from component state."""

    ACTION = "action"
    """Mutating procedure that performs side effects."""


class ProcedureOutputType(StrEnum):
    """Shape of the value a procedure returns."""

    VALUE = "value"
    """A JSON-serializable value."""

    STREAMING = "streaming"
    """A streaming response of arbitrary bytes."""

    FILE = "file"
    """A file response served from a path on disk."""


class ProcedureArgumentsInfo(DataObject.Frozen):
    """Metadata describing the arguments accepted by a procedure."""

    json_schema: Mapping[str, Any]
    """JSON schema describing the procedure's argument object."""

    required: bool
    """`True` when at least one argument is required."""


class ProcedureValueOutputInfo(DataObject.Frozen):
    """Output metadata for a procedure that returns a JSON-serializable value."""

    type: Literal[ProcedureOutputType.VALUE] = ProcedureOutputType.VALUE
    json_schema: Mapping[str, Any]
    """JSON schema describing the procedure's return value."""


class ProcedureFileOutputInfo(DataObject.Frozen):
    """Output metadata for a procedure that returns a `FileOutput`."""

    type: Literal[ProcedureOutputType.FILE] = ProcedureOutputType.FILE
    media: str | None = None
    """Optional declared media type, used as the default when the output omits one."""


class ProcedureStreamingOutputInfo(DataObject.Frozen):
    """Output metadata for a procedure that returns a `StreamingOutput`."""

    type: Literal[ProcedureOutputType.STREAMING] = ProcedureOutputType.STREAMING
    media: str
    """Media type the stream produces, required for streaming outputs."""


ProcedureOutputInfo: TypeAlias = (
    ProcedureValueOutputInfo | ProcedureFileOutputInfo | ProcedureStreamingOutputInfo
)


class ProcedureAccessLevel(OrderedStrEnum):
    """Access level controlling which user roles may invoke a procedure.

    The order is derived from `UserRole`, with `PUBLIC` sitting one step below `VIEWER` so
    unauthenticated callers can be permitted explicitly.
    """

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
    """Anyone, including unauthenticated callers, may invoke the procedure."""

    VIEWERS = "viewers"
    """Authenticated users with viewer role or higher may invoke the procedure."""

    OPERATORS = "operators"
    """Operators or admins may invoke the procedure."""

    ADMINS = "admins"
    """Only admins may invoke the procedure."""


RawProcedureAccessLevel = Literal["public", "viewers", "operators", "admins"]
ProcedureAccessLevelInput = ProcedureAccessLevel | RawProcedureAccessLevel

ProcedurePermissions = ProcedureAccessLevel
ProcedurePermissionsInput = ProcedureAccessLevelInput


class _ProcedureBinding(DataObject.Frozen):
    """Shared metadata for both query and action bindings."""

    type: ProcedureType
    """Discriminator distinguishing queries from actions."""

    name: Name
    """Normalized procedure name as exposed externally."""

    permissions: ProcedurePermissions
    """Minimum access level required to invoke the procedure."""

    method: str
    """Name of the underlying method on the component class."""

    live: bool
    """`True` when the underlying method is an async generator yielding live results."""

    arguments: ProcedureArgumentsInfo | None
    """Argument metadata, or `None` if the procedure takes no arguments."""

    output: ProcedureOutputInfo
    """Output metadata describing what the procedure returns."""


class QueryBinding(_ProcedureBinding):
    """Procedure binding for a `@query` method, polled when subscribed by default."""

    type: Literal[ProcedureType.QUERY] = ProcedureType.QUERY
    poll: PositiveTimeDelta = timedelta(seconds=1)
    """Polling interval used when subscribing to a non-live query."""


class ActionBinding(_ProcedureBinding):
    """Procedure binding for an `@action` method, invoked imperatively rather than polled."""

    type: Literal[ProcedureType.ACTION] = ProcedureType.ACTION


ProcedureBinding: TypeAlias = QueryBinding | ActionBinding


type OutputResponse = Response
type OutputMediaType = str


class BaseOutput:
    """Base class for procedure outputs that should be returned as raw HTTP responses."""

    @abstractmethod
    def to_response(self) -> OutputResponse:
        """Convert this output into a Starlette response."""
        ...


class FileOutput(BaseOutput):
    """Procedure output that streams a file from disk as the HTTP response."""

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
        path: str | PathLike,
        media: OutputMediaType | None = None,
        *,
        http_status: int = 200,
        http_headers: Mapping[str, str] | None = None,
        http_filename: str | None = None,
        on_exit: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        """Construct a file output.

        Args:
            path: Path to the file to send.
            media: Optional MIME type, inferred from the path when omitted.
            http_status: HTTP status code for the response.
            http_headers: Additional response headers.
            http_filename: Filename hint to send via the `Content-Disposition` header.
            on_exit: Optional async callback run after the response finishes streaming.
        """
        self.path = Path(path)
        self.media = media
        self.http_status = http_status
        self.http_headers = http_headers
        self.http_filename = http_filename
        self.on_exit = on_exit

    @override
    def to_response(self) -> FileResponse:
        """Build a Starlette `FileResponse` that streams `self.path` to the client.

        Returns:
            A `FileResponse` configured with the stored media type, status code, headers, filename
            hint, and optional background cleanup task.
        """
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
    """Procedure output that streams arbitrary bytes as the HTTP response body."""

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
        """Construct a streaming output.

        Args:
            stream: Async iterable of byte chunks, or a zero-arg factory returning one. A factory
                lets the response start the iterable lazily.
            media: MIME type to advertise on the response.
            http_status: HTTP status code for the response.
            http_headers: Additional response headers.
            on_exit: Optional async callback run after the response finishes streaming.
        """
        self.stream = stream
        self.media = media
        self.http_status = http_status
        self.http_headers = http_headers
        self.on_exit = on_exit

    @override
    def to_response(self) -> StreamingResponse:
        """Build a Starlette `StreamingResponse` that relays `self.stream` to the client.

        If `self.stream` is a callable factory, it is invoked to produce the async
        iterable lazily.

        Returns:
            A `StreamingResponse` configured with the stored media type, status code,
            headers, and optional background cleanup task.
        """
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
    """Mark a method as a query, a read-only RPC endpoint with optional polling subscription.

    Queries may be plain methods returning a JSON-serializable value, methods returning a
    `FileOutput` or `StreamingOutput`, or async generators yielding live values.

    Args:
        method: When used without arguments, the method being decorated.
        poll: Interval used when subscribing to a non-live query.
        media: Media type for streaming queries, required when the return type is `StreamingOutput`
            and otherwise optional.
        permit: Minimum access level required to call the query.

    Returns:
        Either the decorated method (when used without arguments) or a decorator returning the
        decorated method.
    """

    def query(method: Callable[P, T]) -> Callable[P, T]:
        info = _get_procedure_method_info(method, ProcedureType.QUERY, media)
        _add_binding(
            method,
            QueryBinding(
                name=_get_bound_name(method),
                permissions=ProcedureAccessLevel(permit),
                method=get_function_name(method),
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
    """Mark a method as an action, a mutating RPC endpoint that performs side effects.

    Like `@query`, actions may return JSON-serializable values, file or streaming outputs, or yield
    live values from an async generator.

    Args:
        method: When used without arguments, the method being decorated.
        media: Media type for streaming actions, required when the return type is
            `StreamingOutput` and otherwise optional.
        permit: Minimum access level required to invoke the action, defaults to operator level.

    Returns:
        Either the decorated method (when used without arguments) or a decorator returning the
        decorated method.
    """

    def action(method: Callable[P, T]) -> Callable[P, T]:
        validated = _get_procedure_method_info(method, ProcedureType.ACTION, media)
        _add_binding(
            method,
            ActionBinding(
                name=_get_bound_name(method),
                permissions=ProcedureAccessLevel(permit),
                method=get_function_name(method),
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
    """Result of inspecting a procedure method, used to build `QueryBinding`/`ActionBinding`."""

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
    method = get_inner_function(method)
    signature = inspect.signature(method)

    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{type_} {method} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{type_} {method} cannot have positional-only arguments")

    arguments_json_schema = get_args_model(method).model_json_schema()
    # `required` is a top-level key in the JSON schema, not nested inside `properties`.
    arguments_required = len(arguments_json_schema.get("required", [])) > 0
    arguments = ProcedureArgumentsInfo(
        json_schema=arguments_json_schema,
        required=arguments_required,
    )

    output_annotation = get_return_annotation(method, Undefined)
    if output_annotation is Undefined:
        raise ValueError(f"return type of {type_} {method} must be specified")

    live = inspect.isasyncgenfunction(method)

    if live:
        error = ValueError(f"return type of live {type_} {method} must be AsyncIterable[T]")

        try:
            if output_annotation.__name__ != "AsyncIterable":
                raise error

            output_annotation = get_args(output_annotation)[0]
        except Exception:
            raise error

    if isinstance(output_annotation, type) and issubclass(output_annotation, BaseOutput):
        if issubclass(output_annotation, StreamingOutput):
            if media is None:
                raise ValueError(f"`media` type must be specified for {type_} {method}")

            output = ProcedureStreamingOutputInfo(media=media)
        elif issubclass(output_annotation, FileOutput):
            output = ProcedureFileOutputInfo(media=media)
        else:
            raise ValueError(
                f"output type of {type_} {method} must be either `FileOutput` or `StreamingOutput` if it is a subtype of `Output`."
            )
    else:
        try:
            output_json_schema = adapt(output_annotation).json_schema()
            output = ProcedureValueOutputInfo(json_schema=output_json_schema)
        except Exception as exception:
            raise ValueError(
                f"output type of {type_} {method} must be either a JSON serializable type, `FileOutput` or `StreamingOutput`. Type is not JSON serializable: "
                f"{exception}"
            )

    return _ProcedureMethodInfo(
        name=_get_bound_name(method),
        method=get_function_name(method),
        arguments=arguments,
        output=output,
        live=live,
    )


_BINDINGS_ATTRIBUTE = "__bindings__"


class RoutineRestartPolicy(StrEnum):
    """When a routine should be restarted after it finishes running."""

    NEVER = "never"
    """Run once, never restart."""

    ALWAYS = "always"
    """Restart after every completion or exception."""

    ON_COMPLETED = "on-completed"
    """Restart only after a successful completion (not on exception)."""

    ON_EXCEPTION = "on-exception"
    """Restart only after an exception (not on successful completion)."""


RoutineRestartPolicyLiteral = Literal[
    "never",
    "always",
    "on-completed",
    "on-exception",
]


class RoutineBinding(DataObject.Frozen):
    """Description of a single routine method registered on a component class."""

    method: Name
    """Name of the underlying method to call."""

    restart: RoutineRestartPolicy
    """Restart policy controlling whether the routine runs again after finishing."""

    restart_delay: PositiveTimeDelta
    """Delay between a routine ending and being restarted."""


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


@validated_function
def routine(
    method: _RoutineMethod | None = None,
    *,
    restart: RoutineRestartPolicy | RoutineRestartPolicyLiteral = RoutineRestartPolicy.NEVER,
    restart_delay: PositiveFloat | PositiveTimeDelta = timedelta(seconds=1),
) -> _RoutineMethod | _RoutineMethodHandler:
    """Mark an async method as a routine, a long-running background task.

    Routines are started when the component starts and cancelled when it stops. The
    `restart` policy controls whether the routine is re-run after it finishes, with
    `restart_delay` inserted between attempts.

    Args:
        method: When used without arguments, the method being decorated.
        restart: Restart policy. Defaults to `NEVER`, meaning the routine runs once.
        restart_delay: Delay before restarting, accepted as either seconds or a `timedelta`.

    Returns:
        Either the decorated method (when used without arguments) or a decorator returning the
        decorated method.
    """

    def routine(method: _RoutineMethod) -> _RoutineMethod:
        _add_binding(
            method,
            RoutineBinding(
                method=get_function_name(method),
                restart=RoutineRestartPolicy(restart),
                restart_delay=delta(restart_delay),
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
    """Return all bindings of type `binding_cls` attached to the given method by a decorator."""
    method = get_inner_function(method)
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
    """Return the first binding of type `binding_cls` on the method, or `None` if absent."""
    bindings = get_component_method_bindings_on(method, binding_cls)
    if bindings:
        return bindings[0]

    return None


def _get_component_method_bindings[T: _MethodBinding](
    cls: type,
    binding_cls: type[T],
) -> Sequence[T]:
    bindings: dict[str, T] = {}

    # Walk the MRO from base to derived so subclass overrides win when they re-decorate the same
    # method name.
    for cls in reversed(cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_component_method_bindings_on(member, binding_cls):
                bindings[binding.method] = binding

    return sorted(bindings.values(), key=lambda current: current.method)


class SieveBinding(DataObject.Frozen):
    """Description of a single sieve method registered on a component class."""

    name: Name
    """Sieve name, used as its key in the sieve manager."""

    method: Name
    """Name of the underlying method on the component."""

    stored: bool
    """Whether particles produced by the sieve should be persisted."""

    retries: NonNegativeInt | None
    """Maximum number of retries for failed messages, or `None` for unlimited."""

    retry_delay: PositiveTimeDelta
    """Delay between retry attempts."""

    filter: MessageFilter | None
    """Optional filter restricting which messages reach the sieve."""

    connections: tuple[ConnectionField, ...] | None
    """Specific connections the sieve subscribes to, or `None` to subscribe to all."""

    buffer_size: ByteSize | None = Field(gt=0)
    """Optional cap on the in-memory buffer this sieve receives."""

    buffer_drop: ByteSize | None = Field(gt=0)
    """Optional threshold at which oldest data is dropped from the buffer."""


type SieveMethod[S, T: Particle] = (
    Callable[[S, Message], T | None | Awaitable[T | None]]
    | Callable[[S, AsyncIterable[Message]], AsyncIterable[T]]
    | Callable[[S, Buffer], Iterable[T]]
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
    stored: bool = True,
    retries: NonNegativeInt | None = None,
    retry_delay: PositiveTimeDelta = timedelta(seconds=5),
    contains: MaybeSequence[MessageData] | None = None,
    prefix: MaybeSequence[MessageData] | None = None,
    suffix: MaybeSequence[MessageData] | None = None,
    buffer_size: int | str | None = None,
    buffer_drop: int | str | None = None,
) -> Callable[[SieveMethod[S, T]], SieveMethod[S, T]]: ...


def sieve[S, T: Particle](
    first: SieveMethod[S, T] | MaybeSequence[ConnectionField] | None = None,
    /,
    direction: MaybeSequence[MessageDirectionInput] | None = "receive",
    *,
    name: Name | None = None,
    stored: bool = True,
    retries: NonNegativeInt | None = None,
    retry_delay: PositiveTimeDelta = timedelta(seconds=5),
    contains: MaybeSequence[MessageData] | None = None,
    prefix: MaybeSequence[MessageData] | None = None,
    suffix: MaybeSequence[MessageData] | None = None,
    buffer_size: int | str | None = None,
    buffer_drop: int | str | None = None,
) -> SieveMethod[S, T] | Callable[[SieveMethod[S, T]], SieveMethod[S, T]]:
    """Mark a method as a sieve, parsing incoming messages into particles.

    A sieve method takes either a single `Message` (returning an optional particle), an async
    iterable of messages (yielding particles), or a `Buffer` (yielding particles).

    Args:
        first: When used as `@sieve` without arguments, this is the decorated method itself.
            When used as `@sieve(connection)`, this is a connection or sequence of connections
            to bind the sieve to.
        direction: Message direction(s) to accept. Defaults to receive-only.
        name: Optional override for the sieve name, defaults to the method name.
        stored: Whether produced particles should be persisted to the database.
        retries: Maximum retries for failed messages, or `None` for unlimited.
        retry_delay: Delay between retries.
        contains: Filter accepting only messages whose data contains the given bytes.
        prefix: Filter accepting only messages whose data starts with the given bytes.
        suffix: Filter accepting only messages whose data ends with the given bytes.
        buffer_size: Optional cap on the in-memory buffer this sieve receives.
        buffer_drop: Optional threshold at which oldest data is dropped from the buffer.

    Returns:
        Either the decorated method (when used without arguments) or a decorator returning the
        decorated method.
    """
    # The first positional may be either the decorated method or the bound connection(s),
    # disambiguate before we build the binding.
    if first is None:
        method = None
        connections = None
    elif inspect.isfunction(first) or inspect.ismethod(first):
        method = first
        connections = None
    else:
        method = None
        connections = tuple(cast("Sequence[ConnectionField]", seq(first)))

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
                method=get_function_name(method),
                stored=stored,
                retries=retries,
                retry_delay=retry_delay,
                filter=filter,
                connections=connections,
                buffer_size=cast("ByteSize | None", buffer_size),
                buffer_drop=cast("ByteSize | None", buffer_drop),
            ),
        )
        return method

    if method is None:
        return sieve

    return sieve(method)


def _add_binding(method: Callable[..., object], binding: _MethodBinding) -> None:
    method = get_inner_function(method)
    bindings: Sequence[_MethodBinding] | None = getattr(method, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    bindings = list(bindings)
    bindings.append(binding)
    setattr(method, _BINDINGS_ATTRIBUTE, tuple(bindings))


def _get_bound_name(function: Callable[..., Any]) -> str:
    return _get_normalized_name(get_function_name(function))


def _get_normalized_name(name: str) -> Name:
    return name.replace("_", "-").strip().strip("-")


warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


@final
class ComponentSystem(Node, ComponentSource):
    """Runtime wrapper around a `Component` that owns its lifecycle and infrastructure.

    Each `Component` is paired with exactly one `ComponentSystem`. The system provides:

    - Tree placement via the parent container and child registry.
    - Lifecycle: `start`, `stop`, `enable`, `disable`, plus the routine and procedure runners.
    - The event bus and reference resolution.
    - Lazy access to the connection, sieve, job, and pruner managers.

    Components reach their system via `Component.system`. The system is normally created by
    `Component.__post_init__`, callers rarely instantiate it directly.
    """

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
            # Components without explicit names get a stable random handle so they can still be
            # addressed in logs and references.
            __with_name__ = randstr(ascii_lowercase, 8)
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
        from ceres.connection import Connection

        for connection in self.get_connection_bindings().values():
            instance = getattr(self.component, connection.field, None)
            if isinstance(instance, Connection):
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
        for binding in self.get_sieve_bindings().values():
            connection_names = [
                field.name for field in seq(binding.connections or ()) if field.name is not None
            ]

            filter = binding.filter
            if connection_names:
                if filter is not None:
                    filter = filter.model_copy(update={"connection": connection_names})
                else:
                    filter = MessageFilter(connection=connection_names)

            sieves[binding.name] = MethodSieveConfig(
                name=binding.name,
                method=binding.method,
                stored=binding.stored,
                retries=binding.retries,
                retry_delay=binding.retry_delay,
                filter=filter,
                connections=connection_names,
                buffer_size=binding.buffer_size,
                buffer_drop=binding.buffer_drop,
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
        return f"{type(self).__name__}({reprify(self.component)})"

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
        """The current address of the component, derived by walking up to the root."""
        if self.parent is not None:
            return self.parent.address / self.name

        return Address.ROOT

    @property
    def container(self) -> ComponentSystem | Engine | None:
        """The container of the component system.

        This is either another `ComponentSystem` (the parent component) or an `Engine` (when
        this component is the engine's root). Returns `None` when the component is detached.
        """
        return self._container

    @container.setter
    def container(self, container: ComponentSystem | Engine | None) -> None:
        from ceres.engine import Engine

        self._container = container
        # Make sure the container actually knows about us, calling `attach` is idempotent when
        # the relationship is already in sync.
        if isinstance(container, Engine):
            if container.root is not self:
                container.attach(self)
        elif isinstance(container, ComponentSystem):
            if container._children.get(self._name) is not self:
                container.attach(self)

    @property
    @override
    def engine(self) -> Engine | None:
        """The engine that contains this component, or `None` if it is detached.

        Walks the container chain upwards and returns the engine at the top.
        """
        container = self._container
        if container is None:
            return None

        return container.engine

    @property
    @override
    def database(self) -> Database:
        """The database used by the component.

        If the component is part of a tree, this returns the database from the engine at the
        root. A detached component creates a private in-memory database lazily on first access,
        useful for unit tests.
        """
        container = self._container
        if container is not None:
            return container.database

        if self._database is None:
            self._database = Database()
        return self._database

    @property
    @override
    def config(self) -> ComponentConfig | None:
        """The configuration of the component, if available."""
        return self._config

    @config.setter
    def config(self, config: ComponentConfig | None) -> None:
        """Record the configuration that produced this component.

        This does not re-apply the configuration to the live component, it only records which
        configuration is currently considered active. Generally for internal use by the engine
        during a configuration apply.
        """
        self._config = config

    @property
    @override
    def root(self) -> ComponentSystem:
        """The root of this component's tree, or this component itself when it has no parent."""
        current: ComponentSystem | None = self
        while current.parent is not None:
            current = current.parent

        return current

    @property
    def parent(self) -> ComponentSystem | None:
        """The parent component's system, or `None` if there is no parent."""
        return as_component_system(self._container)

    @property
    def tags(self) -> list[str]:
        """Tags declared on this component's config, empty if none."""
        if self._config is None:
            return []
        return self._config.tags

    @property
    def access(self) -> ComponentAccessLevel | None:
        """Default access level from this component's config, or None if not set."""
        if self._config is None:
            return None
        return self._config.access

    def get_resolved_access(self) -> ComponentAccessLevel:
        """Walk the ancestor chain to find the nearest declared access level.

        Return the first non-None `access` found walking from this component up to root.
        If no ancestor declares an access level, return `ComponentAccessLevel.VIEW`.
        """
        current: ComponentSystem | None = self

        while current is not None:
            if current.access is not None:
                return current.access

            current = current.parent

        return ComponentAccessLevel.VIEW

    def get_inherited_tags(self) -> set[str]:
        """Collect tags from this component and all ancestors for permission resolution."""
        result: set[str] = set()
        current: ComponentSystem | None = self

        while current is not None:
            result.update(current.tags)
            current = current.parent

        return result

    @cached_property
    def jobs(self) -> JobManager:
        """Manager for scheduled jobs declared by this component."""
        return JobManager(self)

    @cached_property
    def connections(self) -> ComponentConnectionManager:
        """Manager for the component's network connections."""
        return ComponentConnectionManager(self)

    @cached_property
    def sieves(self) -> SieveManager:
        """Manager for the component's sieves."""
        return SieveManager(self)

    @cached_property
    def pruners(self) -> PrunerManager:
        """Manager for the component's data pruners."""
        return PrunerManager(self)

    @override
    async def __node_sync__(self, connection: AsyncConnection | None = None) -> None:
        await super().__node_sync__(connection)
        self._enabled = await self.__get_enabled_in_database()

    @property
    def name(self) -> Name:
        """The name this component is registered under within its parent."""
        return self._name

    @name.setter
    def name(self, name: Name) -> None:
        """Rename the component.

        Args:
            name: New name for the component.

        Raises:
            ValueError: If the parent already has a different child with the requested name.
        """
        if self.parent is None:
            self._name = name
            return

        if name == self._name:
            return

        if name in self.parent._children:
            raise ValueError(f"parent already has child named {name!r}")

        # Move the parent's registration over to the new name, otherwise the old key would
        # linger and the component would appear under both names.
        old_name = self._name
        self._name = name
        self.parent._children.pop(old_name, None)
        self.parent._children[name] = self
        self.__propagate_tree_change()

    @property
    def component(self) -> Component:
        """The underlying component this system wraps."""
        return self._component

    @property
    def enabled(self) -> bool:
        """`True` if the component is enabled.

        Enabled components start automatically when their parent or containing engine starts.
        """
        return self._enabled

    async def enable(self) -> None:
        """Enable the component and persist the new state.

        Enabled components start automatically when their parent or containing engine starts.
        Emits `EnabledEvent` on success.
        """
        await self.__set_enabled_in_database(True)
        self._enabled = True
        self.events.emit(EnabledEvent)

    async def disable(self) -> None:
        """Disable the component and persist the new state.

        Disabled components do not start automatically when their parent or containing engine
        starts. Emits `DisabledEvent` on success.
        """
        await self.__set_enabled_in_database(False)
        self._enabled = False
        self.events.emit(DisabledEvent)

    async def up(self) -> None:
        """Enable and start the component."""
        await self.enable()
        self.start()

    async def down(self) -> None:
        """Disable and stop the component, waiting for it to fully stop."""
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
        """All child component systems of this component, in registered order."""
        return list(self._children.values())

    def get_listener_bindings(self) -> Sequence[ListenerBinding]:
        """Return every listener binding on the underlying component class."""
        return get_listener_bindings(type(self.component))

    def get_routine_bindings(self) -> Sequence[RoutineBinding]:
        """Return every routine binding on the underlying component class."""
        return get_routine_bindings(type(self.component))

    def get_query_bindings(self) -> Mapping[Name, QueryBinding]:
        """Return a mapping of query names to query bindings on the underlying class."""
        return get_query_bindings(type(self.component))

    def get_action_bindings(self) -> Mapping[Name, ActionBinding]:
        """Return a mapping of action names to action bindings on the underlying class."""
        return get_action_bindings(type(self.component))

    def get_procedure_bindings(self) -> Mapping[Name, ProcedureBinding]:
        """Return a mapping of procedure names to bindings (queries plus actions)."""
        return get_procedure_bindings(type(self.component))

    def get_sieve_bindings(self) -> Mapping[Name, SieveBinding]:
        """Return a mapping of sieve names to sieve bindings on the underlying class."""
        return get_sieve_bindings(type(self.component))

    def get_connection_bindings(self) -> Mapping[Name, ConnectionBinding]:
        """Return a mapping of connection names to connection bindings on the underlying class."""
        return get_connection_bindings(type(self.component))

    def __propagate_tree_change(self) -> None:
        # Notify every component in the tree that the structure changed so they can recompute
        # cached child order and re-resolve references that may now point somewhere different.
        for component in self.root.get_components():
            component.system.__on_tree_change()

    def __on_tree_change(self) -> None:
        self.sync_child_order()
        self.sync_references()

    def sync_references(self) -> tuple[list[Reference], list[Reference]]:
        """Resolve every `Reference` declared by the component against the current tree.

        Each reference's root is set to this component, then resolution is attempted. Components
        whose references resolve are added to the target's referencer set so the target knows
        who depends on it. Stale referencers (where this system no longer references them) are
        removed.

        Returns:
            A `(resolved, unresolved)` tuple of references that did and did not resolve.
        """
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

        # Drop bookkeeping entries for referencers that no longer point at this component.
        discard: list[ComponentSystem] = []
        for referencer in self._referencers:
            if self.component not in referencer.get_referenced_components():
                discard.append(referencer)

        self._referencers.difference_update(discard)
        return resolved, unresolved

    def get_references(self) -> list[Reference]:
        """Walk the component's state and collect every `Reference` instance found."""
        from ceres.reference import Reference

        references: list[Reference] = []

        def visit(obj: Any) -> bool:
            if isinstance(obj, Reference):
                references.append(obj)
                return False

            return True

        traverse(self.component, visit)
        return references

    def has_reference_to(self, component: Component) -> bool:
        """Return `True` if this component references `component` directly."""
        from ceres.reference import unref

        referenced = self.get_referenced_components()
        for other in referenced:
            if id(other) == id(unref(component)):
                return True

        return False

    def get_referenced_components(self, reference: str | None = None) -> list[Component]:
        """Return components reached by walking this component's references.

        Args:
            reference: Optional dotted attribute path to start the walk from. When given, only
                the subtree rooted at that attribute is traversed.

        Returns:
            All other components that this component (or the requested subtree) references.
            Self-references are excluded.
        """
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
            if lenient_isinstance(obj, (Component, Reference)):
                obj = unref(obj)
                if obj is not self and obj is not self.component:
                    components.append(obj)
                    return False

            return True

        traverse(root, visit)
        return components

    def get_referencing_components(self, recursive: bool = False) -> list[Component]:
        """Return components that hold a reference to this component.

        Args:
            recursive: When `True`, also include components that reference this component
                indirectly through a chain of other referencers.

        Returns:
            The list of referencing components.
        """
        if recursive:
            return self.__get_referencing_components_recursive()

        return as_components(self._referencers)

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
        """Add a child component beneath this component.

        Args:
            child: Component or component system to attach.
            name: Optional name to register the child under. When omitted, the child's existing
                name is used.

        Raises:
            ValueError: If the child is this component itself, an ancestor, or there is already
                another child registered under the same name.
        """
        if isinstance(child, Component):
            child = child.system

        if child is self or self.contains(child):
            raise ValueError("component cannot contain itself")

        # Detach the child from its previous container before re-parenting so we don't leave
        # dangling references behind.
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
        """Remove the component from its container.

        The container can be either a parent component or the engine. If the component has no
        container, this does nothing. Emits `WillDetachEvent` before the removal and
        `DetachedEvent` afterward (propagated through the former container so listeners can see
        what was detached and from where).
        """
        if self._container is None:
            return

        engine = as_engine(self._container)
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
        """Resolve `address` to a component beneath this one.

        Args:
            address: Address string or `DynamicAddress`. An empty value returns this component.
                Absolute addresses on a non-root system are resolved against the tree root.

        Returns:
            The matching component, or `None` if no component exists at that address.
        """
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
        """Walk this component's subtree and return components matching the given filter.

        Args:
            filter: A `ComponentFilter` or `AddressSelector`, or `None` to skip positional
                filtering.
            inclusive: When `True`, include this component itself in the candidate set.
            **kwargs: Additional filter overrides.

        Returns:
            All matching components in pre-order traversal.
        """
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
        """Return the component's status augmented with its enabled flag and connectivity."""
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
        """Return `True` if `component` is somewhere in this subtree.

        Args:
            component: Component or system to test.
            inclusive: When `True`, return `True` for the component itself in addition to its
                descendants.
        """
        system = as_component_system(component)
        current: ComponentSystem | None = system if inclusive else system.parent
        while current is not None:
            if current is system:
                return True

            current = current.parent

        return False

    def get_ancestor_components(self, *, inclusive: bool = False) -> list[Component]:
        """Return a list of ancestor components in ascending order.

        Args:
            inclusive: When `True`, include this component itself as the first entry.

        Returns:
            Ancestors ordered from nearest parent to root.
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
        """Start the component, its ancestors, and any enabled descendants.

        Ancestors are started first so this component always has a running parent. After this
        component starts, every enabled child is started recursively unless `all_enabled` is
        `False`.

        Args:
            on_completed: Optional callback invoked when the component task finishes
                successfully.
            on_exception: Optional callback invoked when the component task fails.
            all_enabled: When `True`, recursively start every enabled descendant. Internal
                callers set this to `False` when starting an ancestor to avoid double-starts.
        """
        # Walk up first so parents are running before we start, ancestors are passed
        # `all_enabled=False` because we don't want them to fan out and start unrelated children.
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
            try:
                # Run the user's `__start__` hook. Failures here are reported but don't prevent
                # the `__stop__` hook from running on shutdown.
                await awaitify(self.component.__start__())
            except Exception as exception:
                self.events.emit(StartExceptionEvent, exception=trace(exception))
            else:
                try:
                    for component in reversed(self.get_ancestor_components()):
                        component.system.start(all_enabled=False)

                    await self.__node_sync__()

                    # Run all background workers concurrently. The first to fail will cancel the
                    # rest via `concurrently`.
                    await concurrently(
                        super().__run__(),
                        self.__run_routines(),
                        self.jobs.__run__(),
                        self.connections.__run__(),
                        self.sieves.__run__(),
                        self.pruners.__run__(),
                    )
                except Exception:
                    self.log.error(
                        f"An error occurred during component system execution. {traceback.format_exc()}",
                    )
                    raise
        finally:
            try:
                await awaitify(self.component.__stop__())
            except Exception as exception:
                self.events.emit(StopExceptionEvent, exception=trace(exception))

    async def __run_routine(self, binding: RoutineBinding) -> None:
        # Look up the bound method by name. A subclass may legitimately remove a routine, in
        # which case there's nothing to run.
        routine = getattr(self.component, binding.method, None)
        if routine is None:
            return

        self.events.emit(RoutineStartedEvent, routine=binding.method)

        try:
            while True:
                try:
                    await routine()
                    self.events.emit(RoutineCompletedEvent, routine=binding.method)
                    # `ON_COMPLETED` means "stop restarting once we successfully complete," so
                    # exit the loop here.
                    if binding.restart == RoutineRestartPolicy.ON_COMPLETED:
                        break
                except Exception as exception:
                    self.events.emit(
                        RoutineExceptionEvent,
                        routine=binding.method,
                        exception=trace(exception),
                    )
                    # `ON_EXCEPTION` means "stop restarting once we hit an exception," so exit
                    # the loop here.
                    if binding.restart == RoutineRestartPolicy.ON_EXCEPTION:
                        break

                if binding.restart == RoutineRestartPolicy.NEVER:
                    break

                self.events.emit(
                    RoutineRestartingEvent,
                    routine=binding.method,
                    delay=binding.restart_delay,
                )
                await sleep(binding.restart_delay)
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
        # Stop every running child concurrently. Loop until none remain because a child stop may
        # spawn or restart sibling state during shutdown.
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
            (binding := self.get_procedure_bindings().get(procedure)) is None
            or (method := getattr(self.component, binding.method, None)) is None
            or not inspect.ismethod(method)
        ):
            raise ProcedureNotFoundError()

        validated = create_validated_function(method)

        try:
            self.events.emit(ProcedureCalledEvent, procedure=procedure)
            return await awaitify(validated(**arguments))
        except CancelledError:
            self.events.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except ValidationError as error:
            if method.__name__ in error.title:
                raise ProcedureInvalidArgumentsError(
                    problems=ValidationProblem.extract(error, arguments)
                )

            raise
        except Exception as exception:
            info = trace(exception)
            self.events.emit(
                ProcedureExceptionEvent,
                procedure=procedure,
                exception=info,
            )
            raise ProcedureInternalError(exception=info)

    async def call(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> object | None:
        """Invoke a procedure once and return its output.

        For live procedures, queries return the first yielded value while actions exhaust the
        async iterator and return the last one.

        Args:
            procedure: Name of the procedure to invoke.
            arguments: Mapping of argument names to values, or `None` for no arguments.

        Returns:
            The procedure's output. `BaseOutput` instances are returned as-is, plain values are
            returned as the procedure produced them.

        Raises:
            ProcedureNotFoundError: If no procedure exists with the given name.
            ProcedureInvalidArgumentsError: If the procedure's arguments fail validation.
            ProcedureInternalError: If the procedure raises an exception during execution.
        """
        binding = self.get_procedure_bindings().get(procedure)
        if binding is None:
            raise ProcedureNotFoundError()

        output = await self.__invoke(procedure, arguments)

        if isinstance(output, BaseOutput):
            # File and streaming outputs are passed through verbatim, the server turns them
            # into responses.
            return output

        if not binding.live:
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)
            return output

        try:
            match binding:
                # A live query produces an iterable of values, return the first one and let the
                # generator be garbage collected.
                case QueryBinding():
                    async for current in output:
                        return current

                    return None
                # A live action is run to completion so all of its side effects happen, returning
                # the final value.
                case ActionBinding():
                    last: object | None = None
                    async for current in output:
                        last = current
                    return last
        except Exception as exception:
            info = trace(exception)
            self.events.emit(ProcedureExceptionEvent, procedure=procedure, exception=info)
            raise ProcedureInternalError(exception=info)
        finally:
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)

    async def subscribe(
        self,
        procedure: str,
        arguments: Mapping[Name, Any] | None = None,
    ) -> AsyncIterable[object | None]:
        """Subscribe to a procedure, yielding its output as it becomes available.

        For non-live queries, this polls the procedure on the binding's `poll` interval and
        yields each result. For live procedures, this yields each value the underlying async
        generator produces.

        Args:
            procedure: Name of the procedure to subscribe to.
            arguments: Mapping of argument names to values, or `None` for no arguments.

        Yields:
            Each successive output value from the procedure.

        Raises:
            ProcedureNotFoundError: If no procedure exists with the given name.
            ProcedureNotSubscribableError: If the procedure is a non-live action, which
                cannot be subscribed to.
            ProcedureInternalError: If the procedure raises an exception during execution.
        """
        binding = self.get_procedure_bindings().get(procedure)
        if binding is None:
            raise ProcedureNotFoundError()

        if not binding.live:
            if isinstance(binding, ActionBinding):
                raise ProcedureNotSubscribableError()

            try:
                while True:
                    yield await self.__invoke(procedure, arguments)
                    await sleep(binding.poll)
            except CancelledError:
                self.events.emit(ProcedureCancelledEvent, procedure=procedure)
                raise
            except Exception as exception:
                info = trace(exception)
                self.events.emit(ProcedureExceptionEvent, procedure=procedure, exception=info)
                raise ProcedureInternalError(exception=info)

        # Live procedures hand back an async iterable from the first invocation, just relay it.
        output = await self.__invoke(procedure, arguments)
        try:
            if output is not None:
                async for current in output:
                    yield current
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)
        except CancelledError:
            self.events.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except Exception as exception:
            info = trace(exception)
            self.events.emit(ProcedureExceptionEvent, procedure=procedure, exception=info)
            raise ProcedureInternalError(exception=info)

    def sync_child_order(self) -> None:
        """Reorder the child registry to match the order specified in the component's config.

        Children present in the configuration come first in declared order, any extra children
        not mentioned in the configuration are appended afterward in their existing order.
        """
        if self._config is None:
            return

        order: list[ComponentSystem] = []
        for config in self._config.components:
            component = self._children.get(config.name)
            if component is not None:
                order.append(component)

        # Include any children that aren't named in the configuration, appended after the
        # configured ones so configuration-driven ordering always wins.
        for component in self._children.values():
            if not any(current is component for current in order):
                order.append(component)

        self._children.clear()
        for component in order:
            self._children[component.name] = component


class Bound[T]:
    """Type-only marker used as `Bound[Connection]` to declare a field bound to a sibling object.

    Bound fields are how a component declares it expects an external object (currently only
    connections) to be supplied through the `BoundField` annotation. The actual descriptor behaviour
    is implemented by `BoundField`, this class only exists to give type checkers a handle.
    """

    if TYPE_CHECKING:

        @overload
        def __get__(self, instance: None, owner: type[T]) -> Self: ...
        @overload
        def __get__(self, instance: Any, owner: type[T]) -> Self | T: ...
        @overload
        def __get__(self, instance: Any, owner: type[T]) -> T: ...

        @overload
        def __get__(self, instance: None, owner: type[Any]) -> Self: ...
        @overload
        def __get__(self, instance: Any, owner: type[Any]) -> T: ...
        def __get__(self, instance: Any, owner: type[Any]) -> Self | T: ...

        def __set__(self, instance: Any, value: T) -> None: ...


@classmethod
def _bound__class_getitem__(cls: type[Bound], args: Any | tuple[Any]) -> Any:
    if not isinstance(args, tuple):
        args = (args,)

    return Annotated[args[0], BoundField.Marker(), *args[1:]]


_bound__class_getitem__.__name__ = "__class_getitem__"
Bound.__class_getitem__ = _bound__class_getitem__  # type: ignore


class BoundFieldArgs(TypedDict, total=False):
    """Keyword arguments accepted by `BoundField`, mirroring `pydantic.fields.FieldInfo`."""

    name: Name
    """Name to register the bound object under, defaults to the field name."""

    defaults: Mapping[str, Any] | None
    """Default values applied when constructing the bound object."""

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
    """Pydantic field used to declare a bound dependency, like a `ConnectionField`.

    The field tags itself with a `Marker` so `get_connection_bindings` can find the field and
    treat it as a connection slot rather than as plain configuration.
    """

    __slots__ = "marker"

    @dataclass(slots=True)
    class Marker:
        """Metadata appended to a bound field's annotations to identify it during inspection."""

        name: str | None = None

    def __init__(
        self,
        default: Any = Undefined,
        **kwargs: Unpack[BoundFieldArgs],
    ) -> None:
        name = kwargs.pop("name", None)
        defaults = kwargs.pop("defaults", None)

        # Accept the bound name from `defaults` as a convenience, this lets a config bundle the
        # name alongside other defaults without repeating it in `name=`.
        if name is None and defaults is not None and "name" in defaults:
            name = defaults["name"]

        super().__init__(default=default, **kwargs)

        self.marker = self.Marker(name=name)
        self.metadata.append(self.marker)

        if defaults:
            self.metadata.append(WithDefaults(**defaults))

    def __set_name__(self, owner: type[Any], name: str) -> None:
        if self.marker.name is None:
            self.marker.name = name

    @property
    def name(self) -> str | None:
        """Name the bound object is registered under, or `None` if not yet set."""
        return self.marker.name
