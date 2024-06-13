from __future__ import annotations

import asyncio
import inspect
import traceback
import warnings
from asyncio import CancelledError
from dataclasses import InitVar, field
from datetime import timedelta
from functools import cached_property
from inspect import Parameter
from string import ascii_lowercase
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Final,
    Iterable,
    Literal,
    Mapping,
    Protocol,
    Self,
    Sequence,
    Unpack,
    dataclass_transform,
    final,
    get_args,
    get_type_hints,
    overload,
    override,
    runtime_checkable,
)

from pydantic import Field, PositiveFloat, ValidationError
from pydantic.fields import FieldInfo

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.lazy import lazy_imports
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.config import ComponentConfig
from ceres.connectivity import Connectivity
from ceres.data import (
    ImmutableDataObject,
    Name,
    PositiveTimeDelta,
    StrEnum,
    ValidatedDataclass,
)
from ceres.database.enums import DatabaseType
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
from ceres.filter import BaseFilter, BaseFilterArgs
from ceres.node import Node
from ceres.status import Status

with lazy_imports(__name__):
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql import select

    from ceres._internal import util
    from ceres._internal.util import OrderedWeakSet, Undefined, WeakRef
    from ceres.database.database import Database
    from ceres.manager.job import JobManager
    from ceres.reference import Reference, unref

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = object


warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


class ComponentFilterArgs(BaseFilterArgs, total=False):
    root: Annotated[Address, CLIOption(str | None)]
    address: Annotated[AddressSelector | None, CLIOption(str | None)]
    enabled: bool | None
    running: bool | None


class ComponentFilter(BaseFilter):
    root: Annotated[Address, CLIOption(str | None)] = Address.ROOT
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = None
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


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class Component(ValidatedDataclass):
    __with_name__: InitVar[Name | None] = field(default=None)
    __with_config__: InitVar[ComponentConfig | None] = field(default=None)

    def __post_init__(
        self,
        __with_name__: Name | None = None,
        __with_config__: ComponentConfig | None = None,
    ) -> None:
        self.__system = ComponentSystem(
            self,
            __with_name__=__with_name__,
            __with_config__=__with_config__,
        )
        self.__setup__()

    def __setup__(self) -> None:
        pass

    def __connectivity__(self) -> Connectivity | None:
        return None

    @final
    def __bind__(self, bind: ComponentSystem, /) -> None:
        self.__system = bind

    @final
    def __unref__(self) -> Self:
        return self

    @final
    @property
    def system(self) -> ComponentSystem:
        return self.__system


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
    return get_component_procedure_bindings(cls).get(name)


class ListenerBinding(ImmutableDataObject):
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
    reference = util.strlist(reference)

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


class ProcedureArgumentsInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]
    required: bool


class ProcedureOutputInfo(ImmutableDataObject):
    json_schema: Mapping[str, Any]


class __BaseProcedureBinding(ImmutableDataObject):
    name: Name
    type: ProcedureType
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


@overload
def query[
    **P, T: Awaitable[Any] | AsyncIterable[Any]
](method: Callable[P, T]) -> Callable[P, T]: ...


