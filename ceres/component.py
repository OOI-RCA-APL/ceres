import inspect
import warnings
from datetime import timedelta
from inspect import Parameter
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    Literal,
    Mapping,
    ParamSpec,
    Protocol,
    Sequence,
    TypeVar,
    final,
    get_args,
    get_type_hints,
    runtime_checkable,
)

from pydantic import Field, PositiveFloat
from pydantic.fields import FieldInfo
from typing_extensions import Self, dataclass_transform, overload

from ceres.address import AddressSelector, DynamicAddress
from ceres.connectivity import Connectivity
from ceres.data import ImmutableDataObject, Name, PositiveTimeDelta, StrEnum, ValidatedDataclass
from ceres.events import Event
from ceres.internal.utilities import (
    Undefined,
    cached,
    decode_td,
    get_args_model,
    get_function_name,
    get_inner_function,
    get_return_annotation,
    get_type_adapter,
    strify,
    strlist,
    validated_function,
)

if TYPE_CHECKING:
    from ceres.system import System
else:
    System = object

_ComponentT = TypeVar("_ComponentT", bound="Component")

warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(Field, FieldInfo),
)
class Component(ValidatedDataclass):
    def __post_init__(self) -> None:
        self.__bind: "System | None" = None
        self.__setup__()

    def __setup__(self) -> None:
        pass

    @final
    def __bind__(self, bind: "System", /) -> None:
        self.__bind = bind

    def __connectivity__(self) -> Connectivity | None:
        return None

    @final
    @property
    def system(self) -> System:
        if self.__bind is None:
            self.__bind = System(self)

        return self.__bind

    def unref(self) -> Self:
        return self

    @final
    @classmethod
    def get_listener_bindings(cls) -> Sequence["ListenerBinding"]:
        """
        Get all listener bindings for this component class.
        """
        return _get_listener_bindings(cls)

    @final
    @classmethod
    def get_routine_bindings(cls) -> Sequence["RoutineBinding"]:
        """
        Get all routine bindings for this component class.
        """
        return _get_routine_bindings(cls)

    @final
    @classmethod
    def get_query_bindings(cls) -> Mapping[str, "QueryBinding"]:
        """
        Get all query bindings for this component class. Returns a mapping of query names to query
        bindings.
        """
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, QueryBinding)
        }

    @final
    @classmethod
    def get_query_binding(cls, name: Callable[..., Any] | str) -> "QueryBinding | None":
        """
        Get a query binding for this component class by name. Returns `None` if the query binding
        does not exist.
        """
        procedure = cls.get_procedure_binding(name)
        if not isinstance(procedure, QueryBinding):
            return None

        return procedure

    @final
    @classmethod
    def get_action_bindings(cls) -> Mapping[str, "ActionBinding"]:
        """
        Get all action bindings for this component class. Returns a mapping of action names to
        action bindings.
        """
        return {
            name: binding
            for name, binding in cls.get_procedure_bindings().items()
            if isinstance(binding, ActionBinding)
        }

    @final
    @classmethod
    def get_action_binding(cls, name: Callable[..., Any] | str) -> "ActionBinding | None":
        """
        Get an action binding for this component class by name. Returns `None` if the action binding
        does not exist.
        """
        procedure = cls.get_procedure_binding(name)
        if not isinstance(procedure, ActionBinding):
            return None

        return procedure

    @final
    @classmethod
    def get_procedure_bindings(cls) -> Mapping[str, "ProcedureBinding"]:
        """
        Get all procedure bindings (actions and queries) for this component class. Returns a mapping
        of procedure names to procedure bindings.
        """
        return _get_procedure_bindings(cls)

    @final
    @classmethod
    def get_procedure_binding(cls, name: Callable[..., Any] | str) -> "ProcedureBinding | None":
        """
        Get a procedure binding (action or query) for this component class by name. Returns `None`
        if the procedure does not exist.
        """
        if isinstance(name, str):
            return cls.get_procedure_bindings().get(name)

        return get_method_binding(name, ProcedureBinding)  # type: ignore


@cached
def _get_listener_bindings(cls: type[Component]) -> Sequence["ListenerBinding"]:
    return get_bindings(cls, ListenerBinding)


@cached
def _get_routine_bindings(cls: type[Component]) -> Sequence["RoutineBinding"]:
    return get_bindings(cls, RoutineBinding)


@cached
def _get_procedure_bindings(cls: type[_ComponentT]) -> Mapping[Name, "ProcedureBinding"]:
    queries = get_bindings(cls, QueryBinding)
    actions = get_bindings(cls, ActionBinding)
    procedures = sorted([*queries, *actions], key=lambda current: current.name)

    return MappingProxyType({binding.name: binding for binding in procedures})


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


