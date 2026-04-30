import typing
from asyncio import Future
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
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

from pydantic.fields import FieldInfo
from typing_inspection import typing_objects

from ceres.__internal__.utilities.caching import cached

Stringy: TypeAlias = str | bytes | bytearray | memoryview


def is_stringy(obj: Any, /) -> TypeIs[Stringy]:
    """Check whether ``obj`` is a string-like type (``str``, ``bytes``, ``bytearray``, or
    ``memoryview``).
    """
    if obj is None:
        return False

    return isinstance(obj, Stringy)


def is_iterable(obj: Any, /) -> TypeIs[Iterable[Any]]:
    """Check whether ``obj`` is a non-string, non-future iterable.

    Exclude string-like types and ``Future`` instances, which are technically iterable but rarely
    intended to be iterated over directly.
    """
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
    """Check whether ``obj`` is a non-string collection with a known length.

    Return ``True`` for lists, tuples, sets, frozensets, and other ``Collection`` types that
    support ``len()``, excluding string-like types.
    """
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
    """Check whether ``obj`` is a non-string sequence with a known length.

    Return ``True`` for lists, tuples, and other ``Sequence`` types that support ``len()``,
    excluding string-like types.
    """
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
    """Check whether ``obj`` is a mapping type (dict or ``Mapping``) that supports ``.keys()``."""
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
    """Return the generic origin of a type, checking Pydantic metadata before ``typing.get_origin``.

    Args:
        obj: A type annotation or generic alias.

    Returns:
        The origin type, or ``None`` if ``obj`` is not generic.
    """
    origin = getattr(obj, "__pydantic_generic_metadata__", _EMPTY_MAPPING).get("origin")
    if origin is None:
        origin = typing.get_origin(obj)
    if origin is None and hasattr(obj, "__origin__"):
        origin = getattr(obj, "__origin__", None)

    return origin


def get_args(obj: Any, /) -> tuple[Any, ...]:
    """Return the type arguments of a generic type, checking Pydantic metadata first.

    Args:
        obj: A type annotation or generic alias.

    Returns:
        A tuple of type arguments, or an empty tuple if none are present.
    """
    args = getattr(obj, "__pydantic_generic_metadata__", _EMPTY_MAPPING).get("args")
    if args is None:
        args = typing.get_args(obj)
    if not args:
        args = getattr(obj, "__args__", ())

    return args


def get_parameters(obj: Any, /) -> tuple[Any, ...]:
    """Return the unresolved type parameters of a generic type, checking Pydantic metadata first.

    Args:
        obj: A type annotation or generic alias.

    Returns:
        A tuple of type parameters (``TypeVar`` etc.), or an empty tuple if none are present.
    """
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


@dataclass(frozen=True, kw_only=True)
class AnnotationInfo:
    """Decomposed representation of a type annotation.

    Hold the unwrapped inner type, any generic alias, and collected metadata from ``Annotated``
    wrappers and Pydantic ``FieldInfo``.
    """

    annotation: Any
    """The original type annotation."""
    type: Any
    """The inner type of the annotation, before any generic arguments are applied."""
    generic: GenericAlias | None
    """The generic alias of the annotation, provided it is a generic type."""
    metadata: tuple[Any, ...]
    """The metadata extracted from the annotation."""

    @property
    def generic_args(self) -> tuple[Any, ...]:
        """Return the type arguments of the generic alias, or an empty tuple if not generic."""
        if self.generic is None:
            return ()

        return typing.get_args(self.generic)


