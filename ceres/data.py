import dataclasses
from abc import ABCMeta
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSet,
    Sequence,
    Set,
)
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum as BaseStrEnum
from functools import wraps
from re import RegexFlag
from types import FunctionType, GenericAlias, MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Final,
    Literal,
    NewType,
    Protocol,
    Self,
    TypeAlias,
    TypedDict,
    TypeIs,
    Unpack,
    cast,
    dataclass_transform,
    final,
    overload,
    override,
)
from uuid import UUID
from warnings import warn
from weakref import WeakKeyDictionary

import pydantic
from pydantic import (
    AfterValidator,
    AliasGenerator,
    AliasPath,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PlainSerializer,
    PrivateAttr,
    SerializationInfo,
    StringConstraints,
    TypeAdapter,
    model_serializer,
    model_validator,
)
from pydantic.aliases import AliasChoices
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic_core import (
    ArgsKwargs,
    CoreSchema,
    PydanticUndefined,
    SchemaSerializer,
    SchemaValidator,
)
from pydantic_extra_types.color import Color as Color
from pydantic_settings import NoDecode
from typing_extensions import TypeForm

from ceres._internal import util
from ceres._internal.util import (
    NAME_PATTERN,
    ClassProperty,
    Undefined,
    cached,
    cached_class_property,
    class_property,
    declared_slots_of,
    uniquify,
)

if TYPE_CHECKING:
    from inspect import Signature
    from types import CellType

    from pydantic._internal._decorators import Decorator, DecoratorInfos
    from pydantic.config import ExtraValues
    from pydantic.main import IncEx

if TYPE_CHECKING:
    from typing import _SpecialForm
else:
    type _SpecialForm = Any


type TypeInput[T = Any] = (
    type[T] | TypeForm[T] | UnionType | GenericAlias | FunctionType | _SpecialForm
)
type MaybeClass[T] = T | type[T]

_cached_class_type_adapters = WeakKeyDictionary[type, TypeAdapter[type]]()
_cached_type_form_type_adapters = dict[Any, TypeAdapter[Any]]()
_cached_dataclasses = WeakKeyDictionary[type, type["PydanticDataclass"]]()
_cached_fields = WeakKeyDictionary[type, Mapping[str, FieldInfo]]()
_cached_init_fields = WeakKeyDictionary[type, Mapping[str, FieldInfo]]()
_cached_computed_fields = WeakKeyDictionary[type, Mapping[str, ComputedFieldInfo]]()


@overload
def _is_dataclass(obj: type, /) -> TypeIs[type[Dataclass]]: ...
@overload
def _is_dataclass(obj: object, /) -> TypeIs[MaybeClass[Dataclass]]: ...
def _is_dataclass(obj: object, /) -> TypeIs[MaybeClass[Dataclass]]:
    return dataclasses.is_dataclass(obj)


def _supports_pydantic_fields(obj: object, /) -> TypeIs[MaybeClass[SupportsPydanticFields]]:
    return hasattr(obj, "__pydantic_fields__")


def _supports_fields_set(obj: object, /) -> TypeIs[SupportsPydanticFieldsSet]:
    return hasattr(obj, "__pydantic_fields_set__")


@cached(storage=_cached_dataclasses)
def _as_pydantic_dataclass(cls: type[Dataclass]) -> type[PydanticDataclass]:
    if pydantic.dataclasses.is_pydantic_dataclass(cls):
        return cls

    return pydantic.dataclasses.dataclass(cls, config={"arbitrary_types_allowed": True})


def _as_class[T](obj: MaybeClass[T]) -> type[T]:
    return obj if isinstance(obj, type) else type(obj)


def _decorators_of(cls: type[PydanticDataclass]) -> Iterable[tuple[str, Decorator]]:
    for _, decorators in items_of(cls.__pydantic_decorators__):
        if isinstance(decorators, Mapping):
            yield from decorators.items()


def adapt[T](
    ty: TypeInput[T],
    /,
    *,
    _namespace: int = 3,
) -> TypeAdapter[T]:
    key = cast("Any", ty)
    cache: MutableMapping[Any, Any]
    if isinstance(ty, type):
        cache = _cached_class_type_adapters
    else:
        cache = _cached_type_form_type_adapters

    adapter = cache.get(key)
    if adapter is None:
        adapter = TypeAdapter(ty, _parent_depth=_namespace)
        adapter = cache.setdefault(key, adapter)

    return cast("TypeAdapter[T]", adapter)


