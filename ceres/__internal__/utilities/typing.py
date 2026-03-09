import typing
from asyncio import Future
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Generic,
    NoDefault,
    TypeAlias,
    TypeAliasType,
    TypeIs,
    TypeVar,
    TypeVarTuple,
    overload,
)

from typing_inspection import typing_objects

from ceres.__internal__.utilities.caching import cached

if TYPE_CHECKING:
    from pydantic.fields import FieldInfo

Stringy: TypeAlias = str | bytes | bytearray | memoryview


def is_stringy(obj: Any, /) -> TypeIs[Stringy]:
    if obj is None:
        return False

    return isinstance(obj, Stringy)


def is_iterable(obj: Any, /) -> TypeIs[Iterable[Any]]:
    if obj is None:
        return False
    if is_stringy(obj):
        return False
    if isinstance(obj, Future):
        return False
    if not isinstance(obj, Iterable):
        return False

    try:
        iter(obj)
    except Exception:
        return False

    return True


def is_collection(obj: Any, /) -> TypeIs[Collection[Any]]:
    if obj is None:
        return False
    if isinstance(obj, (list, tuple, set, frozenset)):
        return True
    if not isinstance(obj, Collection):
        return False
    if is_stringy(obj):
        return False

    try:
        len(obj)
    except Exception:
        return False

    return True


def is_sequence(obj: Any, /) -> TypeIs[Sequence[Any]]:
    if obj is None:
        return False
    if isinstance(obj, (list, tuple)):
        return True
    if not isinstance(obj, Sequence):
        return False
    if is_stringy(obj):
        return False

    try:
        len(obj)
    except Exception:
        return False

    return True


def is_mapping(obj: Any, /) -> TypeIs[Mapping[Any, Any]]:
    if obj is None:
        return False
    if isinstance(obj, dict):
        return True
    if not isinstance(obj, Mapping):
        return False

    try:
        obj.keys()
    except Exception:
        return False

    return True


if TYPE_CHECKING:
    from builtins import isinstance as _lenient_isinstance
    from builtins import issubclass as _lenient_issubclass
else:

    def _lenient_isinstance(obj, cls):
        try:
            return isinstance(obj, cls)
        except TypeError:
            return False

    def _lenient_issubclass(obj, cls):
        try:
            return issubclass(obj, cls)
        except TypeError:
            return False


lenient_isinstance = _lenient_isinstance
lenient_issubclass = _lenient_issubclass

_EMPTY_MAPPING = {}

if TYPE_CHECKING:
    from typing import ParamSpec, ParamSpecArgs, ParamSpecKwargs

    @overload
    def get_origin(tp: ParamSpecArgs | ParamSpecKwargs, /) -> ParamSpec: ...
    @overload
    def get_origin(tp: UnionType, /) -> type[UnionType]: ...

    @overload
    def get_origin(tp: GenericAlias, /) -> type: ...
    @overload
    def get_origin(tp: Any, /) -> Any | None: ...  # AnnotationForm


def get_origin(obj: Any, /) -> Any:
    origin = getattr(obj, "__pydantic_generic_metadata__", _EMPTY_MAPPING).get("origin")
    if origin is None:
        origin = typing.get_origin(obj)
    if origin is None and hasattr(obj, "__origin__"):
        origin = getattr(obj, "__origin__", None)

    return origin


def get_args(obj: Any, /) -> tuple[Any, ...]:
    args = getattr(obj, "__pydantic_generic_metadata__", _EMPTY_MAPPING).get("args")
    if args is None:
        args = typing.get_args(obj)
    if not args:
        args = getattr(obj, "__args__", ())

    return args


def get_parameters(obj: Any, /) -> tuple[Any, ...]:
    parameters = getattr(obj, "__pydantic_generic_metadata__", _EMPTY_MAPPING).get("parameters")
    if parameters is None:
        parameters = getattr(obj, "__parameters__", ())

    return parameters


_TRANSPARENT_ARGS_TYPES = {
    typing.Annotated,
    typing.ClassVar,
    typing.NotRequired,
    typing.Optional,
    typing.Required,
}


def extract_annotation(annotation: Any, /) -> tuple[Any, list[Any]]:
    current = annotation
    metadata: list[Any] = []

    while True:
        origin = get_origin(current)
        if is_type_alias(current):
            current = current.__value__
            continue

        if origin in _TRANSPARENT_ARGS_TYPES:
            args = get_args(current)
            if args:
                current, *current_metadata = args
                if origin is Annotated:
                    metadata.extend(current_metadata)

                continue

        return current, metadata