def extract_annotation(annotation: Any | FieldInfo, /) -> AnnotationInfo:
    """Unwrap a type annotation into its constituent parts.

    Strip ``Annotated``, ``ClassVar``, ``Optional``, ``Required``, ``NotRequired``, and Pydantic
    ``FieldInfo`` wrappers to extract the inner type, generic alias, and accumulated metadata.

    Args:
        annotation: A raw type annotation or Pydantic ``FieldInfo`` to decompose.

    Returns:
        An ``AnnotationInfo`` containing the unwrapped type, generic alias, and metadata.
    """
    field_metadata: list[Any] = []

    if isinstance(annotation, FieldInfo):
        field_metadata = list(annotation.metadata)
        current = annotation.annotation
    else:
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

        break

    inner = current
    generic_origin = get_origin(inner)
    generic: GenericAlias | None = None
    if generic_origin is not None:
        generic = inner  # type: ignore
        inner = generic_origin

    if field_metadata:
        field_metadata_ids = {id(item) for item in field_metadata}
        for current_meta in metadata:
            if id(current_meta) not in field_metadata_ids:
                field_metadata.append(current_meta)

        combined_metadata = tuple(field_metadata)
    else:
        combined_metadata = tuple(metadata)

    return AnnotationInfo(
        annotation=annotation,
        type=inner,
        generic=generic,
        metadata=combined_metadata,
    )


def get_return_annotation(
    function: Callable[..., Any],
    /,
    default: Any = None,
) -> Any:
    """Return the resolved return-type annotation of ``function``.

    Args:
        function: The callable whose return annotation to retrieve.
        default: The value to return if no return annotation is present.

    Returns:
        The return type hint, or ``default`` if the function has no return annotation.
    """
    hints = typing.get_type_hints(function)
    return hints.get("return", default)


is_typevar = typing_objects.is_typevar
is_typevartuple = typing_objects.is_typevartuple
is_paramspec = typing_objects.is_paramspec
is_nodefault = typing_objects.is_nodefault


def is_type_alias(obj: Any, /) -> TypeIs[TypeAliasType]:
    """Check whether ``obj`` is a ``TypeAliasType``."""
    return typing_objects.is_typealiastype(obj)


def is_type_parameter(obj: Any, /) -> TypeIs[TypeVar | TypeVarTuple | ParamSpec]:
    """Check whether ``obj`` is a ``TypeVar``, ``TypeVarTuple``, or ``ParamSpec``."""
    return is_typevar(obj) or is_typevartuple(obj) or is_paramspec(obj)


def is_generic_alias(obj: Any, /) -> TypeIs[GenericAlias]:
    """Check whether ``obj`` is a ``GenericAlias`` (e.g. ``list[int]``)."""
    return isinstance(obj, GenericAlias)


def is_generic_alias_like(cls: Any, /) -> TypeIs[GenericAlias]:
    """Check whether ``cls`` looks like a generic alias by duck-typing.

    Return ``True`` if ``cls`` is a ``GenericAlias`` or has ``__origin__``, a non-empty
    ``__args__`` tuple, and a ``__parameters__`` tuple.
    """
    if is_generic_alias(cls):
        return True

    __origin__ = getattr(cls, "__origin__", None)
    if __origin__ is None:
        return False

    __args__ = getattr(cls, "__args__", ())
    if not isinstance(__args__, tuple) or not __args__:
        return False

    __parameters__ = getattr(cls, "__parameters__", ())
    if not isinstance(__parameters__, tuple):
        return False

    return True


def is_assignable(
    variable_type: Any,
    assigned_type: Any,
    /,
) -> bool:
    """Check whether ``assigned_type`` is assignable to ``variable_type``.

    Handle ``Any``, ``object``, union types, and plain class subclass relationships. Both types
    are unwrapped through ``extract_annotation`` before comparison.

    Args:
        variable_type: The target type being assigned to.
        assigned_type: The source type being assigned from.

    Returns:
        ``True`` if the assignment is type-compatible.
    """
    assigned_type = extract_annotation(assigned_type).type
    variable_type = extract_annotation(variable_type).type

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
    """Return the ``__parameters__`` tuple of ``cls``, defaulting to an empty tuple."""
    return getattr(cls, "__parameters__", ())


@cached(weak=True)
def get_generic_variable_mapping(cls: type[Any] | GenericAlias) -> GenericVariableMapping:
    """Build a mapping from generic type parameters to their assigned types across the MRO.

    Walk the class hierarchy and generic alias chain to track how each ``TypeVar`` is mapped
    from superclass to subclass.

    Args:
        cls: A class or generic alias to inspect.

    Returns:
        A mapping from ``(declaring_class, TypeVar)`` pairs to ``(assigning_class, assigned_type)``
        pairs.
    """
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
    """Return the inverse of ``get_generic_variable_mapping`` for ``cls``.

    Args:
        cls: A class or generic alias to inspect.

    Returns:
        A mapping from ``(assigning_class, assigned_type)`` to ``(declaring_class, TypeVar)``.
    """
    return {value: key for key, value in get_generic_variable_mapping(cls).items()}