@overload
def query[
    **P, T: Awaitable[Any] | AsyncIterable[Any]
](*, poll: float | timedelta = ...) -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def query[
    **P, T: Awaitable[Any] | AsyncIterable[Any]
](
    method: Callable[P, T] | None = None,
    *,
    poll: float | timedelta = timedelta(seconds=5),
) -> (
    Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]
):
    def query(method: Callable[P, T]) -> Callable[P, T]:
        info = __get_procedure_method_info(method, ProcedureType.QUERY)
        _bind(
            method,
            QueryBinding(
                name=_get_bound_name(method),
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
def action[
    **P, T: Awaitable[Any] | AsyncIterable[Any]
](method: Callable[P, T]) -> Callable[P, T]: ...


@overload
def action[
    **P, T: Awaitable[Any] | AsyncIterable[Any]
]() -> Callable[[Callable[P, T]], Callable[P, T]]: ...


def action[
    **P, T: Awaitable[Any] | AsyncIterable[Any]
](method: Callable[P, T] | None = None) -> (
    Callable[P, T] | Callable[[Callable[P, T]], Callable[P, T]]
):
    def action(method: Callable[P, T]) -> Callable[P, T]:
        validated = __get_procedure_method_info(method, ProcedureType.ACTION)
        _bind(
            method,
            ActionBinding(
                name=_get_bound_name(method),
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

    try:
        output_json_schema = util.get_type_adapter(output_annotation).json_schema()
    except Exception as exception:
        raise ValueError(
            f"output type of {type_} {util.strify(method)} must be serializable as a JSON object: "
            f"{exception}"
        )

    return __ProcedureMethodInfo(
        name=_get_bound_name(method),
        method=util.get_function_name(method),
        arguments=ProcedureArgumentsInfo(
            json_schema=arguments_json_schema,
            required=arguments_required,
        ),
        output=ProcedureOutputInfo(
            json_schema=output_json_schema,
        ),
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


def get_component_method_bindings[
    T: Binding
](method: Callable[..., Any], binding_cls: type[T]) -> Sequence[T]:
    method = util.get_inner_function(method)
    output: list[T] = []

    if values := getattr(method, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_component_method_binding[
    T: Binding
](method: Callable[..., Any], binding_cls: type[T]) -> T | None:
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
class ComponentSystem(Node):
    def __init__(
        self,
        component: Component,
        *,
        __with_config__: ComponentConfig | None = None,
        __with_name__: Name | None = None,
    ) -> None:
        super().__init__()

        if __with_name__ is None:
            __with_name__ = util.randstr(ascii_lowercase, 8)

        self._name = __with_name__
        self._config: Final[ComponentConfig | None] = __with_config__
        self._referencers: Final[OrderedWeakSet[ComponentSystem]] = OrderedWeakSet()
        self._children: Final[dict[Name, ComponentSystem]] = {}
        self._parent: WeakRef[ComponentSystem] | None = None
        self._enabled = False
        self._engine: Engine | None = None
        self._database: Database | None = None
        self._component: Final[Component] = component
        self._component.__bind__(self)

        if self._config is not None:
            for job in self._config.jobs:
                self.jobs.add(job)

        self.sync_references()

    @override
    def __str__(self) -> str:
        return repr(self)

    @override
    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(name={self.name!r}, component={util.reprify(self.component)})"
        )

    @property
    @override
    def __container__(self) -> Node | None:
        if self.parent is not None:
            return self.parent

        return self.engine

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
    @override
    def engine(self) -> Engine | None:
        """
        Get the engine this component is part of. Returns `None` if the component is not part of any
        engine.
        """

        if self.parent is not None:
            return self.parent.engine
        if self._engine is not None:
            return self._engine

        return None

    @engine.setter
    def engine(self, engine: Engine) -> None:
        """
        Bind the component to a given engine.
        """
        self._engine = engine

    @property
    @override
    def database(self) -> Database:
        if self.parent is not None:
            return self.parent.database
        if self.engine is not None:
            return self.engine.database
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
        if self._parent is None:
            return None

        return self._parent()

    @cached_property
    def jobs(self) -> JobManager:
        return JobManager(self)

    @override
    async def __node_sync__(self, session: AsyncSession | None = None) -> None:
        async with await util.get_session(self.database, session) as session:
            await super().__node_sync__(session)
            self._enabled = await self.__get_enabled_in_database(session)

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
        starts.
        """
        return self._enabled

    async def enable(self) -> None:
        """
        Enable the component, and implicitly, all its ancestors. Enabled components start
        automatically when their parent starts.
        """
        if self.parent is not None:
            await self.parent.enable()

        async with await self.database.init() as session:
            await self.__set_enabled_in_database(session, True)
        self._enabled = True
        self.events.emit(EnabledEvent)

    async def disable(self) -> None:
        """
        Disable the component.
        """
        async with await self.database.init() as session:
            await self.__set_enabled_in_database(session, False)
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

    async def __get_enabled_in_database(self, session: AsyncSession) -> bool:
        from ceres.store import StoreRow

        enabled = await session.scalar(
            select(StoreRow.enabled).where(StoreRow.address == self.address)
        )

        if enabled is None:
            return False

        return enabled

    async def __set_enabled_in_database(self, session: AsyncSession, enabled: bool) -> None:
        from ceres.store import StoreRow

        match self.database.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert
            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        await self.__node_sync__(session)
        await session.execute(
            insert(StoreRow)
            .values(
                StoreRow(
                    address=self.address,
                    enabled=enabled,
                ).values()
            )
            .on_conflict_do_update(
                index_elements=[StoreRow.address],
                set_={"enabled": enabled},
            )
        )

        await session.commit()

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
        self.__sync_child_order()
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
        child._parent = WeakRef(self)

        self.__propagate_tree_change()
        child.events.emit(AttachedEvent)

    def detach(self) -> None:
        """
        Remove the component from its parent's children. If the component has no parent, this does
        nothing.
        """
        parent = self.parent
        if parent is None:
            return

        current = parent._children.get(self.name)

        try:
            if current is not None and current is self:
                self.events.emit(WillDetachEvent)

                address_before = self.address
                parent._children.pop(self.name, None)
                self._parent = None

                self.__propagate_tree_change()
                parent.__propagate_tree_change()

                parent.events.propagate(
                    DetachedEvent(address=address_before),
                    logging=self.get_resolved_logging_config(),
                )
                self.events.emit(DetachedEvent)
        finally:
            self._parent = None

    @override
    def get_component(
        self,
        address: str | DynamicAddress | None = None,
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
                    child.start()

    @override
    async def __run__(self) -> None:
        try:
            for component in reversed(self.get_ancestor_components()):
                component.system.start(all_enabled=False)

            await self.__node_sync__()

            await asyncio.gather(
                super().__run__(),
                self.__process_routines(),
                self.jobs.process(),
            )
        except Exception:
            self.log.error("An error occurred during component system execution.", exc_info=True)
            traceback.print_exc()
            raise

    async def __process_routine(self, binding: RoutineBinding) -> None:
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

    async def __process_routines(self) -> None:
        await asyncio.gather(
            *[self.__process_routine(binding) for binding in self.get_routine_bindings()]
        )

    @override
    async def __stop__(self) -> None:
        self.events.emit(StoppingEvent)
        for system in reversed(self.children):
            await system.stop()

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

        result = await self.__invoke(procedure, arguments)

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

    def __sync_child_order(self) -> None:
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