def get_annotated_metadata(annotation: Any, /) -> list[Any]:
    _, metadata = extract_annotation(annotation)
    return metadata


def get_annotated_type(annotation: Any, /) -> Any:
    inner, _ = extract_annotation(annotation)
    return inner


def get_field_metadata(field: FieldInfo, /) -> list[Any]:
    metadata = list(field.metadata)
    metadata_ids: set[int] = set()
    for current in get_annotated_metadata(field.annotation):
        current_id = id(current)
        if current_id not in metadata_ids:
            metadata.append(current)
            metadata_ids.add(current_id)

    return metadata


def get_field_type(field: FieldInfo, /) -> Any:
    return get_annotated_type(field.annotation)


def get_return_annotation(
    function: Callable[..., Any],
    /,
    default: Any = None,
) -> Any:
    hints = typing.get_type_hints(function)
    return hints.get("return", default)


is_typevar = typing_objects.is_typevar
is_typevartuple = typing_objects.is_typevartuple
is_paramspec = typing_objects.is_paramspec
is_nodefault = typing_objects.is_nodefault


def is_type_alias(obj: Any, /) -> TypeIs[TypeAliasType]:
    return typing_objects.is_typealiastype(obj)


def is_type_parameter(obj: Any, /) -> TypeIs[TypeVar | TypeVarTuple | ParamSpec]:
    return is_typevar(obj) or is_typevartuple(obj) or is_paramspec(obj)


def is_generic_alias(obj: Any, /) -> TypeIs[GenericAlias]:
    return isinstance(obj, GenericAlias)


def is_generic_alias_like(cls: Any, /) -> TypeIs[GenericAlias]:
    if is_generic_alias(cls):
        return True
    if getattr(cls, "__origin__", None) is None:
        return False
    if not getattr(cls, "__args__", ()):
        return False

    return True


def is_assignable(
    variable_type: Any,
    assigned_type: Any,
    /,
) -> bool:
    assigned_type = get_annotated_type(assigned_type)
    variable_type = get_annotated_type(variable_type)

    if assigned_type is Any or variable_type is Any:
        return True
    if assigned_type is object:
        return True

    if isinstance(assigned_type, UnionType):
        # Ensure all options in the assigned type are assignable to the variable type.
        return all(is_assignable(variable_type, option) for option in get_args(assigned_type))
    if isinstance(variable_type, UnionType):
        # Ensure at least one option in the variable type is assignable to the assigned type.
        return any(is_assignable(option, assigned_type) for option in get_args(variable_type))

    # Finally, check if the assigned type is a just class that is a subclass of the variable type.
    return (
        isinstance(variable_type, type)
        and isinstance(assigned_type, type)
        and issubclass(variable_type, assigned_type)
    )


if TYPE_CHECKING:
    from types import GenericAlias as __GenericAlias

    GenericAlias = __GenericAlias
else:

    class _A[T]: ...

    GenericAlias = type(_A[int])


type GenericVariable = tuple[type[Any] | GenericAlias, TypeVar]
type GenericVariableMapping = Mapping[GenericVariable, GenericVariable]


def _get_parameters(cls: type[Any]) -> tuple[TypeVar, ...]:
    return getattr(cls, "__parameters__", ())


@cached(weak=True)
def get_generic_variable_mapping(cls: type[Any] | GenericAlias) -> GenericVariableMapping:
    mapping: dict[GenericVariable, GenericVariable] = {}

    if is_generic_alias_like(cls):
        origin: Any = cls.__origin__
        if origin is not Generic:
            parameters = _get_parameters(origin)
            arguments = cls.__args__
            for parameter, argument in zip(parameters, arguments):
                mapping[(origin, parameter)] = (cls, argument)

            if origin is not cls:
                mapping.update(get_generic_variable_mapping(origin))

        return mapping

    bases: tuple[type[Any] | GenericAlias, ...] = getattr(cls, "__orig_bases__", cls.__bases__)
    parameters = _get_parameters(cls)
    for base in bases:
        if is_generic_alias_like(base):
            origin = base.__origin__
            if origin is Generic:
                continue

            mapping.update(get_generic_variable_mapping(base))

            arguments = base.__args__
            for parameter in parameters:
                if is_typevar(parameter) and parameter in arguments:
                    mapping[(base, parameter)] = (cls, parameter)
        else:
            mapping.update(get_generic_variable_mapping(base))

    return MappingProxyType(mapping)