def _find_generic_superclass_argument[T](
    mapping: GenericVariableMapping,
    superclass: type[T],
    parameter: TypeVar,
) -> Any:
    """Resolve a single generic type parameter through a variable mapping chain.

    Follow the mapping from ``(superclass, parameter)`` through successive assignments until a
    concrete type or a terminal ``TypeVar`` (possibly with a default) is reached.

    Args:
        mapping: The generic variable mapping to traverse.
        superclass: The class that declared the type parameter.
        parameter: The ``TypeVar`` to resolve.

    Returns:
        The resolved concrete type, the ``TypeVar`` default, or the terminal ``TypeVar`` itself.
    """
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
    """Validate that ``cls`` is a class or generic alias and inherits from ``superclass``.

    Raises:
        TypeError: If ``cls`` or ``superclass`` is not a valid type, or ``cls`` does not inherit
            from ``superclass``.
    """
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
    """Resolve a single type argument that ``cls`` assigns to a generic ``superclass``.

    Args:
        cls: The subclass or generic alias to inspect.
        superclass: The generic superclass whose type parameter to resolve.
        index: The zero-based index of the type parameter on ``superclass``.

    Returns:
        The resolved type argument at the given index.

    Raises:
        TypeError: If ``cls`` does not inherit from ``superclass``.
        IndexError: If ``index`` is out of range for the superclass's type parameters.
    """
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
    """Resolve all type arguments that ``cls`` assigns to a generic ``superclass``.

    Args:
        cls: The subclass or generic alias to inspect.
        superclass: The generic superclass whose type parameters to resolve.

    Returns:
        A tuple of resolved type arguments, one per type parameter on ``superclass``.

    Raises:
        TypeError: If ``cls`` does not inherit from ``superclass``.
    """
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
    """Trace the chain of ``TypeVar`` assignments for ``parameter`` down through the class hierarchy.

    Walk the inverse generic variable mapping starting from ``(cls, parameter)`` and collect each
    ``TypeVar`` encountered along the way.

    Args:
        cls: The class or generic alias to start from.
        parameter: The ``TypeVar`` whose assignment chain to trace.

    Returns:
        A deduplicated list of ``TypeVar`` instances in the chain, starting with ``parameter``.
    """
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
    """Extract a ``Component`` from the given object.

    Accept a ``Component`` directly, unwrap a ``ComponentSystem`` to its component, or return
    ``None`` for anything else.
    """
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
    """Extract a ``ComponentSystem`` from the given object.

    Accept a ``ComponentSystem`` directly, unwrap a ``Component`` to its system, or return
    ``None`` for anything else.
    """
    from ceres.component import Component, ComponentSystem

    if isinstance(obj, ComponentSystem):
        return obj
    if isinstance(obj, Component):
        return obj.system

    return None


def as_components(objects: Iterable[ComponentSystem | Component | None], /) -> list[Component]:
    """Convert an iterable of component-like objects to a list of ``Component`` instances.

    Skip ``None`` values and objects that cannot be converted.

    Args:
        objects: An iterable of ``ComponentSystem``, ``Component``, or ``None`` values.

    Returns:
        A list of successfully extracted ``Component`` instances.
    """
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
    """Convert an iterable of component-like objects to a list of ``ComponentSystem`` instances.

    Skip ``None`` values and objects that cannot be converted.

    Args:
        objects: An iterable of ``ComponentSystem``, ``Component``, or ``None`` values.

    Returns:
        A list of successfully extracted ``ComponentSystem`` instances.
    """
    systems: list[ComponentSystem] = []
    for current in objects:
        system = as_component_system(current)
        if system is not None:
            systems.append(system)

    return systems


def as_engine(obj: object | None, /) -> Engine | None:
    """Return ``obj`` as an ``Engine`` if it is one, otherwise return ``None``."""
    from ceres.engine import Engine

    if isinstance(obj, Engine):
        return obj

    return None
