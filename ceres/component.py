from __future__ import annotations

import asyncio
import inspect
import traceback
import warnings
from asyncio import CancelledError, TaskGroup
from dataclasses import InitVar, field
from datetime import timedelta
from functools import cached_property
from inspect import Parameter
from string import ascii_lowercase
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Coroutine,
    Final,
    Iterable,
    Literal,
    Mapping,
    Protocol,
    Self,
    Sequence,
    TypeAlias,
    Unpack,
    final,
    get_args,
    get_type_hints,
    overload,
    override,
    runtime_checkable,
)

from pydantic import ConfigDict, PositiveFloat, ValidationError

from ceres._internal import util
from ceres._internal.filter import BaseFilter, BaseFilterArgs
from ceres._internal.lazy import lazy_imports
from ceres._internal.protocols import ComponentSource
from ceres._internal.util import BytesLike, OrderedWeakSet, Undefined
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.config import ComponentConfig, JobConfig, PrunerConfig, SieveConfig
from ceres.data import (
    ImmutableDataObject,
    Name,
    NonEmptyStr,
    OrderedStrEnum,
    PositiveTimeDelta,
    StrEnum,
    ValidatedDataclass,
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
from ceres.node import Node
from ceres.stream import WriteStream
from ceres.variable import InternalVariableName, Variable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from ceres.connectivity import Connectivity
    from ceres.engine import Engine
    from ceres.status import Status

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.job import ComponentJobManager
    from ceres.pruner import ComponentPrunerManager
    from ceres.reference import Reference, unref
    from ceres.sieve import ComponentSieveManager


warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


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
    _Container: TypeAlias = "Component | ComponentSystem | Engine | None"
else:
    _Container = object


class Component(ValidatedDataclass, ComponentSource):
    __with_name__: InitVar[Name | None] = field(default=None, kw_only=False)
    __with_config__: InitVar[ComponentConfig | None] = field(default=None)
    __with_container__: InitVar[_Container] = field(default=None)

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

    def __static_jobs__(self) -> Iterable[JobConfig]:
        return ()

    def __static_pruners__(self) -> Iterable[PrunerConfig]:
        return ()

    def __static_sieves__(self) -> Iterable[SieveConfig]:
        return ()

    @final
    def __bind__(self, bind: ComponentSystem, /) -> None:
        self.__system = bind

    @final
    def __unref__(self) -> Self:
        return self


@util.cached
def get_component_listener_bindings(cls: type[Component]) -> Sequence[ListenerBinding]:
    """
    Get all listener bindings for this component class.
    """
    return get_component_bindings(cls, ListenerBinding)


@util.cached
def get_component_routine_bindings(cls: type[Component]) -> Sequence[RoutineBinding]:
    """
    Get all routine bindings for this component class.
    """
    return get_component_bindings(cls, RoutineBinding)


@util.cached
def get_component_query_bindings(cls: type[Component]) -> Mapping[str, QueryBinding]:
    """
    Get all query bindings for this component class. Returns a mapping of query names to query
    bindings.
    """
    return {
        name: binding
        for name, binding in get_component_procedure_bindings(cls).items()
        if isinstance(binding, QueryBinding)
    }


def get_component_query_binding(cls: type[Component], name: str) -> QueryBinding | None:
    """
    Get a query binding for this component class by name. Returns `None` if the query binding
    does not exist.
    """
    procedure = get_component_procedure_binding(cls, name)
    if not isinstance(procedure, QueryBinding):
        return None

    return procedure


@util.cached
def get_component_action_bindings(cls: type[Component]) -> Mapping[str, ActionBinding]:
    """
    Get all action bindings for this component class. Returns a mapping of action names to
    action bindings.
    """
    return {
        name: binding
        for name, binding in get_component_procedure_bindings(cls).items()
        if isinstance(binding, ActionBinding)
    }


def get_component_action_binding(cls: type[Component], name: str) -> ActionBinding | None:
    """
    Get an action binding for this component class by name. Returns `None` if the action binding
    does not exist.
    """
    procedure = get_component_procedure_binding(cls, name)
    if not isinstance(procedure, ActionBinding):
        return None

    return procedure


@util.cached
def get_component_procedure_bindings(cls: type[Component]) -> Mapping[Name, ProcedureBinding]:
    """
    Get all procedure bindings (actions and queries) for this component class. Returns a mapping
    of procedure names to procedure bindings.
    """
    queries = get_component_bindings(cls, QueryBinding)
    actions = get_component_bindings(cls, ActionBinding)
    procedures = sorted([*queries, *actions], key=lambda current: current.name)

    return MappingProxyType({binding.name: binding for binding in procedures})


def get_component_procedure_binding(cls: type[Component], name: str) -> ProcedureBinding | None:
    """
    Get a procedure binding (action or query) for this component class by name. Returns `None`
    if the procedure does not exist.
    """
    name = _get_normalized_name(name)
    return get_component_procedure_bindings(cls).get(name)


class ListenerBinding(ImmutableDataObject):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: Name
    method: Name
    event: type | UnionType
    local: bool
    reference: Sequence[str]
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

        _bind(
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


class ProcedureSchemas(ImmutableDataObject):
    arguments: Mapping[str, Any] | None
    output: Mapping[str, Any]


class ProcedureOutputType(StrEnum):
    VALUE = "value"
    MEDIA = "media"


class ProcedureArgumentsInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]
    required: bool


class ProcedureValueOutputInfo(ImmutableDataObject):
    type: Literal[ProcedureOutputType.VALUE] = ProcedureOutputType.VALUE
    json_schema: Mapping[str, Any]


class ProcedureMediaOutputInfo(ImmutableDataObject):
    type: Literal[ProcedureOutputType.MEDIA] = ProcedureOutputType.MEDIA
    media: str


ProcedureOutputInfo: TypeAlias = ProcedureValueOutputInfo | ProcedureMediaOutputInfo


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


class __BaseProcedureBinding(ImmutableDataObject):
    type: ProcedureType
    name: Name
    permissions: ProcedurePermissions
    method: str
    live: bool
    arguments: ProcedureArgumentsInfo | None
    output: ProcedureOutputInfo


class QueryBinding(__BaseProcedureBinding):
    type: Literal[ProcedureType.QUERY] = ProcedureType.QUERY
    poll: PositiveTimeDelta = timedelta(seconds=1)


class ActionBinding(__BaseProcedureBinding):
    type: Literal[ProcedureType.ACTION] = ProcedureType.ACTION


ProcedureBinding = QueryBinding | ActionBinding

MediaWriter: TypeAlias = Callable[[WriteStream[BytesLike]], Coroutine[Any, Any, None]]


class Media(ValidatedDataclass, kw_only=False):
    type: NonEmptyStr
    writer: MediaWriter


@overload
def query[**P, T](method: Callable[P, T]) -> Callable[P, T]: ...


@overload
def query[**P, T: Media | Awaitable[Media]](
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
        info = __get_procedure_method_info(method, ProcedureType.QUERY, media)
        _bind(
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
        validated = __get_procedure_method_info(method, ProcedureType.ACTION, media)
        _bind(
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


class __ProcedureMethodInfo(ImmutableDataObject):
    name: str
    method: str
    arguments: ProcedureArgumentsInfo | None
    output: ProcedureOutputInfo
    live: bool


def __get_procedure_method_info(
    method: Callable[..., Any],
    type_: ProcedureType,
    media: str | None,
    /,
) -> __ProcedureMethodInfo:
    method = util.get_inner_function(method)
    signature = inspect.signature(method)

    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{type_} {util.strify(method)} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{type_} {util.strify(method)} cannot have positional-only arguments")

    arguments_json_schema = util.get_args_model(method).model_json_schema()
    arguments_required = len(arguments_json_schema.get("properties", {}).get("required", [])) > 0

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

    if isinstance(output_annotation, type) and issubclass(output_annotation, Media):
        if media is None:
            raise ValueError(f"`media` type must be specified for {type_} {util.strify(method)}")

        output = ProcedureMediaOutputInfo(media=media)
    else:
        if media is not None:
            raise ValueError(
                f"`media` type was specified for {type_} {util.strify(method)}, but return type is not `Media`"
            )

        try:
            output_json_schema = util.get_type_adapter(output_annotation).json_schema()
            output = ProcedureValueOutputInfo(json_schema=output_json_schema)
        except Exception as exception:
            raise ValueError(
                f"output type of {type_} {util.strify(method)} must be either `Download` or be serializable as JSON. Type is not serializable: "
                f"{exception}"
            )

    return __ProcedureMethodInfo(
        name=_get_bound_name(method),
        method=util.get_function_name(method),
        arguments=ProcedureArgumentsInfo(
            json_schema=arguments_json_schema,
            required=arguments_required,
        ),
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


class RoutineBinding(ImmutableDataObject):
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
        _bind(
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
class Binding(Protocol):
    method: str


def get_component_method_bindings[T: Binding](
    method: Callable[..., Any],
    binding_cls: type[T],
) -> Sequence[T]:
    method = util.get_inner_function(method)
    output: list[T] = []

    if values := getattr(method, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_component_method_binding[T: Binding](
    method: Callable[..., Any],
    binding_cls: type[T],
) -> T | None:
    bindings = get_component_method_bindings(method, binding_cls)
    if bindings:
        return bindings[0]

    return None


def get_component_bindings[T: Binding](cls: type[Component], binding_cls: type[T]) -> Sequence[T]:
    bindings: dict[str, T] = {}

    for cls in reversed(cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_component_method_bindings(member, binding_cls):
                bindings[binding.method] = binding

    return sorted(bindings.values(), key=lambda current: current.method)


def _bind(method: Callable[..., object], binding: Binding) -> None:
    method = util.get_inner_function(method)
    bindings: Sequence[Binding] | None = getattr(method, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(method, _BINDINGS_ATTRIBUTE, bindings)


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
        "__name",
        "__config",
        "__referencers",
        "_container",
        "__children",
        "__enabled",
        "__database",
        "__component",
    )

    def __init__(
        self,
        component: Component,
        *,
        __with_config__: ComponentConfig | None = None,
        __with_name__: Name | None = None,
        __with_container__: Component | ComponentSystem | Engine | None = None,
    ) -> None:
        super().__init__()

        if __with_name__ is None:
            __with_name__ = util.randstr(ascii_lowercase, 8)
        if isinstance(__with_container__, Component):
            __with_container__ = __with_container__.system

        self.__name = __with_name__
        self.__config: ComponentConfig | None = __with_config__
        self.__referencers: Final[OrderedWeakSet[ComponentSystem]] = OrderedWeakSet()
        self.__container: ComponentSystem | Engine | None = None
        self.__children: Final[dict[Name, ComponentSystem]] = {}
        self.__enabled = False
        self.__database: Database | None = None
        self.__component: Final[Component] = component
        self.__component.__bind__(self)

        if __with_container__ is not None:
            __with_container__.attach(self)
            assert self.__container is __with_container__

        self.sync_references()

        jobs = {job.name: job for job in self.component.__static_jobs__()}
        jobs.update({job.name: job for job in (self.config.jobs if self.config else ())})
        for job in jobs.values():
            self.jobs.add(job)

        pruners = {pruner.name: pruner for pruner in self.component.__static_pruners__()}
        pruners.update(
            {pruner.name: pruner for pruner in (self.config.pruners if self.config else ())}
        )
        for pruner in pruners.values():
            self.pruners.add(pruner)

        sieves = {sieve.name: sieve for sieve in self.component.__static_sieves__()}
        sieves.update({sieve.name: sieve for sieve in (self.config.sieves if self.config else ())})
        for sieve in sieves.values():
            self.sieves.add(sieve)

    @override
    def __str__(self) -> str:
        return repr(self)

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}(component={util.reprify(self.component)})"

    @property
    @override
    def __container__(self) -> Node | None:
        return self.__container

    @property
    @override
    def __node__(self) -> Node:
        return self

    @property
    @override
    def __component__(self) -> Component:
        return self.__component

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
        return self.__container

    @container.setter
    def container(self, container: ComponentSystem | Engine | None) -> None:
        from ceres.engine import Engine

        self.__container = container
        if isinstance(container, Engine):
            if container.root is not self:
                container.attach(self)
        elif isinstance(container, ComponentSystem):
            if container.__children.get(self.__name) is not self:
                container.attach(self)

    @property
    @override
    def engine(self) -> Engine | None:
        """
        Get the engine this component is contained by. Returns `None` if the component is not
        contained by any engine.
        """
        container = self.__container
        if container is None:
            return None

        return container.engine

    @property
    @override
    def database(self) -> Database:
        container = self.__container
        if container is not None:
            return container.database

        if self.__database is None:
            self.__database = Database()
        return self.__database

    @property
    @override
    def config(self) -> ComponentConfig | None:
        """
        The configuration of the component, if available.
        """
        return self.__config

    @config.setter
    def config(self, config: ComponentConfig | None) -> None:
        """
        Set the configuration of the component. Note this doesn't actually sync the component with
        the configuration. It will only indicate to the engine, that this configuration is the one
        currently applied. Generally, this is only for internal use and should not be used directly.
        """
        self.__config = config

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
        return util.as_component_system(self.__container)

    @cached_property
    def jobs(self) -> ComponentJobManager:
        return ComponentJobManager(self)

    @cached_property
    def pruners(self) -> ComponentPrunerManager:
        return ComponentPrunerManager(self)

    @cached_property
    def sieves(self) -> ComponentSieveManager:
        return ComponentSieveManager(self)

    @override
    async def __node_sync__(self, connection: AsyncConnection | None = None) -> None:
        await super().__node_sync__(connection)
        self.__enabled = await self.__get_enabled_in_database()

    @property
    def name(self) -> Name:
        return self.__name

    @name.setter
    def name(self, name: Name) -> None:
        if self.parent is None:
            self.__name = name
            return

        if name in self.parent.__children:
            raise ValueError(f"parent already has child named {self.__name!r}")

        self.__name = name
        self.parent.__children[name] = self
        self.__propagate_tree_change()

        self.__name = name

    @property
    def component(self) -> Component:
        """
        Get the underlying component of the component system.
        """
        return self.__component

    @property
    def enabled(self) -> bool:
        """
        `True` if the component is enabled. Enabled components start automatically when their parent
        or containing engine starts.
        """
        return self.__enabled

    async def enable(self) -> None:
        """
        Enable the component. Enabled components start automatically when their parent or containing
        engine starts.
        """
        await self.__set_enabled_in_database(True)
        self.__enabled = True
        self.events.emit(EnabledEvent)

    async def disable(self) -> None:
        """
        Disable the component. Disabled components will not start automatically when their parent
        or containing engine starts.
        """
        await self.__set_enabled_in_database(False)
        self.__enabled = False
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
        return list(self.__children.values())

    def get_listener_bindings(self) -> Sequence[ListenerBinding]:
        """
        Get all listener bindings for this component.
        """
        return get_component_listener_bindings(type(self.component))

    def get_routine_bindings(self) -> Sequence[RoutineBinding]:
        """
        Get all routine bindings for this component.
        """
        return get_component_routine_bindings(type(self.component))

    def get_query_bindings(self) -> Mapping[str, QueryBinding]:
        """
        Get all query bindings for this component. Returns a mapping of query names to query
        bindings.
        """
        return get_component_query_bindings(type(self.component))

    def get_query_binding(self, name: str) -> QueryBinding | None:
        """
        Get a query binding for this component by name. Returns `None` if the query binding does not
        exist.
        """
        return get_component_query_binding(type(self.component), name)

    def get_action_bindings(self) -> Mapping[str, ActionBinding]:
        """
        Get all action bindings for this component. Returns a mapping of action names to action
        bindings.
        """
        return get_component_action_bindings(type(self.component))

    def get_action_binding(self, name: str) -> ActionBinding | None:
        """
        Get an action binding for this component by name. Returns `None` if the action binding does
        not exist.
        """
        return get_component_action_binding(type(self.component), name)

    def get_procedure_bindings(self) -> Mapping[Name, ProcedureBinding]:
        """
        Get all procedure bindings (actions and queries) for this component. Returns a mapping of
        procedure names to procedure bindings.
        """
        return get_component_procedure_bindings(type(self.component))

    def get_procedure_binding(self, name: str) -> ProcedureBinding | None:
        """
        Get a procedure binding (action or query) for this component by name. Returns `None` if the
        procedure does not exist.
        """
        return get_component_procedure_binding(type(self.component), name)

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
                component.system.__referencers.add(self)
            else:
                unresolved.append(reference)

        discard: list[ComponentSystem] = []
        for referencer in self.__referencers:
            if self.component not in referencer.get_referenced_components():
                discard.append(referencer)

        self.__referencers.difference_update(discard)
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

        return util.as_components(self.__referencers)

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
        current = self.__children.get(name)
        if current is not None:
            raise ValueError(f"child with name '{name}' already exists")

        if child.name != name:
            child.name = name

        self.__children[child.name] = child
        child.__container = self

        self.__propagate_tree_change()
        child.events.emit(AttachedEvent)

    def detach(self) -> None:
        """
        Remove the component from its container (either its parent component, or its containing
        engine). If the component has no container, this does nothing.
        """
        if self.__container is None:
            return

        engine = util.as_engine(self.__container)
        if engine is not None:
            self.events.emit(WillDetachEvent)
            address_before = self.address
            logging_before = self.get_resolved_logging_config()

            self.__container = None
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

        current = parent.__children.get(self.name)

        try:
            if current is not None and current is self:
                self.events.emit(WillDetachEvent)

                address_before = self.address
                logging_before = self.get_resolved_logging_config()

                parent.__children.pop(self.name, None)
                self.__container = None

                self.__propagate_tree_change()
                parent.__propagate_tree_change()

                parent.events.propagate(
                    DetachedEvent(address=address_before),
                    logging=logging_before,
                )
                self.events.emit(DetachedEvent)
        finally:
            self.__container = None

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

            current = current.__children.get(name)

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

            for component in current.__children.values():
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

            await util.concurrently(
                super().__run__(),
                self.__run_routines(),
                self.jobs.__run__(),
                self.pruners.__run__(),
                self.sieves.__run__(),
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
            for system in reversed(self.children):
                if system.running:
                    await system.stop()

        await self.settle()

    @override
    async def __post_stop__(self) -> None:
        await super().__post_stop__()
        await self.flush()

        if self.__database is not None:
            await self.__database.dispose()
            self.__database = None

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

        result = await self.__invoke(procedure, arguments)

        if isinstance(result, Media):
            # If the result is a media object, just return it directly.
            return result

        if not binding.live:
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)
            return result

        try:
            match binding:
                # If the procedure is a live query, we just return the first output.
                case QueryBinding():
                    async for output in result:
                        return output

                    return None
                # If the procedure is a live action, iterate through all outputs and return the
                # last one.
                case ActionBinding():
                    last: object | None = None
                    async for output in result:
                        last = output
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

        result = await self.__invoke(procedure, arguments)

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
            if result is not None:
                async for output in result:
                    yield output
            self.events.emit(ProcedureCompletedEvent, procedure=procedure)
        except CancelledError:
            self.events.emit(ProcedureCancelledEvent, procedure=procedure)
            raise
        except Exception as exception:
            traceback = util.get_traceback(exception)
            self.events.emit(ProcedureExceptionEvent, procedure=procedure, traceback=traceback)
            raise Failure(ProcedureInternalError(traceback=list(traceback)))

    def sync_child_order(self) -> None:
        if self.__config is None:
            return

        order: list[ComponentSystem] = []
        for config in self.__config.components:
            component = self.__children.get(config.name)
            if component is not None:
                order.append(component)

        for component in self.__children.values():
            if not any(current is component for current in order):
                order.append(component)

        self.__children.clear()
        for component in order:
            self.__children[component.name] = component
