from __future__ import annotations

import dataclasses
from abc import ABCMeta
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableSet,
    Sequence,
    Set,
)
from copy import deepcopy
from functools import wraps
from types import GenericAlias, MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Final,
    Protocol,
    Self,
    TypeIs,
    TypeVar,
    cast,
    dataclass_transform,
    final,
    overload,
    override,
)
from warnings import warn
from weakref import WeakKeyDictionary

import pydantic
from pydantic import (
    AfterValidator,
    AliasGenerator,
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    SerializationInfo,
    TypeAdapter,
    model_serializer,
    model_validator,
)
from pydantic.aliases import AliasChoices, AliasPath
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic_core import (
    MISSING,
    ArgsKwargs,
    CoreSchema,
    PydanticUndefined,
    SchemaSerializer,
    SchemaValidator,
)

from ceres.__internal__.utilities.caching import cached
from ceres.__internal__.utilities.classes import (
    ClassProperty,
    cached_class_property,
    class_property,
    fields_cached_class_property,
    get_declared_slots,
)
from ceres.__internal__.utilities.collections import uniq
from ceres.__internal__.utilities.undefined import Undefined

if TYPE_CHECKING:
    from inspect import Signature
    from types import CellType

    from pydantic._internal._decorators import Decorator, DecoratorInfos

    from ceres.data import MaybeClass

__all__ = [
    "DataObject",
    "create",
    "construct",
    "fields_of",
    "computed_fields_of",
    "fields_set_on",
    "to_dict",
    "to_items",
    "replacing",
    "defaulting",
    "WithDefaults",
    "to_kwargs",
]


_cached_dataclasses: WeakKeyDictionary[type, type[PydanticDataclass]] = WeakKeyDictionary()
_cached_fields: WeakKeyDictionary[type, Mapping[str, FieldInfo]] = WeakKeyDictionary()
_cached_init_fields: WeakKeyDictionary[type, Mapping[str, FieldInfo]] = WeakKeyDictionary()
_cached_computed_fields: WeakKeyDictionary[type, Mapping[str, ComputedFieldInfo]] = (
    WeakKeyDictionary()
)


if TYPE_CHECKING:
    from _typeshed import DataclassInstance as __DataclassInstance

    class _DataclassParams(Protocol):
        """Protocol describing the `__dataclass_params__` attribute on a dataclass."""

        kw_only: bool
        frozen: bool
        init: bool
        repr: bool
        eq: bool
        order: bool
        unsafe_hash: bool
        match_args: bool
        slots: bool
        weakref_slot: bool

    class Dataclass(__DataclassInstance, Protocol):
        """Protocol representing any standard-library dataclass instance."""

        __slots__ = ()

    from pydantic._internal._dataclasses import PydanticDataclass as __PydanticDataclass

    class PydanticDataclass(__PydanticDataclass, Protocol):
        """Protocol representing any Pydantic-wrapped dataclass instance."""

        __slots__ = ()

    class _SupportsPydanticFields(Protocol):
        """Protocol for objects exposing a `__pydantic_fields__` mapping."""

        if TYPE_CHECKING:
            __pydantic_fields__: ClassVar[dict[str, FieldInfo]]

    class _SupportsPydanticFieldsSet(_SupportsPydanticFields, Protocol):
        """Protocol extending `_SupportsPydanticFields` with a fields-set property."""

        @property
        def __pydantic_fields_set__(self) -> Set[str]: ...

    class _SupportsReplace(Protocol):
        """Protocol for objects implementing the `__replace__` copy-with-changes pattern."""

        def __replace__(self, *args: Any, **changes: Any) -> Any: ...
else:

    class Dataclass:
        """Runtime stub for the `Dataclass` protocol."""

        __slots__ = ()

    class PydanticDataclass:
        """Runtime stub for the `PydanticDataclass` protocol."""

        __slots__ = ()


@overload
def _is_dataclass(obj: type) -> TypeIs[type[Dataclass]]: ...
@overload
def _is_dataclass(obj: object) -> TypeIs[MaybeClass[Dataclass]]: ...
def _is_dataclass(obj: object) -> TypeIs[MaybeClass[Dataclass]]:
    return dataclasses.is_dataclass(obj)


def _get_dataclass_params(cls: type[Dataclass]) -> _DataclassParams:
    return getattr(cls, "__dataclass_params__")


def _supports_pydantic_fields(obj: object) -> TypeIs[MaybeClass[_SupportsPydanticFields]]:
    return hasattr(obj, "__pydantic_fields__")


def _supports_fields_set(obj: object) -> TypeIs[_SupportsPydanticFieldsSet]:
    return hasattr(obj, "__pydantic_fields_set__")


def _supports_replace(obj: object) -> TypeIs[_SupportsReplace]:
    return hasattr(obj, "__replace__") and not isinstance(obj, type)


@cached(storage=_cached_dataclasses)
def _as_pydantic_dataclass(cls: type[Dataclass]) -> type[PydanticDataclass]:
    if pydantic.dataclasses.is_pydantic_dataclass(cls):
        return cls

    return pydantic.dataclasses.dataclass(
        config={"arbitrary_types_allowed": True},
        frozen=_get_dataclass_params(cls).frozen,
    )(
        cls,
    )


def _as_class[T](obj: MaybeClass[T]) -> type[T]:
    return obj if isinstance(obj, type) else type(obj)


def _decorators_of(cls: type[PydanticDataclass]) -> Iterable[tuple[str, Decorator]]:
    for _, decorators in to_items(cls.__pydantic_decorators__):
        if isinstance(decorators, Mapping):
            yield from decorators.items()


def _generate_validation_aliases(field: str) -> str | AliasChoices:
    if "_" not in field:
        return field

    return AliasChoices(field, field.replace("_", "-"))


def fields_of(
    obj: MaybeClass[_SupportsPydanticFields | Dataclass],
    /,
    init: bool = False,
    cache: bool = True,
) -> Mapping[str, FieldInfo]:
    """Return a mapping of field names to `FieldInfo` for the given object or class.

    Accept any Pydantic model, `DataObject`, or standard dataclass instance or class.
    Standard dataclasses are automatically wrapped as Pydantic dataclasses on first access
    so their fields can be expressed as `FieldInfo`.

    Args:
        obj: A class or instance with Pydantic fields, or a standard dataclass.
        init: When `True`, include `init_var` fields (excluded by default).
        cache: When `True`, cache the result per class for faster repeated lookups.

    Returns:
        An immutable mapping from field name to `FieldInfo`.

    Raises:
        TypeError: If `obj` is neither a Pydantic-aware type nor a standard dataclass.
    """
    cls = _as_class(obj)
    storage = _cached_init_fields if init else _cached_fields
    if cache:
        cached = storage.get(cls, Undefined)
        if cached is not Undefined:
            return cached

    if not _supports_pydantic_fields(cls):
        if _is_dataclass(cls):
            cls = _as_pydantic_dataclass(cls)
        else:
            raise TypeError(f"Unsupported type for `fields_of`: {cls}")

    fields: Mapping[str, FieldInfo] = {}
    for field, info in cls.__pydantic_fields__.items():
        if not init and info.init_var:
            continue

        fields[field] = info

    fields = MappingProxyType(fields)
    if cache:
        fields = storage.setdefault(cls, fields)

    return fields