def to_dict(
    obj: Dataclass | BaseModel,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    exclude_unset: bool = False,
    exclude_computed_fields: bool = True,
) -> dict[str, Any]:
    return dict(
        items_of(
            obj,
            include=include,
            exclude=exclude,
            exclude_unset=exclude_unset,
            exclude_computed_fields=exclude_computed_fields,
        )
    )


class DumpKwargs(TypedDict, total=False):
    mode: Literal["json", "python"]
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool | None
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    exclude_computed_fields: bool
    round_trip: bool
    warnings: bool | Literal["none", "warn", "error"]
    fallback: Callable[[Any], Any] | None
    serialize_as_any: bool
    context: Any | None


def dump(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[DumpKwargs],
) -> Any:
    if as_type is None:
        as_type = type(obj)

    return adapt(as_type, _namespace=_namespace).dump_python(obj, **kwargs)


class ToJSONKwargs(TypedDict, total=False):
    indent: int | None
    ensure_ascii: bool
    include: IncEx | None
    exclude: IncEx | None
    by_alias: bool | None
    exclude_unset: bool
    exclude_defaults: bool
    exclude_none: bool
    exclude_computed_fields: bool
    round_trip: bool
    warnings: bool | Literal["none", "warn", "error"]
    fallback: Callable[[Any], Any] | None
    serialize_as_any: bool
    context: Any | None
    indent: int | None


def to_json(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ToJSONKwargs],
) -> str:
    if as_type is None:
        as_type = type(obj)

    return adapt(as_type, _namespace=_namespace).dump_json(obj, **kwargs).decode()


class ToYAMLKwargs(ToJSONKwargs):
    pass


def to_yaml(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    _namespace: int = -5,
    **kwargs: Unpack[ToYAMLKwargs],
) -> str:
    import yaml

    return yaml.safe_dump(
        simplify(obj, as_type, _namespace=_namespace, **kwargs),
        indent=kwargs.get("indent", None),
    )


class SimplifyKwargs(ToJSONKwargs):
    pass


def simplify(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[SimplifyKwargs],
) -> Any:
    import json

    return json.loads(to_json(obj, as_type, _namespace=_namespace, **kwargs))


class ValidateKwargs(TypedDict, total=False):
    from_attributes: bool | None
    strict: bool | None
    extra: ExtraValues | None
    from_attributes: bool | None
    context: Any | None
    experimental_allow_partial: bool | Literal["off", "on", "trailing-strings"]
    by_alias: bool | None
    by_name: bool | None


def validate[T](
    data: Any,
    as_type: TypeInput[T],
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ValidateKwargs],
) -> Any:
    return adapt(as_type, _namespace=_namespace).validate_python(data, **kwargs)


class ValidateJSONKwargs(TypedDict, total=False):
    strict: bool | None
    extra: ExtraValues | None
    experimental_allow_partial: bool | Literal["off", "on", "trailing-strings"]
    context: Any | None
    by_alias: bool | None
    by_name: bool | None


def validate_json[T](
    data: str,
    as_type: TypeInput[T],
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ValidateJSONKwargs],
) -> T:
    return adapt(as_type, _namespace=_namespace).validate_json(data, **kwargs)


class ValidateYAMLKwargs(ValidateJSONKwargs, total=False):
    pass


def validate_yaml[T](
    data: str,
    as_type: TypeInput[T],
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ValidateYAMLKwargs],
) -> T:
    import json

    try:
        parsed = json.loads(data)
    except Exception:
        import yaml

        parsed = yaml.safe_load(data)

    return validate(parsed, as_type, _namespace=_namespace, **kwargs)


if TYPE_CHECKING:
    from _typeshed import DataclassInstance as __DataclassInstance

    class Dataclass(__DataclassInstance, Protocol):
        __slots__ = ()

    from pydantic._internal._dataclasses import PydanticDataclass as __PydanticDataclass

    class PydanticDataclass(__PydanticDataclass, Protocol):
        __slots__ = ()

    class SupportsPydanticFields(Protocol):
        if TYPE_CHECKING:
            __pydantic_fields__: ClassVar[dict[str, FieldInfo]]

    class SupportsPydanticFieldsSet(SupportsPydanticFields, Protocol):
        @property
        def __pydantic_fields_set__(self) -> Set[str]: ...
else:

    class Dataclass:
        __slots__ = ()

    class PydanticDataclass:
        __slots__ = ()