@cached(weak=True)
def get_inverse_generic_variable_mapping(
    cls: type[Any] | GenericAlias,
) -> GenericVariableMapping:
    return {value: key for key, value in get_generic_variable_mapping(cls).items()}


def _find_generic_superclass_argument[T](
    mapping: GenericVariableMapping,
    superclass: type[T],
    parameter: TypeVar,
) -> Any:
    from typing_inspection.typing_objects import is_typevar

    current = mapping.get((superclass, parameter))
    if current is None:
        return parameter

    default: Any = NoDefault
    while True:
        _, assigned = current
        # If we've reached a non-type variable, this is the resolved type for the generic variable.
        if not is_typevar(assigned):
            return assigned

        if not is_nodefault(assigned.__default__):
            default = assigned.__default__

        next = mapping.get(current)
        if next is None:
            if default is not NoDefault:
                return default

            return assigned

        current = next


def _superclass_sanity_check[T](cls: type[T] | GenericAlias, superclass: type[T]) -> None:
    origin = get_origin(cls) or cls
    if not isinstance(origin, type):
        raise TypeError(f"`cls` must be a class or generic alias, got `{type(cls)}`.")
    if not isinstance(superclass, type):
        raise TypeError(f"`superclass` must be a class, got `{type(superclass)}`.")
    if not issubclass(origin, superclass):
        raise TypeError(f"`{cls}` does not inherit from `{superclass}`.")


def get_generic_superclass_argument[T](
    cls: type[T] | GenericAlias,
    superclass: type[T],
    index: int,
) -> Any:
    _superclass_sanity_check(cls, superclass)
    try:
        parameter = _get_parameters(superclass)[index]
    except IndexError:
        raise IndexError(
            f"Generic superclass `{superclass}` has no type parameter at index {index}."
        )

    assignments = get_generic_variable_mapping(cls)
    return _find_generic_superclass_argument(assignments, superclass, parameter)


def get_generic_superclass_arguments[T](
    cls: type[T] | GenericAlias,
    superclass: type[T],
) -> tuple[Any, ...]:
    _superclass_sanity_check(cls, superclass)
    parameters = _get_parameters(superclass)
    mapping = get_generic_variable_mapping(cls)
    return tuple(
        _find_generic_superclass_argument(mapping, superclass, parameter)
        for parameter in parameters
    )


def get_generic_parameter_chain[Any](
    cls: type[Any] | GenericAlias,
    parameter: TypeVar,
) -> list[TypeVar]:
    from ceres.__internal__.utilities.collections import uniq

    mapping = get_inverse_generic_variable_mapping(cls)
    parameters: list[TypeVar] = [parameter]

    current: GenericVariable = (cls, parameter)
    while True:
        next = mapping.get(current)
        if next is None:
            break

        _, next_parameter = next
        if not is_typevar(next_parameter):
            break

        current = next
        parameters.append(next_parameter)

    return list(uniq(parameters))


if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.engine import Engine


@overload
def as_component(obj: ComponentSystem | Component, /) -> Component: ...


@overload
def as_component(obj: ComponentSystem | Component | None, /) -> Component | None: ...


def as_component(obj: ComponentSystem | Component | None, /) -> Component | None:
    from ceres.component import Component, ComponentSystem

    if isinstance(obj, Component):
        return obj
    if not isinstance(obj, ComponentSystem):
        return None

    return obj.component


@overload
def as_component_system(obj: ComponentSystem | Component, /) -> ComponentSystem: ...


@overload
def as_component_system(obj: ComponentSystem | Component | None, /) -> ComponentSystem | None: ...


@overload
def as_component_system(obj: object | None, /) -> ComponentSystem | None: ...


def as_component_system(obj: object | None, /) -> ComponentSystem | None:
    from ceres.component import Component, ComponentSystem

    if isinstance(obj, ComponentSystem):
        return obj
    if isinstance(obj, Component):
        return obj.system

    return None


def as_components(objects: Iterable[ComponentSystem | Component | None], /) -> list[Component]:
    components: list[Component] = []
    for current in objects:
        component = as_component(current)
        if component is not None:
            components.append(component)

    return components


def as_component_systems(
    objects: Iterable[ComponentSystem | Component | None],
    /,
) -> list[ComponentSystem]:
    systems: list[ComponentSystem] = []
    for current in objects:
        system = as_component_system(current)
        if system is not None:
            systems.append(system)

    return systems


def as_engine(obj: object | None, /) -> Engine | None:
    from ceres.engine import Engine

    if isinstance(obj, Engine):
        return obj

    return None