def computed_fields_of(
    obj: MaybeClass[_SupportsPydanticFields | Dataclass],
    /,
    *,
    cache: bool = True,
) -> Mapping[str, ComputedFieldInfo]:
    """Return a mapping of computed field names to `ComputedFieldInfo`.

    Args:
        obj: A class or instance with Pydantic computed fields, or a standard dataclass.
        cache: When `True`, cache the result per class for faster repeated lookups.

    Returns:
        An immutable mapping from computed field name to `ComputedFieldInfo`.

    Raises:
        TypeError: If `obj` is neither a Pydantic `BaseModel` nor a standard dataclass.
    """
    cls = _as_class(obj)
    if cache:
        cached = _cached_computed_fields.get(cls, Undefined)
        if cached is not Undefined:
            return cached

    if isinstance(obj, BaseModel):
        fields = MappingProxyType(obj.__pydantic_computed_fields__)
    elif _is_dataclass(cls):
        cls = _as_pydantic_dataclass(cls)
        fields = MappingProxyType(
            {
                name: decorator.info
                for name, decorator in cls.__pydantic_decorators__.computed_fields.items()
            }
        )
    else:
        raise TypeError(f"Unsupported type for `computed_fields_of`: {cls}")

    if cache:
        fields = _cached_computed_fields.setdefault(cls, fields)

    return fields


def to_items(
    obj: _SupportsPydanticFields | Dataclass,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    exclude_unset: bool = False,
    exclude_computed_fields: bool = True,
) -> Iterator[tuple[str, Any]]:
    """Yield `(field_name, value)` pairs for each field on `obj`.

    Args:
        obj: A Pydantic-aware object or standard dataclass instance.
        include: If provided, only yield fields whose names are in this set.
        exclude: If provided, skip fields whose names are in this set.
        exclude_unset: When `True`, skip fields that were not explicitly set.
        exclude_computed_fields: When `True` (the default), skip computed fields.

    Yields:
        Two-tuples of `(field_name, value)` for each matching field.
    """
    if not exclude_unset or not _supports_fields_set(obj):
        fields_set = None
    else:
        fields_set = fields_set_on(obj)

    for field in fields_of(obj):
        if include is not None and field not in include:
            continue
        if exclude is not None and field in exclude:
            continue
        if fields_set is not None and field not in fields_set:
            continue
        value = getattr(obj, field, Undefined)
        if value is Undefined:
            continue

        yield field, value

    if not exclude_computed_fields:
        for field in computed_fields_of(obj):
            if include is not None and field not in include:
                continue
            if exclude is not None and field in exclude:
                continue

            value = getattr(obj, field, Undefined)
            if value is Undefined:
                continue

            yield field, value


def fields_set_on(obj: _SupportsPydanticFieldsSet, /) -> Set[str]:
    """Return the set of field names explicitly set on `obj`.

    Args:
        obj: An object with a `__pydantic_fields_set__` property.

    Returns:
        The set of field names that were explicitly provided during construction or assigned
        afterward.

    Raises:
        TypeError: If `obj` does not support fields-set tracking.
    """
    try:
        return obj.__pydantic_fields_set__
    except AttributeError:
        raise TypeError(f"Unsupported type for `{fields_set_on.__name__}`: {type(obj)}")


def to_dict(
    obj: _SupportsPydanticFields | Dataclass,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    exclude_unset: bool = False,
    exclude_computed_fields: bool = True,
) -> dict[str, Any]:
    """Convert the fields of `obj` to a plain dictionary.

    Accept the same filtering arguments as `to_items` and return their results as a
    `dict` instead of an iterator.

    Args:
        obj: A Pydantic-aware object or standard dataclass instance.
        include: If provided, only include fields whose names are in this set.
        exclude: If provided, skip fields whose names are in this set.
        exclude_unset: When `True`, skip fields that were not explicitly set.
        exclude_computed_fields: When `True` (the default), skip computed fields.

    Returns:
        A dictionary mapping field names to their values.
    """
    return dict(
        to_items(
            obj,
            include=include,
            exclude=exclude,
            exclude_unset=exclude_unset,
            exclude_computed_fields=exclude_computed_fields,
        )
    )


if TYPE_CHECKING:

    class _SupportsDefaulting(_SupportsPydanticFieldsSet, _SupportsReplace, Protocol):
        """Protocol for objects that support both fields-set tracking and `__replace__`."""


def _get_items(
    obj: Mapping[str, Any] | _SupportsPydanticFieldsSet | None,
) -> Iterable[tuple[str, Any]]:
    if obj is None:
        return ()
    if isinstance(obj, Mapping):
        return obj.items()

    return to_items(obj, exclude_unset=True)


def defaulting[T: _SupportsDefaulting](
    original: T,
    defaults_object: T | dict[str, Any] | None = None,
    /,
    **defaults: Any,
) -> T:
    """Return a copy of `original` with unset fields filled in from `defaults`.

    Only fields that were *not* explicitly set on `original` are updated. Fields that
    were already set keep their existing values.

    Args:
        original: The object to fill defaults into.
        defaults_object: An optional object or dict supplying default values. Values from
            this object are merged with `**defaults`, with `**defaults` taking priority.
        **defaults: Additional default values keyed by field name.

    Returns:
        A copy of `original` with unset fields populated from the merged defaults.
    """
    from copy import replace

    for field, value in _get_items(defaults_object):
        defaults.setdefault(field, value)

    existing = original.__pydantic_fields_set__
    updates = {field: value for field, value in defaults.items() if field not in existing}

    return replace(original, **updates)


if TYPE_CHECKING:

    class _SupportsReplacing(_SupportsPydanticFieldsSet, _SupportsReplace, Protocol):
        """Protocol for objects that support fields-set tracking and `__replace__`."""


def replacing[T: _SupportsReplacing](
    original: T,
    updates_object: T | dict[str, Any] | None = None,
    /,
    **updates: Any,
) -> T:
    """Return a copy of `original` with the specified fields replaced.

    Unlike `defaulting`, this unconditionally overwrites fields regardless of whether
    they were set on `original`.

    Args:
        original: The object to copy with replacements.
        updates_object: An optional object or dict supplying replacement values. Values
            from this object are merged with `**updates`, with `**updates` taking
            priority.
        **updates: Additional replacement values keyed by field name.

    Returns:
        A copy of `original` with the specified fields replaced.
    """
    from copy import replace

    for field, value in _get_items(updates_object):
        updates.setdefault(field, value)

    return replace(original, **updates)


def WithDefaults(
    defaults_object: _SupportsDefaulting | Callable[[], _SupportsDefaulting] | None = None,
    /,
    **defaults: Any,
) -> AfterValidator:
    """Create a Pydantic `AfterValidator` that fills unset fields with defaults.

    Use as a field annotation wrapper (via `Annotated`) to automatically apply
    `defaulting` after Pydantic validation.

    Args:
        defaults_object: An object, callable returning an object, or `None` supplying
            default field values. A callable is invoked lazily on first use.
        **defaults: Additional default values keyed by field name.

    Returns:
        An `AfterValidator` that applies `defaulting` to the validated value.
    """

    def WithDefaults(obj: object, /) -> Any:
        if not _supports_fields_set(obj) or not _supports_replace(obj):
            raise TypeError(
                "`WithDefaults` can only be applied to types with set fields tracking and a "
                "`__replace__` method, such as `BaseModel` or `DataObject` instances."
            )

        nonlocal defaults_object
        if callable(defaults_object):
            defaults_object = defaults_object()

        return defaulting(obj, defaults_object, **defaults)

    return AfterValidator(WithDefaults)