def fields_of(
    obj: MaybeClass[Dataclass | BaseModel],
    /,
    init: bool = False,
    cache: bool = True,
) -> Mapping[str, FieldInfo]:
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
    obj: MaybeClass[Dataclass | BaseModel],
    /,
    *,
    cache: bool = True,
) -> Mapping[str, ComputedFieldInfo]:
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


def items_of(
    obj: Dataclass | BaseModel,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    exclude_unset: bool = False,
    exclude_computed_fields: bool = True,
) -> Iterator[tuple[str, Any]]:
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


def fields_set_on(obj: SupportsPydanticFieldsSet, /) -> Set[str]:
    try:
        return obj.__pydantic_fields_set__
    except AttributeError:
        raise TypeError(f"Unsupported type for `{fields_set_on.__name__}`: {type(obj)}")


def _generate_validation_aliases(field: str) -> str | AliasChoices:
    if "_" not in field:
        return field

    return AliasChoices(field, field.replace("_", "-"))


_DATA_OBJECT_ALIAS_GENERATOR = AliasGenerator(
    validation_alias=_generate_validation_aliases,
)

_DATA_OBJECT_DEFAULT_CONFIG = ConfigDict(
    extra="forbid",
    from_attributes=True,
    use_attribute_docstrings=True,
    alias_generator=_DATA_OBJECT_ALIAS_GENERATOR,
    validate_by_name=True,
    validate_by_alias=True,
)


def _patch_dataclass_fields() -> None:
    try:
        _original_as_dataclass_field: Any = pydantic._internal._dataclasses.as_dataclass_field  # type: ignore
    except AttributeError:
        _original_as_dataclass_field = None

    if _original_as_dataclass_field is not None:

        def overridden_as_dataclass_field(pydantic_field: FieldInfo) -> dataclasses.Field[Any]:
            field = _original_as_dataclass_field(pydantic_field)
            if pydantic_field.kw_only is not None:
                field.kw_only = pydantic_field.kw_only

            return field

        pydantic._internal._dataclasses.as_dataclass_field = overridden_as_dataclass_field  # type: ignore


_patch_dataclass_fields()

if TYPE_CHECKING:
    from ceres.component import ConnectionField
else:
    ConnectionField = object


_data_object_classes_being_built: set[Any] = set()


class DataObjectClassInvalid(TypeError):
    pass


class DataObjectAbstract(RuntimeError):
    pass


class DataModel(BaseModel):
    model_config = {**_DATA_OBJECT_DEFAULT_CONFIG}

    __data_object_origin__: ClassVar[type[DataObject]]

    if TYPE_CHECKING:

        def __init__(self, **data: Any) -> None: ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        try:
            super().__init_subclass__(**kwargs)
        except Exception:
            super().__init_subclass__()


_is_data_object_class_defined = False
_is_data_object_frozen_class_defined = False


class _Empty:
    pass


class DataObjectMetaclass(
    type(Protocol) if not TYPE_CHECKING else _Empty,
    ABCMeta,
):
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
            bases = tuple(uniquify((__Frozen__ if base is DataObject else base) for base in bases))
            # Ensure `FrozenDataObject` is in the bases if no subclass of it is already.
            if not any(issubclass(base, __Frozen__) for base in bases):
                bases = tuple((__Frozen__, *bases))

        inner_class = super().__new__(mcs, name, bases, namespace, **kwargs)
        key = (inner_class.__module__, name)
        if key in _data_object_classes_being_built:
            return inner_class

        # Collect inherited Pydantic config from base classes with `__pydantic_config__` defined.
        inherited = ConfigDict()
        for base in reversed(bases):
            current: ConfigDict | None = getattr(base, "__pydantic_config__", None)
            if current:
                inherited.update(current)

        config: ConfigDict = {
            **inherited,
            "title": inner_class.__qualname__,
            **(config or {}),
        }

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
            uniquify(__data_object_required_slots__)
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

        return data_object_class