@validated_function
def listener(
    method: _ListenerMethod | None = None,
    *,
    event: type | UnionType | None = None,
    local: bool | None = None,
    reference: str | Sequence[str] | None = None,
    address: str | AddressSelector | Sequence[str | AddressSelector] | None = None,
) -> _ListenerMethod | _ListenerMethodTransform:
    reference = strlist(reference)

    if address is not None:
        if isinstance(address, (str, DynamicAddress)):
            address = [address]

        address = AddressSelector("|".join(str(current) for current in address))

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


_P = ParamSpec("_P")
_T = TypeVar("_T", bound=Awaitable[Any] | AsyncIterable[Any])


@overload
def query(method: Callable[_P, _T]) -> Callable[_P, _T]: ...


@overload
def query(
    *,
    poll: float | timedelta = ...,
) -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...


@validated_function
def query(
    method: Callable[_P, _T] | None = None,
    *,
    poll: float | timedelta = timedelta(seconds=5),
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def query(method: Callable[_P, _T]) -> Callable[_P, _T]:
        info = __get_procedure_method_info(method, ProcedureType.QUERY)
        _bind(
            method,
            QueryBinding(
                name=_get_bound_name(method),
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
def action(method: Callable[_P, _T]) -> Callable[_P, _T]: ...


@overload
def action() -> Callable[[Callable[_P, _T]], Callable[_P, _T]]: ...


@validated_function
def action(
    method: Callable[_P, _T] | None = None,
) -> Callable[_P, _T] | Callable[[Callable[_P, _T]], Callable[_P, _T]]:
    def action(method: Callable[_P, _T]) -> Callable[_P, _T]:
        validated = __get_procedure_method_info(method, ProcedureType.ACTION)
        _bind(
            method,
            ActionBinding(
                name=_get_bound_name(method),
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
    method = get_inner_function(method)
    signature = inspect.signature(method)

    parameters = [*signature.parameters.values()]
    if not parameters or parameters[0].name != "self":
        raise ValueError(f"{type_} {strify(method)} must have 'self' as its first parameter")
    if any(parameter.kind == Parameter.POSITIONAL_ONLY for parameter in parameters[1:]):
        raise ValueError(f"{type_} {strify(method)} cannot have positional-only arguments")

    arguments_json_schema = get_args_model(method).model_json_schema()
    arguments_required = len(arguments_json_schema.get("properties", {}).get("required", [])) > 0

    output_annotation = get_return_annotation(method, Undefined)
    if output_annotation is Undefined:
        raise ValueError(f"return type of {type_} {strify(method)} must be specified")

    live = inspect.isasyncgenfunction(method)

    if live:
        error = ValueError(f"return type of live {type_} {strify(method)} must be AsyncIterable[T]")

        try:
            if output_annotation.__name__ != "AsyncIterable":
                raise error

            output_annotation = get_args(output_annotation)[0]
        except Exception:
            raise error

    try:
        output_json_schema = get_type_adapter(output_annotation).json_schema()
    except Exception as exception:
        raise ValueError(
            f"output type of {type_} {strify(method)} must be serializable as a JSON object: "
            f"{exception}"
        )

    return __ProcedureMethodInfo(
        name=_get_bound_name(method),
        method=get_function_name(method),
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


@validated_function
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
                method=get_function_name(method),
                restart=RoutineRestartPolicy(restart),
                restart_delay=decode_td(restart_delay),
            ),
        )

        return method

    if method is None:
        return routine

    return routine(method)


def _get_bound_name(function: Callable[..., Any]) -> str:
    return _get_normalized_name(get_function_name(function))


def _get_normalized_name(name: str) -> Name:
    return name.replace("_", "-").strip().strip("-")


@runtime_checkable
class Binding(Protocol):
    method: str


_BindingT = TypeVar("_BindingT", bound=Binding)


def get_method_bindings(
    method: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    method = get_inner_function(method)
    output: list[_BindingT] = []

    if values := getattr(method, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_method_binding(
    method: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> _BindingT | None:
    bindings = get_method_bindings(method, binding_cls)
    if bindings:
        return bindings[0]

    return None


def _bind(method: Callable[..., object], binding: Binding) -> None:
    method = get_inner_function(method)
    bindings: Sequence[Binding] | None = getattr(method, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(method, _BINDINGS_ATTRIBUTE, bindings)


def get_bindings(component_cls: type[Component], binding_cls: type[_BindingT]) -> list[_BindingT]:
    bindings: dict[str, _BindingT] = {}

    for cls in reversed(component_cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_method_bindings(member, binding_cls):
                bindings[binding.method] = binding

    return sorted(bindings.values(), key=lambda current: current.method)