_object_setattr: Final = object.__setattr__


class DataObjectConfigDict(ConfigDict):
    """Pydantic `ConfigDict` subclass used by `DataObject` and its subclasses."""


_DATA_OBJECT_ALIAS_GENERATOR = AliasGenerator(validation_alias=_generate_validation_aliases)
_DATA_OBJECT_DEFAULT_CONFIG = DataObjectConfigDict(
    extra="forbid",
    from_attributes=True,
    use_attribute_docstrings=True,
    alias_generator=_DATA_OBJECT_ALIAS_GENERATOR,
    arbitrary_types_allowed=True,
    validate_by_name=True,
    validate_by_alias=True,
)


def _patch_dataclass_fields() -> None:
    import pydantic
    from pydantic._internal._dataclasses import as_dataclass_field

    @wraps(as_dataclass_field)
    def patched_as_dataclass_field(pydantic_field: FieldInfo) -> dataclasses.Field[Any]:
        field = as_dataclass_field(pydantic_field)
        if pydantic_field.kw_only is not None:
            field.kw_only = pydantic_field.kw_only

        return field

    pydantic._internal._dataclasses.as_dataclass_field = patched_as_dataclass_field  # type: ignore


_patch_dataclass_fields()


class DataObjectClassInvalid(TypeError):
    """Raised when a `DataObject` subclass definition is structurally invalid."""


class DataObjectAbstract(RuntimeError):
    """Raised when code attempts to instantiate an abstract `DataObject` subclass."""


_data_object_classes_being_built: set[Any] = set()
_is_data_object_class_defined = False
_is_data_object_frozen_class_defined = False


class _Empty:
    pass