@final
class FieldsSet(MutableSet[str]):
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
            return
        else:
            raise TypeError(
                f"Expected subclass of `{DataObject.__name__}` or `{type(self).__name__} instance` "
                "as first argument."
            )

    @property
    def cls(self) -> type[DataObject]:
        return self._cls

    @property
    def mask(self) -> int:
        return self._mask

    @mask.setter
    def mask(self, mask: int, /) -> None:
        self._mask = self._validate_mask(mask)

    def invert(self) -> None:
        self._mask = self._get_inverted_mask()

    def to_inverted(self) -> Self:
        return self._remask(self._get_inverted_mask())

    def __invert__(self) -> Self:
        return self.to_inverted()

    def to_empty(self) -> Self:
        return self._remask(0)

    def fill(self) -> None:
        self._mask = self._get_filled_mask()

    def to_filled(self) -> Self:
        return self._remask(self._get_filled_mask())

    def is_full(self) -> bool:
        return self._mask == self._get_filled_mask()

    def is_empty(self) -> bool:
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


assert issubclass(FieldsSet, Set)


if TYPE_CHECKING:

    class _DataObjectProtocols(PydanticDataclass, Dataclass, Protocol):
        pass
else:
    _DataObjectProtocols = object

_FIELD_SPECIFIERS = (
    dataclasses.field,
    dataclasses.Field,
    Field,
    FieldInfo,
    PrivateAttr,
    ConnectionField,
)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=_FIELD_SPECIFIERS,
)
class DataObject(
    _DataObjectProtocols,
    metaclass=DataObjectMetaclass,
    config=_DATA_OBJECT_DEFAULT_CONFIG,
):
    __slots__ = ("__data_object_fields_set__",)

    if TYPE_CHECKING:
        # This isn't actually a field, but type-checking wise it behaves just like a non-init field
        # on a dataclass so we define this here anyway.
        __data_object_fields_set__: FieldsSet = dataclasses.field(
            init=False,
            repr=False,
            compare=False,
        )
        """
        Set of field names explicitly set during initialization, or assigned to the field at some
        point following. Used for equivalent set/unset functionality as Pydantic's `BaseModel`.
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
        from ceres.data import __Frozen__

        @dataclass_transform(
            kw_only_default=True,
            frozen_default=True,
            field_specifiers=_FIELD_SPECIFIERS,
        )
        class Frozen(__Frozen__, frozen=True):
            __slots__ = ()
    else:

        @class_property
        @classmethod
        def Frozen(cls) -> type[DataObject]:
            return __Frozen__

    __data_object_abstract__: ClassVar[bool] = False
    __data_object_required_slots__: ClassVar[tuple[str, ...]] = ()

    if TYPE_CHECKING:
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

    @cached_class_property
    @classmethod
    def __data_object_fields__(cls) -> Mapping[str, FieldInfo]:
        return fields_of(cls, cache=False)

    @cached_class_property
    @classmethod
    def __data_object_init_fields__(cls) -> Mapping[str, FieldInfo]:
        return fields_of(cls, cache=False)

    @cached_class_property
    @classmethod
    def __data_object_computed_fields__(cls) -> Mapping[str, ComputedFieldInfo]:
        return computed_fields_of(cls, cache=False)

    @cached_class_property
    @classmethod
    def __data_object_field_indexes__(cls) -> Mapping[str, int]:
        return MappingProxyType(
            {field: index for index, field in enumerate(cls.__data_object_fields__)}
        )

    @cached_class_property
    @classmethod
    def __data_object_field_names__(cls) -> tuple[str, ...]:
        return tuple(cls.__data_object_fields__)

    @cached_class_property
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

    @classmethod
    def __data_object_create__(
        cls,
        values: Mapping[str, Any],
        fields_set: Iterable[str] | int | bool | None = None,
    ) -> Self:
        instance = object.__new__(cls)

        fields_set_provided = fields_set is not None
        fields_set = FieldsSet(cls, fields_set if fields_set_provided else values.keys())

        for field_name, field in cls.__data_object_fields__.items():
            value = values.get(field_name, Undefined)
            if value is Undefined:
                if field.is_required():
                    raise AttributeError(f"Missing value for required field '{field_name}'.")

                value = field.get_default(
                    call_default_factory=True,
                    validated_data=values,  # type: ignore
                )

            _object_setattr(instance, field_name, value)
            if not fields_set_provided:
                fields_set.add(field_name)

        _object_setattr(instance, "__data_object_fields_set__", fields_set)
        return instance

    @classmethod
    def __data_object_construct__(cls, *args: Any, **kwargs: Any) -> Self:
        values = cls.__data_object_resolve_args_kwargs__(args, kwargs, True)
        return cls.__data_object_create__(values)

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

    @cached_class_property
    @classmethod
    def __data_object_defined_slots__(cls) -> tuple[str, ...]:
        return tuple(
            slot
            for slot in declared_slots_of(cls)
            if slot not in ("__weakref__", "__dict__", "__data_object_fields_set__")
        )

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
        Model.__data_object_origin__ = cls
        Model.__qualname__ = __qualname__ or name
        Model.__module__ = cls.__module__
        Model.__doc__ = cls.__doc__

        return Model

    @override
    def __repr__(self) -> str:
        tokens = [type(self).__name__, "("]
        for field in self.__data_object_fields__:
            value = getattr(self, field, Undefined)
            if value is Undefined:
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
        super().__init_subclass__()

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
    def __reduce__(self) -> _ReducedDataObject:
        cls = type(self)
        dictionary: dict | None = getattr(self, "__dict__", None)
        if dictionary:
            dictionary = dict(dictionary)

        slots = self.__data_object_defined_slots__
        slots = [_object_getattribute(self, slot) for slot in slots] if slots else None

        return _reconstruct_data_object, (
            cls,
            dictionary,
            slots,
            self.__pydantic_fields_set__.mask,
        )


_is_data_object_class_defined = True

if TYPE_CHECKING:
    DataObject()  # Ensure class meets abstract class requirements.

DataObject.__dataclass_params__.frozen = None


class __Frozen__(DataObject, frozen=True):
    __slots__ = ()


__Frozen__.__name__ = "Frozen"
__Frozen__.__qualname__ = f"{DataObject.__name__}.{__Frozen__.__name__}"

_is_data_object_frozen_class_defined = True


type _ReducedDataObjectValues = tuple[
    type[object],
    dict[str, Any] | None,
    list[Any] | None,
    int,
]
type _ReducedDataObject = tuple[Callable[..., Any], _ReducedDataObjectValues]

_object_getattribute: Final = object.__getattribute__
_object_setattr: Final = object.__setattr__


def _do[T: DataObject](
    cls: type[T],
    dictionary: dict[str, Any] | None,
    slots: list[Any] | None,
    fields_set_mask: int,
    /,
) -> T:
    instance = object.__new__(cls)

    if dictionary:
        for attribute, value in dictionary.items():
            _object_setattr(instance, attribute, value)
    if slots:
        for attribute, value in zip(cls.__data_object_defined_slots__, slots):
            _object_setattr(instance, attribute, value)

    _object_setattr(instance, "__data_object_fields_set__", FieldsSet(cls, fields_set_mask))
    return instance


_reconstruct_data_object: Final = _do


def _is_data_object_type(obj: object, /) -> TypeIs[type[DataObject]]:
    return isinstance(obj, type) and hasattr(obj, "__data_object_fields__")


DataModel.__data_object_origin__ = DataObject


def __proxy_data_object_class_item(
    item: Callable[..., Any] | classmethod | ClassProperty,
) -> Callable[..., Any] | ClassProperty:
    if isinstance(item, ClassProperty):
        proxy = ClassProperty[DataModel, Any](
            lambda cls: getattr(cls.__data_object_origin__, item.__name__)
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
    def wrapper(cls, *args, **kwargs):
        return function(cls.__data_object_origin__, *args, **kwargs)

    return wrapper


for attribute, value in DataObject.__dict__.items():
    if attribute.startswith("__data_object_") and isinstance(value, (classmethod, ClassProperty)):
        setattr(DataModel, attribute, __proxy_data_object_class_item(value))


class ImmutableDataModel(DataModel):
    model_config = ConfigDict(frozen=True)


if TYPE_CHECKING:
    # This is just to ensure that `ValidatedDataclass` is recognized as a valid Pydantic dataclass
    # type for type checking purposes without actually inheriting from `typing.Protocol` which
    # inherits from `typing.Generic` and causes issues with `dataclasses.dataclass`.
    __ensure_is_pydantic_dataclass: type[PydanticDataclass] = DataObject


type Username = Annotated[
    str,
    StringConstraints(
        pattern=r"[a-zA-Z\-_]+",
        min_length=1,
        max_length=64,
    ),
]


def _validate_password(value: str) -> str:
    bytes = len(value.encode())
    if bytes > 72:
        raise ValueError("password cannot exceed 72 bytes")

    return value


type Password = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32),
    AfterValidator(_validate_password),
]


def _validate_email_address(value: str) -> str:
    from email_validator import validate_email

    validated = validate_email(value, check_deliverability=False)
    return validated.normalized.lower()


type EmailAddress = Annotated[
    str,
    AfterValidator(_validate_email_address),
]

BCryptHash: Final = NewType("BCryptHash", str)
_ValidatedBCryptHash = Annotated[
    BCryptHash,
    StringConstraints(pattern=r"^\$2[ayb]\$.{56}$"),
]

if not TYPE_CHECKING:
    BCryptHash = _ValidatedBCryptHash

Argon2Hash: Final = NewType("Argon2Hash", str)
_ValidatedArgon2Hash = Annotated[
    Argon2Hash,
    StringConstraints(
        pattern=r"^\$argon2(?:(?:id)|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/$]+$"
    ),
]

if not TYPE_CHECKING:
    Argon2Hash = _ValidatedArgon2Hash


type PasswordHash = BCryptHash | Argon2Hash


class StrEnum(BaseStrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, *args: Any, **kwargs: Any) -> str:
        return name.lower().replace("_", "-")

    @override
    def __str__(self) -> str:
        return self.value


_order_cache: dict[tuple[type[OrderedStrEnum], str], int] = {}


class OrderedStrEnum(StrEnum):
    @classmethod
    def __order_mapping__(cls) -> dict[Any, int]:
        return {}

    @property
    def order(self) -> int:
        key = (type(self), self)
        value = _order_cache.get(key)
        if value is not None:
            return value

        value = self.__order_mapping__().get(self)
        if value is None:
            value = tuple(type(self)).index(self)

        _order_cache[key] = value
        return value

    @override
    def __lt__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, OrderedStrEnum):
            return self.order < __x.order

        return super().__lt__(__x)

    @override
    def __le__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, OrderedStrEnum):
            return self.order <= __x.order

        return super().__le__(__x)

    @override
    def __gt__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, OrderedStrEnum):
            return self.order > __x.order

        return super().__gt__(__x)

    @override
    def __ge__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, OrderedStrEnum):
            return self.order >= __x.order

        return super().__ge__(__x)


def defaulting[T: SupportsPydanticFieldsSet](
    original: T,
    defaults: T | dict[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> T:
    if defaults is None:
        return original

    is_mapping = util.is_mapping(defaults)

    update: dict[str, Any] = {}
    original_fields = original.__pydantic_fields_set__
    defaults_fields = defaults.__pydantic_fields_set__ if not is_mapping else defaults.keys()

    for field in defaults_fields:
        if field not in original_fields:
            try:
                update[field] = getattr(defaults, field) if not is_mapping else defaults[field]
            except AttributeError:
                pass

    for key, value in kwargs.items():
        if key not in original_fields and key not in update:
            update[key] = value

    if isinstance(original, BaseModel):
        return original.model_copy(update=update)
    else:
        return dataclasses.replace(original, **update)  # type: ignore


def replacing[T: Dataclass | BaseModel](
    original: T,
    overrides: T | dict[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> T:
    if overrides is None:
        return original

    update = overrides if util.is_mapping(overrides) else to_dict(overrides, exclude_unset=True)
    update.update(kwargs)

    if isinstance(original, BaseModel):
        return original.model_copy(update=update)
    else:
        return dataclasses.replace(
            original,  # type: ignore
            **update,
        )


def WithDefaults(
    defaults: SupportsPydanticFieldsSet | Callable[[], SupportsPydanticFieldsSet] | None = None,
    /,
    **kwargs: Any,
) -> AfterValidator:
    if callable(defaults):
        defaults = defaults()

    def WithDefaults(obj: object) -> Any:
        if not _supports_fields_set(obj):
            raise TypeError(
                "`WithDefaults` can only be applied to types with set fields tracking, such as `BaseModel` or `DataObject` instances."
            )

        return defaulting(obj, defaults, **kwargs)

    return AfterValidator(WithDefaults)


_REGEX_FLAG_CHARACTERS = set(member for member in RegexFlag.__members__ if len(member) == 1)


def _pre_validate_regex_flags(value: object) -> object:
    if isinstance(value, str):
        value = value.upper()
        try:
            return RegexFlag[value]
        except KeyError:
            pass

        summed = RegexFlag.NOFLAG
        for character in value:
            try:
                summed |= RegexFlag[character]
            except KeyError:
                raise ValueError(
                    f"invalid regex flag character '{character}', must be one of: {_REGEX_FLAG_CHARACTERS}"
                )

        return summed

    return value


type RegexFlags = Annotated[RegexFlag, BeforeValidator(_pre_validate_regex_flags)]


def to_kwargs[T: classmethod | Callable[..., Any]](method: T) -> T:
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


type BytesLike = bytes | bytearray

if TYPE_CHECKING:
    from typing import SupportsBytes

    ToBytes: TypeAlias = bytes | bytearray | memoryview | str | SupportsBytes
else:
    ToBytes: TypeAlias = bytes | bytearray | str


def to_bytes(
    data: ToBytes,
    /,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> bytes:
    if isinstance(data, str):
        return bytes(data, encoding, errors)

    return bytes(data)


type Name = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
type NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
type NonBlankStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


def _validate_date(value: date | None) -> date | None:
    return value


type Date = Annotated[
    date,
    AfterValidator(_validate_date),
]


def _validate_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        instance = value
    else:
        instance: datetime | date = validate(value, datetime | date)
        if not isinstance(instance, datetime):
            return datetime(
                year=instance.year,
                month=instance.month,
                day=instance.day,
                tzinfo=UTC,
            )

    if instance.tzinfo is None:
        return instance.replace(tzinfo=UTC)

    return instance.astimezone(UTC)


type DateTime = Annotated[
    datetime,
    AfterValidator(_validate_datetime),
]


def _validate_timedelta(value: Any) -> timedelta | None:
    if value is None:
        return None

    return util.decode_td(value)


type TimeDelta = Annotated[
    timedelta,
    BeforeValidator(_validate_timedelta),
]

_ZERO_TIMEDELTA = timedelta()


def _validate_positive_timedelta(value: object) -> timedelta | None:
    delta = _validate_timedelta(value)
    if delta is None:
        return None

    assert delta > _ZERO_TIMEDELTA, "must be greater than zero"
    return delta


type PositiveTimeDelta = Annotated[
    timedelta,
    BeforeValidator(_validate_positive_timedelta),
]


def _validate_non_negative_timedelta(value: object) -> timedelta | None:
    delta = _validate_timedelta(value)
    if delta is None:
        return None

    assert delta >= _ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return delta


type NonNegativeTimeDelta = Annotated[
    timedelta,
    BeforeValidator(_validate_non_negative_timedelta),
]


def uuid4() -> UUID:
    """Generate a version 4 UUID."""
    try:
        from uuid_utils import uuid4

        return UUID(int=uuid4().int)
    except ImportError:
        from uuid import uuid4

        return uuid4()


def uuid7(
    timestamp: int | None = None,
    nanoseconds: int | None = None,
) -> UUID:
    """Generate a version 7 UUID using a time value and random bytes."""
    from uuid_utils import uuid7

    return UUID(int=uuid7(timestamp, nanoseconds).int)


def _pre_validate_from_json(value: object) -> object:
    if isinstance(value, str | bytes):
        import json

        try:
            return json.loads(value)
        except Exception as error:
            raise ValueError(f"invalid JSON: {error}")

    return value


type FromJSON[T] = Annotated[T, BeforeValidator(_pre_validate_from_json), NoDecode]


def _pre_validate_from_yaml(value: object) -> object:
    if isinstance(value, (str, bytes)):
        import json

        try:
            return json.loads(value)
        except Exception:
            pass

        import yaml

        try:
            return yaml.safe_load(value)
        except Exception as error:
            raise ValueError(f"invalid YAML: {error}")

    return value


type FromYAML[T] = Annotated[T, BeforeValidator(_pre_validate_from_yaml), NoDecode]


def _validate_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


def _serialize_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


type Number = Annotated[
    int | float,
    Field(union_mode="left_to_right"),
    BeforeValidator(_validate_number),
    PlainSerializer(_serialize_number),
]

type JSONValue = None | bool | Number | str | JSONList | JSONDict
type JSONDict = dict[str, JSONValue]
type JSONList = list[JSONValue]


def _validate_json_serializable(value: object) -> object:
    try:
        to_json(value)
    except Exception as error:
        raise ValueError(f"not serializable to JSON: {error}")

    return value


type JSONSerializable[T = Any] = Annotated[T, AfterValidator(_validate_json_serializable)]
type JSONSerializableDict[T = Any] = JSONSerializable[dict[str, T]]
type JSONSerializableList[T = Any] = JSONSerializable[list[T]]

type MaybeList[T] = T | list[T]

if TYPE_CHECKING:
    type MaybeSequence[T] = T | Sequence[T]
else:
    type MaybeSequence[T] = T | list[T]