class DataObjectMetaclass(
    type(Protocol) if not TYPE_CHECKING else _Empty,
    ABCMeta,  # Allow data objects to inherit from `ABC`.
):
    """Metaclass that transforms `DataObject` subclasses into Pydantic dataclasses.

    On class creation, `DataObjectMetaclass` validates the class definition, merges
    inherited Pydantic config, converts the class via `pydantic.dataclasses.dataclass`,
    and enforces slot requirements for concrete subclasses.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        *,
        init: None = None,
        repr: None = None,
        eq: bool = True,
        order: bool = False,
        unsafe_hash: bool = False,
        frozen: bool | None = None,
        config: ConfigDict | None = None,
        kw_only: bool = True,
        slots: bool = False,
        abstract: bool = False,
        **kwargs: Any,
    ):
        data_object_class_name = "DataObject"

        if init is not None:
            raise DataObjectClassInvalid(
                f"`{data_object_class_name}` subclasses do not support setting `init`. "
                "The `__init__` method is always generated."
            )
        if repr is not None:
            raise DataObjectClassInvalid(
                f"`{data_object_class_name}` does support setting `repr`. "
                f"The `__repr__` method is defined within the `{data_object_class_name}` class. "
                "To customize `__repr__`, just define a new implementation in your subclass."
            )
        if "model_config" in namespace:
            warn(
                f"Defining `model_config` is not supported in `{data_object_class_name}` "
                "subclasses. It will be ignored. Define `ConfigDict` using the `config` class "
                "keyword argument."
            )
        if "__data_object_abstract__" in namespace and _is_data_object_class_defined:
            raise DataObjectClassInvalid(
                f"`{data_object_class_name}` does not support defining `__data_object_abstract__`"
                "in the class body. Use the `abstract` class keyword argument instead."
            )
        if abstract and slots:
            if "__slots__" in namespace:
                raise DataObjectClassInvalid(
                    f"`{data_object_class_name}` does not support defining `__slots__` when "
                    "`abstract=True`. Abstract data objects implicitly have empty `__slots__`."
                )

            namespace["__slots__"] = ()

        if "__data_object_generic_alias__" not in namespace:
            namespace["__data_object_generic_alias__"] = None

        if frozen is None:
            if not _is_data_object_frozen_class_defined:
                frozen = False
            else:
                # Any subclass of `FrozenDataObject` is implicitly frozen.
                if __Frozen__ is not None:
                    frozen = any(issubclass(base, __Frozen__) for base in bases)
                else:
                    frozen = False

        if frozen and _is_data_object_frozen_class_defined:
            # If `DataObject` is in the bases already, replace it with `__Frozen__`.
            bases = tuple(uniq((__Frozen__ if base is DataObject else base) for base in bases))
            # Ensure `FrozenDataObject` is in the bases if no subclass of it is already.
            if not any(issubclass(base, __Frozen__) for base in bases):
                bases = tuple((__Frozen__, *bases))

        inner_class = super().__new__(mcs, name, bases, namespace, **kwargs)
        key = (inner_class.__module__, name)
        if key in _data_object_classes_being_built:
            return inner_class

        # Collect inherited Pydantic config from base classes with `__pydantic_config__` defined.
        inherited_config = ConfigDict()
        for base in reversed(bases):
            current: ConfigDict | None = getattr(base, "__pydantic_config__", None)
            if current:
                inherited_config.update(current)

        config: ConfigDict = {
            **inherited_config,
            "title": inner_class.__qualname__,
            **(config or {}),
        }

        # Keep a reference to the original class's `__replace__` method. The `dataclass` decorator
        # overrides it, and we'll need to put it back.
        __replace__ = inner_class.__dict__.get("__replace__")
        if __replace__ is None:
            __replace__ = getattr(inner_class, "__replace__", None)

        # Preserve `__abstractmethods__` across the Pydantic dataclass transformation so that
        # `ABCMeta` can enforce abstract method implementation on concrete subclasses.
        __abstractmethods__ = inner_class.__dict__.get("__abstractmethods__", frozenset())

        # TODO: Use a more robust way to detect this.
        _data_object_classes_being_built.add(key)
        try:
            # Convert the class into a Pydantic dataclass.
            data_object_class = cast(
                "type[DataObject]",
                pydantic.dataclasses.dataclass(
                    repr=False,  # `DataObject` implements its own `__repr__`.
                    eq=eq,
                    order=order,
                    unsafe_hash=unsafe_hash,
                    frozen=frozen,
                    config=config,
                    slots=slots and not abstract,
                    kw_only=kw_only,
                )(inner_class),
            )

        finally:
            _data_object_classes_being_built.discard(key)

        data_object_class.__module__ = inner_class.__module__
        data_object_class.__name__ = inner_class.__name__
        data_object_class.__qualname__ = inner_class.__qualname__
        data_object_class.__doc__ = inner_class.__doc__
        data_object_class.__data_object_abstract__ = abstract
        data_object_class.__data_object_class__ = data_object_class

        # Add `__replace__` back into the class.
        if __replace__ is not None:
            setattr(data_object_class, "__replace__", __replace__)

        # Restore `__abstractmethods__` so `ABCMeta` enforces abstract method contracts.
        data_object_class.__abstractmethods__ = __abstractmethods__

        # Handle required slots logic.
        __data_object_required_slots__: list[str] = []
        if _is_data_object_class_defined:
            for base in reversed(bases):
                if issubclass(base, DataObject):
                    __data_object_required_slots__.extend(base.__data_object_required_slots__)
        if slots:
            __data_object_required_slots__.extend(
                field
                for field in data_object_class.__data_object_fields__
                if field in data_object_class.__dataclass_fields__
            )

        data_object_class.__data_object_required_slots__ = tuple(
            uniq(__data_object_required_slots__)
        )

        if slots:
            # The generated Pydantic dataclass validator ends up being an entirely different
            # class instance when the dataclass has `slots=True`. That class gets passed as
            # `cls` to all the field/model validators but misses a lot of attributes defined on
            # the dataclass. So we just copy them back to the inner class for now.
            inner_class__dict__ = inner_class.__dict__
            for attribute, value in data_object_class.__dict__.items():
                try:
                    inner_class_value = inner_class__dict__.get(attribute, Undefined)
                    if inner_class_value is Undefined or inner_class_value is not value:
                        setattr(inner_class, attribute, value)
                except AttributeError:
                    pass

        # Reassign the `__classcell__` of the class body to the dataclass we've created rather
        # than the original `cls` that was created and assigned by `type.__new__`. Failing to do so
        # will cause `super()` to work incorrectly and weird things will start breaking with
        # confusing error messages and you'll feel sad and nobody wants that.
        __classcell__: CellType | None = namespace.get("__classcell__")
        if __classcell__ is not None:
            __classcell__.cell_contents = data_object_class

        if not abstract:
            required = data_object_class.__data_object_required_slots__
            defined = set(data_object_class.__data_object_defined_slots__)
            missing = [slot for slot in required if slot not in defined]
            if missing:
                raise DataObjectClassInvalid(
                    f"Concrete data object subclass `{data_object_class}` is missing slots for "
                    f"fields: {missing}. Either define these in `__slots__`, set "
                    "`slots=True` in the class's class keyword arguments to define them "
                    "automatically, or set `abstract=True`."
                )

        data_object_class.__data_object_init_subclass__(**kwargs)
        return data_object_class

    @override
    def __repr__(cls) -> str:
        return f"<class {cls.__module__}.{cls.__qualname__}>"


@final
class FieldsSet(MutableSet[str]):
    """Bitmask-backed mutable set tracking which fields are "set" on a `DataObject`.

    Each field declared on a `DataObject` subclass is assigned a bit index. Membership
    tests, iteration, and set operations are performed on an integer bitmask, making
    common operations constant-time regardless of the number of fields.

    Construct from a `DataObject` class plus an optional initial population (a mask
    integer, a boolean for all/none, an iterable of field names, or another `FieldsSet`).
    """

    __slots__ = (
        "_cls",
        "_mask",
    )

    @overload
    def __init__(self, value: FieldsSet, /) -> None: ...
    @overload
    def __init__(self, value: type[DataObject], mask: int | None = None, /) -> None: ...
    @overload
    def __init__(self, value: type[DataObject], fields: bool | Iterable[str], /) -> None: ...

    def __init__(
        self,
        value: type[DataObject] | FieldsSet,
        fields: bool | int | Iterable[str] | None = None,
        /,
    ) -> None:
        if _is_data_object_type(value):
            self._cls = value
            if fields is None:
                mask = 0
            elif isinstance(fields, bool):
                mask = self._get_filled_mask() if fields else 0
            elif isinstance(fields, int):
                mask = self._validate_mask(fields)
            elif hasattr(fields, "__iter__"):
                mask = self._to_mask(fields)
            elif fields is not None:
                raise TypeError("Expected `int`, `Iterable[str]` or `None` as second argument.")

            self._mask = mask
        elif isinstance(value, FieldsSet):
            if fields is not None:
                raise ValueError(
                    f"Cannot specify mask/fields when copying from another `{type(self).__name__}`."
                )

            self._cls = value._cls
            self._mask = value._mask
        else:
            raise TypeError(
                f"Expected subclass of `{DataObject.__name__}` or `{type(self).__name__} instance` "
                "as first argument."
            )

    @property
    def cls(self) -> type[DataObject]:
        """Return the `DataObject` subclass this set is bound to."""
        return self._cls

    @property
    def mask(self) -> int:
        """Return the raw bitmask representing the set fields."""
        return self._mask

    @mask.setter
    def mask(self, mask: int, /) -> None:
        self._mask = self._validate_mask(mask)

    def invert(self) -> None:
        """Toggle all bits in place, swapping set and unset fields."""
        self._mask = self._get_inverted_mask()

    def to_inverted(self) -> Self:
        """Return a new `FieldsSet` with all bits toggled."""
        return self._remask(self._get_inverted_mask())

    def __invert__(self) -> Self:
        return self.to_inverted()

    def to_empty(self) -> Self:
        """Return a new `FieldsSet` with no fields set."""
        return self._remask(0)

    def fill(self) -> None:
        """Mark every field as set."""
        self._mask = self._get_filled_mask()

    def to_filled(self) -> Self:
        """Return a new `FieldsSet` with every field marked as set."""
        return self._remask(self._get_filled_mask())

    def is_full(self) -> bool:
        """Return `True` if every field on the bound class is set."""
        return self._mask == self._get_filled_mask()

    def is_empty(self) -> bool:
        """Return `True` if no fields are set."""
        return not self._mask

    @override
    def add(self, value: str) -> None:
        index = self._get_index(value)
        if index is not None:
            self._mask |= 1 << index

    @override
    def discard(self, value: str) -> None:
        self._clear_field(value)

    @override
    def clear(self) -> None:
        self._mask = 0

    @override
    def pop(self) -> str:
        mask = self._mask
        if not mask:
            raise KeyError("Pop from an empty fields set.")

        last = mask.bit_length() - 1
        field = self._cls.__data_object_field_names__[last]
        self._clear_index(last)
        return field

    @override
    def remove(self, value: str) -> None:
        if value not in self:
            raise KeyError(value)

        self._clear_field(value)

    @override
    def __ior__(self, it: Set[str]) -> Self:
        self._mask |= self._to_mask(it)
        return self

    @override
    def __iand__(self, it: Set[Any]) -> Self:
        self._mask &= self._to_mask(it)
        return self

    @override
    def __ixor__(self, it: Set[Any]) -> Self:
        self._mask ^= self._to_mask(it)
        return self

    @override
    def __isub__(self, it: Set[Any]) -> Self:
        self._mask &= ~self._to_mask(it)
        return self

    @override
    def __contains__(self, field: Any) -> bool:
        index = self._get_index(field)
        if index is None:
            return False

        return not not (self._mask & (1 << index))

    @override
    def __iter__(self) -> Iterator[str]:
        names = self._cls.__data_object_field_names__
        mask = self._mask
        # If the mask is full, just yield all the field names without doing any bit operations.
        if mask == self._get_filled_mask():
            yield from names
            return

        while mask:
            # Get the index of the least significant set bit.
            index = (mask & -mask).bit_length() - 1
            # Yield the field name corresponding to that index.
            yield names[index]
            # Zero out the least significant set bit.
            mask = mask & (mask - 1)

    @override
    def __len__(self) -> int:
        return self._mask.bit_count()

    def __bool__(self) -> bool:
        return not not self._mask

    def _get_filled_mask(self) -> int:
        return (1 << len(self._cls.__data_object_field_names__)) - 1

    def _get_inverted_mask(self) -> int:
        count = len(self._cls.__data_object_field_names__)
        return self._mask ^ 2**count - 1

    def _validate_mask(self, mask: int | object) -> int:
        # Ensure the mask is an `int`.
        if type(mask) is not int:
            if not isinstance(mask, int):
                raise TypeError("Fields set `mask` must be an integer.")
            # Subclasses are okay, but convert them to the normal type to avoid weirdness.
            mask = int(mask)

        # A negative mask is invalid, but out of politeness we'll just treat it as empty.
        if mask < 0:
            return 0
        # Zero out any bits that exceed the number of fields defined on the data object.
        return mask & self._get_filled_mask()

    @override
    def __le__(self, other: Set[Any]) -> bool:
        if len(self) > len(other):
            return False

        for field in self:
            if field not in other:
                return False

        return True

    @override
    def __lt__(self, other: Set[Any]) -> bool:
        if len(self) >= len(other):
            return False

        for field in self:
            if field not in other:
                return False

        return True

    @override
    def __gt__(self, other: Set[Any]) -> bool:
        return not self.__le__(other)

    @override
    def __ge__(self, other: Set[Any]) -> bool:
        return not self.__lt__(other)

    @override
    def __and__(self, other: Set[Any]) -> Self:
        return self._remask(self._mask & self._to_mask(other))

    @override
    def __or__(self, other: Set[str]) -> Self:  # type: ignore
        return self._remask(self._mask | self._to_mask(other))

    @override
    def __sub__(self, other: Set[Any]) -> Self:
        return self._remask(self._mask & ~self._to_mask(other))

    @override
    def __xor__(self, other: Set[Any]) -> Self:
        return self._remask(self._mask ^ self._to_mask(other))

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, set | frozenset | Set):
            return False

        return len(self) == len(other) and self._mask == self._to_mask(other)

    @override
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.cls.__name__}, {self.__str__()})"

    @override
    def __str__(self) -> str:
        return f"{{{', '.join(repr(current) for current in self)}}}"

    @override
    def isdisjoint(self, other: Iterable[Any]) -> bool:
        other = set(other)
        for value in other:
            if value in self:
                return False
        for field in self:
            if field in other:
                return False

        return True

    def copy(self) -> Self:
        """Return a shallow copy of this `FieldsSet`."""
        instance = object.__new__(self.__class__)
        instance._cls = self._cls
        instance._mask = self._mask
        return instance

    def __copy__(self) -> Self:
        return self.copy()

    def _remask(self, mask: int) -> Self:
        instance = object.__new__(self.__class__)
        instance._cls = self._cls
        instance._mask = mask
        return instance

    def _to_mask(self, other: Iterable[Any], /) -> int:
        if isinstance(other, FieldsSet) and other._cls is self._cls:
            return other._mask

        mask = 0
        for field in other:
            index = self._get_index(field)
            if index is not None:
                mask |= 1 << index

        return mask

    def _clear_index(self, index: int) -> None:
        self._mask &= ~(1 << index)

    def _clear_field(self, field: str) -> None:
        index = self._get_index(field)
        if index is not None:
            self._clear_index(index)

    def _get_index(self, field: str) -> int | None:
        return self._cls.__data_object_field_indexes__.get(field)

    @override
    def __getstate__(self) -> tuple[type[DataObject], int]:
        return (self._cls, self._mask)

    def __setstate__(self, state: tuple[type[DataObject], int]) -> None:
        self._cls, self._mask = state


assert issubclass(FieldsSet, Set)


if TYPE_CHECKING:

    class _DataObjectProtocols(PydanticDataclass, Dataclass, Protocol):
        pass
else:
    _DataObjectProtocols = object

if TYPE_CHECKING:
    from ceres.component import ConnectionField
else:
    ConnectionField = object

_FIELD_SPECIFIERS = (
    dataclasses.field,
    dataclasses.Field,
    Field,
    FieldInfo,
    PrivateAttr,
    ConnectionField,
)

_data_object_generic_alias_class_cache: dict[
    tuple[type[DataObject], Any | tuple[Any, ...]], Any
] = {}


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=_FIELD_SPECIFIERS,
)
class DataObject(
    _DataObjectProtocols,
    metaclass=DataObjectMetaclass,
    config=_DATA_OBJECT_DEFAULT_CONFIG,
):
    """Base class for validated, serializable data records in Ceres.

    `DataObject` combines Python's `dataclasses` with Pydantic's validation and
    serialization. Subclasses define typed fields as dataclass attributes, gain automatic
    validation on construction, JSON serialization, and fields-set tracking (knowing which
    fields were explicitly provided versus defaulted).

    Create subclasses by inheriting from `DataObject` and declaring fields as normal
    dataclass attributes. Use `slots=True` in the class keyword arguments for concrete
    classes to allocate per-field slots. Use `abstract=True` for base classes that should
    not be instantiated directly. Pass `frozen=True` (or inherit from `DataObject.Frozen`)
    for immutable instances.

    Instances can be constructed without validation using `construct()` or `create()` for
    pre-validated data, or with full Pydantic validation by calling the class directly.
    """

    __slots__ = ("__data_object_fields_set__",)

    if TYPE_CHECKING:
        # This isn't actually a field, but type-checking wise it behaves just like a non-init field
        # on a dataclass so we define this here anyway.
        __data_object_fields_set__: FieldsSet = dataclasses.field(
            init=False,
            repr=False,
            compare=False,
        )
        """Set of field names explicitly set during initialization or assigned afterward.

        Provide equivalent set/unset functionality to Pydantic's `BaseModel`.
        """

    else:

        @override
        def __setattr__(self, name: str, value: object, /) -> None:
            super().__setattr__(name, value)
            # If `__data_object_fields_set__` isn't assigned yet, then we're probably still
            # assigning regular attributes on the instance, and shouldn't consider assignments to
            # fields as "setting" them just yet.
            if hasattr(self, "__data_object_fields_set__"):
                # `FieldSet` ignores insertions of fields which aren't actually in the data object
                # class so we don't need to check for that here.
                self.__data_object_fields_set__.add(name)

    if TYPE_CHECKING:
        from ceres.data.object import __Frozen__ as __Frozen

        @dataclass_transform(
            kw_only_default=True,
            frozen_default=True,
            field_specifiers=_FIELD_SPECIFIERS,
        )
        class Frozen(__Frozen, frozen=True):
            __slots__ = ()
    else:

        @class_property
        @classmethod
        def Frozen(cls) -> type[DataObject]:
            return __Frozen__

    __data_object_abstract__: ClassVar[bool] = False
    __data_object_required_slots__: ClassVar[tuple[str, ...]] = ()
    __data_object_generic_alias__: ClassVar[GenericAlias | None] = None

    if TYPE_CHECKING:
        from ceres.data.object import DataObject as __DataObject

        __data_object_class__: ClassVar[type[DataObject]] = __DataObject

        # Standard dataclass class attributes.
        __dataclass_fields__: ClassVar[dict[str, Any]]
        __dataclass_params__: ClassVar[Any]

        # Pydantic dataclass class attributes.
        __signature__: ClassVar[Signature]
        __pydantic_config__: ClassVar[ConfigDict]
        __pydantic_complete__: ClassVar[bool]
        __pydantic_core_schema__: ClassVar[CoreSchema]
        __pydantic_decorators__: ClassVar[DecoratorInfos]
        __pydantic_fields__: ClassVar[dict[str, FieldInfo]]
        __pydantic_serializer__: ClassVar[SchemaSerializer]
        __pydantic_validator__: ClassVar[SchemaValidator]

        @override
        @classmethod
        def __pydantic_fields_complete__(cls) -> bool: ...

        def __init__(self, *args: Any, **kwargs: Any) -> None: ...

    def __class_getitem__(cls, __args__: Any | tuple[Any, ...], /) -> type[Self]:
        key = (cls, __args__)
        cached = _data_object_generic_alias_class_cache.get(key)
        if cached is not None:
            return cached

        if TYPE_CHECKING:
            BaseAlias: GenericAlias = cast("GenericAlias", None)
        else:
            BaseAlias = super().__class_getitem__(__args__)

        if not isinstance(__args__, tuple):
            __args__ = (__args__,)

        from pydantic._internal._generics import replace_types

        __parameters__: tuple[TypeVar, ...] = getattr(cls, "__parameters__", ())
        replace = {parameter: argument for parameter, argument in zip(__parameters__, __args__)}
        replaced_annotations: dict[str, Any] = {}
        replaced_fields: dict[str, FieldInfo] = {}

        for field, info in cls.__data_object_fields__.items():
            replaced = replace_types(info.annotation, replace)
            if info.annotation != replaced:
                info = info._copy()
                info.annotation = replaced
                replaced_annotations[field] = replaced
                replaced_fields[field] = info

        argument_names: list[str] = []
        for argument in __args__:
            argument_name = getattr(argument, "__qualname__", None)
            if argument_name is None:
                argument_name = getattr(argument, "__name__", None)
            if argument_name is None:
                argument_name = repr(argument)

            argument_names.append(argument_name)

        arguments = ", ".join(argument_names)
        __qualname__ = f"{cls.__qualname__}[{arguments}]"
        __name__ = f"{cls.__name__}[{arguments}]"

        class Alias(BaseAlias if not TYPE_CHECKING else DataObject):
            __annotations__ = replaced_annotations
            __data_object_generic_alias__ = BaseAlias
            for field, info in replaced_fields.items():
                locals()[field] = info

        Alias.__module__ = cls.__module__
        Alias.__qualname__ = __qualname__
        Alias.__name__ = __name__

        # Set generic alias attributes.
        setattr(Alias, "__origin__", cls)
        setattr(Alias, "__args__", BaseAlias.__args__)
        setattr(Alias, "__parameters__", BaseAlias.__parameters__)

        return _data_object_generic_alias_class_cache.setdefault(key, Alias)

    @class_property
    @classmethod
    def __data_object_config__(cls) -> DataObjectConfigDict:
        return cls.__pydantic_config__

    @class_property
    @classmethod
    def __data_object_parameter_fields__(cls) -> Mapping[str, FieldInfo]:
        return cls.__pydantic_fields__

    @fields_cached_class_property
    @classmethod
    def __data_object_fields__(cls) -> Mapping[str, FieldInfo]:
        return MappingProxyType(
            {field: info for field, info in cls.__pydantic_fields__.items() if not info.init_var}
        )

    @fields_cached_class_property
    @classmethod
    def __data_object_init_var_fields__(cls) -> Mapping[str, FieldInfo]:
        return MappingProxyType(
            {field: info for field, info in cls.__pydantic_fields__.items() if info.init_var}
        )

    @fields_cached_class_property
    @classmethod
    def __data_object_computed_fields__(cls) -> Mapping[str, ComputedFieldInfo]:
        return computed_fields_of(cls, cache=False)

    @fields_cached_class_property
    @classmethod
    def __data_object_field_indexes__(cls) -> Mapping[str, int]:
        return {field: index for index, field in enumerate(cls.__data_object_fields__)}

    @fields_cached_class_property
    @classmethod
    def __data_object_field_names__(cls) -> tuple[str, ...]:
        return tuple(cls.__data_object_fields__)

    @fields_cached_class_property
    @classmethod
    def __data_object_type_adapter__(cls) -> TypeAdapter[Self]:
        return TypeAdapter(cls)

    @cached_class_property
    @classmethod
    def __data_object_positional_parameters__(cls) -> tuple[str, ...]:
        from inspect import Parameter

        return tuple(
            [
                parameter.name
                for parameter in cls.__signature__.parameters.values()
                if parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
                and parameter.name in cls.__pydantic_fields__
            ]
        )

    @cached_class_property
    @classmethod
    def __data_object_defined_slots__(cls) -> tuple[str, ...]:
        return tuple(
            slot
            for slot in get_declared_slots(cls)
            if slot not in ("__weakref__", "__dict__", "__data_object_fields_set__")
        )

    @classmethod
    def __data_object_create__(
        cls,
        field_values: Mapping[str, Any],
        fields_set: Iterable[str] | int | bool | None = None,
        /,
    ) -> Self:
        instance = object.__new__(cls)

        __post_init__args: list[Any] = []

        for field, info in cls.__data_object_parameter_fields__.items():
            value = field_values.get(field, Undefined)
            if value is Undefined:
                if info.is_required():
                    raise AttributeError(f"Missing value for required field '{field}'.")

                value = info.get_default(
                    call_default_factory=True,
                    validated_data=field_values,  # type: ignore
                )

            if info.init_var:
                __post_init__args.append(value)
            else:
                _object_setattr(instance, field, value)

        if fields_set is None:
            fields_set = FieldsSet(cls, field_values)
        else:
            fields_set = FieldsSet(cls, fields_set)

        _object_setattr(instance, "__data_object_fields_set__", fields_set)

        if hasattr(cls, "__post_init__"):
            cls.__post_init__(*__post_init__args)  # type: ignore

        return instance

    @classmethod
    def __data_object_construct__(cls, *args: Any, **kwargs: Any) -> Self:
        kwargs = cls.__data_object_resolve_args_kwargs__(args, kwargs, True)
        return cls.__data_object_create__(kwargs)

    @classmethod
    @overload
    def __data_object_resolve_args_kwargs__(cls, args: ArgsKwargs) -> dict[str, Any]: ...

    @classmethod
    @overload
    def __data_object_resolve_args_kwargs__(
        cls,
        args: Iterable[str] | None,
        kwargs: dict[str, Any] | None = None,
        in_place: bool = False,
    ) -> dict[str, Any]: ...

    @classmethod
    def __data_object_resolve_args_kwargs__(
        cls,
        args: Iterable[str] | ArgsKwargs | None,
        kwargs: dict[str, Any] | None = None,
        in_place: bool = False,
    ) -> dict[str, Any]:
        if isinstance(args, ArgsKwargs):
            if kwargs:
                raise ValueError(
                    "Cannot specify both `args` and `kwargs` when `args` is an `ArgsKwargs` instance."
                )

            kwargs = args.kwargs
            args = args.args

        if kwargs is None:
            kwargs = {}
        if not in_place:
            kwargs = {**kwargs}
        if not args:
            return kwargs

        for name, value in zip(cls.__data_object_positional_parameters__, args):
            kwargs[name] = value

        return kwargs

    @class_property
    @classmethod
    def Model(cls) -> type[DataModel]:
        return cls.__data_object_model_class__

    @cached_class_property
    @classmethod
    def __data_object_model_class__(cls) -> type[DataModel]:
        return cls.__data_object_create_model_class__()

    @classmethod
    def __data_object_create_model_class__(cls, name: str | None = None) -> type[DataModel]:
        if name is None:
            name = f"{cls.__name__}.Model"
            __qualname__ = name
        else:
            __qualname__ = None

        try:
            bases: tuple[type[Any], ...] = tuple(
                [
                    *(
                        base.__data_object_model_class__
                        for base in cls.__bases__
                        if issubclass(base, DataObject)
                        and base not in (object, DataObject, __Frozen__)
                    )
                ]
            )
        except NameError:
            bases = ()

        if not any(base for base in bases if issubclass(base, DataModel)):
            bases = tuple([DataModel, *bases])

        def get_copied_validator(name: str) -> Any:
            for current in cls.__mro__:
                if _is_data_object_class_defined and current is DataObject:
                    break

                value = current.__dict__.get(name, PydanticUndefined)
                if value is not PydanticUndefined:
                    return value

            return None

        decorator_descriptors: dict[str, Any] = {}
        for decorator_name, decorator in _decorators_of(cls):
            function = get_copied_validator(decorator_name)
            if function is None:
                continue

            from pydantic._internal._decorators import PydanticDescriptorProxy

            descriptor = PydanticDescriptorProxy(function, decorator.info)
            decorator_descriptors[decorator_name] = descriptor

        namespace = {
            "model_config": {**cls.__pydantic_config__},
            "__annotations__": {
                field_name: field.annotation
                for field_name, field in cls.__pydantic_fields__.items()
                if field.annotation is not None
            },
            **{name: field for name, field in cls.__pydantic_fields__.items()},
            **{name: descriptor for name, descriptor in decorator_descriptors.items()},
        }

        ModelMetaclass: Any = type(BaseModel)
        Model: type[DataModel] = ModelMetaclass(name, bases, namespace)
        Model.__data_object_class__ = cls
        Model.__qualname__ = __qualname__ or name
        Model.__module__ = cls.__module__
        Model.__doc__ = cls.__doc__

        return Model

    @override
    def __repr__(self) -> str:
        fields = self.__data_object_fields__
        fields_set = self.__data_object_fields_set__

        tokens = [self.__class__.__name__, "("]

        for field, info in fields.items():
            if not info.repr:
                continue

            value = getattr(self, field, Undefined)
            # Omit fields which inexplicably unset in attributes.
            if value is Undefined:
                continue

            if (
                not info.is_required()
                and value is info.default
                and (value is None or value is MISSING)
                and field not in fields_set
            ):
                continue

            tokens.append(field)
            tokens.append("=")
            tokens.append(repr(value))
            tokens.append(", ")

        if tokens[-1] == ", ":
            tokens[-1] = ")"
        else:
            tokens.append(")")

        return "".join(tokens)

    @override
    def __str__(self) -> str:
        return self.__repr__()

    def __copy__(self) -> Self:
        return self.__data_object_create__(
            {field: getattr(self, field) for field in self.__data_object_fields__},
            self.__data_object_fields_set__.mask,
        )

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        return self.__data_object_create__(
            {field: deepcopy(getattr(self, field), memo) for field in self.__data_object_fields__},
            self.__data_object_fields_set__.mask,
        )

    # The `__replace__` method is special-cased by some type-checkers, where for
    # dataclass-transformed classes the keyword arguments of `__replace__` will match that of
    # `__init__`, so hide this from type-checkers to preserve that behavior.
    if not TYPE_CHECKING:

        def __replace__(self, **changes: Any) -> Self:
            fields_set = self.__data_object_fields_set__.copy()
            fields_set |= changes.keys()

            field_values = changes
            for field, value in to_items(self):
                field_values.setdefault(field, value)

            copy = self.__class__(**field_values)
            copy.__data_object_fields_set__ = fields_set
            return copy

    def __iter__(self) -> Iterator[tuple[str, Any]]:
        for field in self.__data_object_fields__:
            value = getattr(self, field, Undefined)
            if value is not Undefined:
                yield field, value

    def __contains__(self, field: object, /) -> bool:
        return field in self.__data_object_fields_set__

    def __data_object_to_model__(self, *, revalidate: bool = False) -> DataModel:
        Model = self.__class__.Model
        __dict__ = to_dict(self)
        __pydantic_fields_set__ = set(self.__data_object_fields_set__)
        if revalidate:
            model = Model.model_validate(__dict__)
            model.__pydantic_fields_set__ = __pydantic_fields_set__
        else:
            model = Model.model_construct(__pydantic_fields_set__, **__dict__)

        return model

    def __init_subclass__(cls, **kwargs: Any) -> None:
        try:
            super().__init_subclass__(**kwargs)
        except TypeError:
            super().__init_subclass__()

    @classmethod
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        pass

    @property
    def __fields_set__(self) -> FieldsSet:
        return self.__data_object_fields_set__

    @property
    def __pydantic_fields_set__(self) -> FieldsSet:
        return self.__data_object_fields_set__

    @__pydantic_fields_set__.setter
    def __pydantic_fields_set__(self, value: Set[str]) -> None:
        self.__data_object_fields_set__ = FieldsSet(self.__class__, value)

    @model_serializer(mode="wrap")
    def __serialize_data_object__(
        self,
        handler: ModelWrapValidatorHandler,
        info: SerializationInfo,
        /,
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if info.exclude_unset:
            __data_object_fields_set__ = self.__data_object_fields_set__
            if not __data_object_fields_set__.is_full():
                for field in ~__data_object_fields_set__:
                    data.pop(field, None)

        return data

    @model_validator(mode="wrap")
    @classmethod
    def __validate_data_object__(
        cls,
        data: object,
        handler: ModelWrapValidatorHandler[Self],
        /,
    ) -> DataObject:
        # Workaround for `cls` being incorrect in Pydantic dataclasses with slots.
        cls = cls.__data_object_class__
        if cls.__data_object_abstract__:
            raise DataObjectAbstract(
                f"Cannot instantiate abstract `{DataObject.__name__}` subclass `{cls}`."
            )

        self = handler(data)
        if not hasattr(self, "__data_object_fields_set__"):
            if isinstance(data, (dict, ArgsKwargs)):
                __data_object_fields_set__ = cls.__data_object_compute_fields_set__(data)
            else:
                __pydantic_fields_set__: Set[str] | None = getattr(
                    data,
                    "__pydantic_fields_set__",
                    None,
                )
                if __pydantic_fields_set__ is not None:
                    __data_object_fields_set__ = FieldsSet(cls, __pydantic_fields_set__)
                else:
                    __data_object_fields_set__ = FieldsSet(cls, cls.__data_object_fields__)

            _object_setattr(self, "__data_object_fields_set__", __data_object_fields_set__)

        return self

    @classmethod
    def __data_object_compute_fields_set__(
        cls,
        data: dict[str, Any] | ArgsKwargs,
        /,
    ) -> FieldsSet:
        # Workaround for `cls` being incorrect in Pydantic dataclasses with slots.
        cls: type[DataObject] = cls.__data_object_class__
        if isinstance(data, ArgsKwargs):
            data = cls.__data_object_resolve_args_kwargs__(data)

        fields_set = FieldsSet(cls)
        for name, field in cls.__data_object_fields__.items():
            # Check if the field name itself is in the data.
            if name in data:
                fields_set.add(name)
                continue

            if field.alias is not None and field.alias in data:
                fields_set.add(name)
                continue

            if field.validation_alias is not None:
                aliases: Sequence[str | AliasPath] = (
                    field.validation_alias.choices
                    if isinstance(field.validation_alias, AliasChoices)
                    else (field.validation_alias,)
                )

                for alias in aliases:
                    if isinstance(alias, str) and alias in data:
                        fields_set.add(name)
                        break

                    if isinstance(alias, AliasPath):
                        value = alias.search_dict_for_path(cast("dict[str, Any]", data))
                        if value is not PydanticUndefined:
                            fields_set.add(name)
                            break

        return fields_set

    @override
    def __getstate__(self) -> tuple[Sequence[Any], int]:
        return (
            [getattr(self, field) for field in self.__data_object_fields__],
            self.__data_object_fields_set__.mask,
        )

    def __setstate__(self, state: tuple[Sequence[Any], int], /) -> None:
        values, mask = state
        for field, value in zip(self.__data_object_fields__, values):
            _object_setattr(self, field, value)

        fields_set = object.__new__(FieldsSet)
        fields_set._cls = self.__class__
        fields_set._mask = mask
        _object_setattr(self, "__data_object_fields_set__", fields_set)


_is_data_object_class_defined = True

if TYPE_CHECKING:
    DataObject()  # Ensure class meets abstract class requirements.

DataObject.__dataclass_params__.frozen = True


class __Frozen__(DataObject, frozen=True):
    __slots__ = ()


__Frozen__.__name__ = "Frozen"
__Frozen__.__qualname__ = f"{DataObject.__name__}.{__Frozen__.__name__}"

DataObject.__dataclass_params__.frozen = None
_is_data_object_frozen_class_defined = True


@overload
def _is_data_object(obj: type, /) -> TypeIs[type[DataObject]]: ...  # type: ignore
@overload
def _is_data_object(obj: object, /) -> TypeIs[MaybeClass[DataObject]]: ...
def _is_data_object(obj: object, /) -> bool:
    return hasattr(obj, "__data_object_fields__")


def _is_data_object_type(obj: object, /) -> TypeIs[type[DataObject]]:
    return isinstance(obj, type) and hasattr(obj, "__data_object_fields__")


def to_kwargs[T: classmethod | Callable[..., Any]](method: T) -> T:
    """Decorator that converts an `ArgsKwargs` first argument into keyword arguments.

    When the wrapped method receives an `ArgsKwargs` instance as its first positional
    argument, the decorator resolves it into a keyword dictionary using the class's
    positional parameter mapping before forwarding the call.

    Args:
        method: A classmethod or callable to wrap.

    Returns:
        The wrapped method with automatic `ArgsKwargs` resolution.
    """
    if isinstance(method, classmethod):
        function = method.__func__
    else:
        function = method

    @wraps(function)
    def wrapper(cls, *args, **kwargs):
        if TYPE_CHECKING:
            assert issubclass(cls, DataObject)

        if args:
            first = args[0]
            if isinstance(first, ArgsKwargs):
                first = cls.__data_object_resolve_args_kwargs__(first)
                args = (first, *args[1:])

        return function(cls, *args, **kwargs)

    if isinstance(method, classmethod):
        wrapper = classmethod(wrapper)  # type: ignore

    return wrapper  # type: ignore


class DataModel(BaseModel):
    """Pydantic `BaseModel` mirror of a `DataObject`, generated for each concrete subclass.

    Access a `DataObject`'s corresponding model class via `MyDataObject.Model`. The model
    shares the same fields, validators, and config as the originating `DataObject` but
    inherits from `BaseModel` so it can be used in contexts that require a model instance
    (for example, OpenAPI schema generation).
    """

    model_config = {**_DATA_OBJECT_DEFAULT_CONFIG}

    __data_object_class__: ClassVar[type[DataObject] | None] = None
    """The `DataObject` subclass this model was generated from, or `None` for the base."""

    if TYPE_CHECKING:

        def __init__(self, **data: Any) -> None: ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        try:
            super().__init_subclass__(**kwargs)
        except Exception:
            super().__init_subclass__()


def __proxy_data_object_class_item(
    item: Callable[..., Any] | classmethod | ClassProperty,
) -> Callable[..., Any] | ClassProperty:
    if isinstance(item, ClassProperty):
        proxy = ClassProperty[DataModel, Any](
            lambda cls: getattr(cls.__data_object_class__, item.__name__)
        )
        proxy.__name__ = item.__name__
        proxy.__doc__ = item.__doc__
        return proxy

    if isinstance(item, classmethod):
        function = item.__func__
    else:
        function = item

    @classmethod
    @wraps(function)
    def wrapper(cls: type[DataModel], *args, **kwargs):
        assert cls.__data_object_class__ is not None
        return function(cls.__data_object_class__, *args, **kwargs)

    return wrapper


for attribute, value in DataObject.__dict__.items():
    if attribute.startswith("__data_object_") and isinstance(value, (classmethod, ClassProperty)):
        setattr(DataModel, attribute, __proxy_data_object_class_item(value))


if TYPE_CHECKING:
    # This is just to ensure that `ValidatedDataclass` is recognized as a valid Pydantic dataclass
    # type for type checking purposes without actually inheriting from `typing.Protocol` which
    # inherits from `typing.Generic` and causes issues with `dataclasses.dataclass`.
    __ensure_is_pydantic_dataclass: type[PydanticDataclass] = DataObject


def create[T: DataObject | BaseModel](
    cls: type[T],
    field_values: Mapping[str, Any],
    fields_set: Iterable[str] | bool | None = None,
    /,
) -> T:
    """Construct an instance of `cls` with provided field values, skipping validation.

    Args:
        cls: The `DataObject` or `BaseModel` subclass to instantiate.
        field_values: A mapping of field names to pre-validated values.
        fields_set: Fields to mark as explicitly set. Can be an iterable of field
            names, `True` to mark all fields as set, `False` to mark no fields as
            set, or `None` to infer set fields from `field_values`.

    Returns:
        An instance of the specified class with the provided field values.

    Raises:
        ValueError: If `cls` is not a subclass of `DataObject` or `BaseModel`, or if
            a required field value is missing from `field_values`.
    """
    instance: DataObject | BaseModel | None = None

    if isinstance(cls, type):
        if _is_data_object(cls):
            instance = cls.__data_object_create__(field_values, fields_set)
        elif issubclass(cls, BaseModel):
            if fields_set is not None and not isinstance(fields_set, set):
                if isinstance(fields_set, bool):
                    fields_set = set(cls.__pydantic_fields__) if fields_set else set()
                else:
                    fields_set = set(fields_set)

            instance = cls.model_construct(fields_set, **field_values)

    if instance is None:
        raise ValueError(
            f"`create` can only be used with subclasses of {DataObject.__name__} or "
            f"{BaseModel.__name__}, got {_as_class(cls)}."
        )

    return instance  # type: ignore


def construct[T: DataObject | BaseModel, **P](
    cls: Callable[P, T],
    /,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Construct an instance of `cls` with the provided arguments, skipping validation.

    Args:
        cls: The `DataObject` or `BaseModel` subclass to construct.
        *args: Positional arguments to pass to the constructor.
        **kwargs: Keyword arguments to pass to the constructor.

    Returns:
        An instance of `cls` constructed with the provided arguments.

    Raises:
        ValueError: If `cls` is not a subclass of `DataObject` or `BaseModel`, a required
            field is missing, or positional arguments are passed to a `BaseModel` subclass.
    """
    instance: DataObject | BaseModel | None = None

    if isinstance(cls, type):
        if _is_data_object_type(cls):
            instance = cls.__data_object_construct__(*args, **kwargs)
        elif isinstance(cls, type) and issubclass(cls, BaseModel):
            if args:
                raise ValueError(
                    f"cannot construct `BaseModel` subclass `{cls}` with positional arguments"
                )
            instance = cls.model_construct(**kwargs)

    if instance is None:
        raise ValueError(
            f"`construct` can only be used with subclasses of {DataObject.__name__} or "
            f"{BaseModel.__name__}, got {_as_class(cls)}."
        )

    return instance  # type: ignore
