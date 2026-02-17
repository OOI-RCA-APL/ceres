from __future__ import annotations

import dataclasses
import sys
from abc import ABCMeta
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableSet,
    Sequence,
    Set,
    Sized,
)
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum as BaseStrEnum
from functools import wraps
from re import RegexFlag
from types import MappingProxyType
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
    Unpack,
    cast,
    dataclass_transform,
    final,
    overload,
    override,
    runtime_checkable,
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
from sqlalchemy.util import defaultdict
from typing_extensions import TypeIs, TypeVar

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


def _as_class[T](obj: MaybeType[T]) -> type[T]:
    return obj if isinstance(obj, type) else type(obj)


@cached(weak=True)
def adapt[T](ty: type[T] | Any, /) -> TypeAdapter[T]:
    return TypeAdapter(ty)


if TYPE_CHECKING:
    from _typeshed import DataclassInstance as __DataclassInstance

    class Dataclass(__DataclassInstance, Protocol):
        __slots__ = ()

    from pydantic._internal._dataclasses import PydanticDataclass as __PydanticDataclass

    class PydanticDataclass(__PydanticDataclass, Protocol):
        __slots__ = ()

else:

    class Dataclass:
        __slots__ = ()

    class PydanticDataclass:
        __slots__ = ()


DataclassField: TypeAlias = dataclasses.Field
DataclassLike: TypeAlias = Dataclass | BaseModel
DataclassFieldLike: TypeAlias = dataclasses.Field | FieldInfo | ComputedFieldInfo


def is_dataclass_instance(obj: object, /) -> TypeIs[Dataclass]:
    return not isinstance(obj, type) and is_dataclass(obj)


def is_dataclass_type(obj: object, /) -> TypeIs[type[Dataclass]]:
    return isinstance(obj, type) and is_dataclass(obj)


@overload
def is_dataclass(obj: type, /) -> TypeIs[type[Dataclass]]: ...
@overload
def is_dataclass(obj: object, /) -> TypeIs[MaybeType[Dataclass]]: ...
def is_dataclass(obj: object, /) -> TypeIs[MaybeType[Dataclass]]:
    return dataclasses.is_dataclass(obj)


@overload
def is_pydantic_dataclass(obj: type, /) -> TypeIs[type[PydanticDataclass]]: ...
@overload
def is_pydantic_dataclass(obj: object, /) -> TypeIs[MaybeType[PydanticDataclass]]: ...
def is_pydantic_dataclass(obj: object, /) -> TypeIs[MaybeType[PydanticDataclass]]:
    if not isinstance(obj, type):
        obj = type(obj)

    return pydantic.dataclasses.is_pydantic_dataclass(obj)


def is_pydantic_dataclass_type(obj: object, /) -> TypeIs[type[PydanticDataclass]]:
    return isinstance(obj, type) and is_pydantic_dataclass(obj)


def is_pydantic_dataclass_instance(obj: object, /) -> TypeIs[PydanticDataclass]:
    return not isinstance(obj, type) and is_pydantic_dataclass(obj)


class SupportsPydanticFields(Protocol):
    if TYPE_CHECKING:
        __pydantic_fields__: ClassVar[dict[str, FieldInfo]]


def _supports_pydantic_fields(obj: object, /) -> TypeIs[MaybeType[SupportsPydanticFields]]:
    return hasattr(obj, "__pydantic_fields__")


@runtime_checkable
class SupportsFieldsSet(SupportsPydanticFields, Protocol):
    @property
    def __pydantic_fields_set__(self) -> Set[str]: ...


def _supports_fields_set(obj: object, /) -> TypeIs[MaybeType[SupportsFieldsSet]]:
    return hasattr(obj, "__pydantic_fields_set__")


def fields_set_on(obj: SupportsFieldsSet, /) -> Set[str]:
    return obj.__pydantic_fields_set__


_field_caches = defaultdict[
    tuple[bool, bool],
    WeakKeyDictionary[type, Mapping[str, DataclassFieldLike]],
](WeakKeyDictionary)

type MaybeType[T] = T | type[T]


_EMPTY_MAPPING: Final[Mapping[str, Any]] = MappingProxyType({})


@overload
def fields_of(
    obj: MaybeType[PydanticDataclass | BaseModel],
    /,
    include_computed: Literal[True],
    include_init_vars: bool = False,
    cache: bool = True,
) -> Mapping[str, FieldInfo | ComputedFieldInfo]: ...


@overload
def fields_of(
    obj: MaybeType[PydanticDataclass | BaseModel],
    /,
    include_computed: Literal[False] = False,
    include_init_vars: bool = False,
    cache: bool = True,
) -> Mapping[str, FieldInfo]: ...


@overload
def fields_of(
    obj: MaybeType[Dataclass],
    /,
    include_computed: bool = False,
    include_init_vars: bool = False,
    cache: bool = True,
) -> Mapping[str, DataclassField]: ...


def fields_of(
    obj: MaybeType[Dataclass | PydanticDataclass | BaseModel],
    /,
    include_computed: bool = False,
    include_init_vars: bool = False,
    cache: bool = True,
) -> Mapping[str, FieldInfo | ComputedFieldInfo | DataclassField]:
    cls = _as_class(obj)
    key = (include_computed, include_init_vars)
    if cache:
        cached = _field_caches[key].get(cls, Undefined)
        if cached is not Undefined:
            return cached

    if _supports_pydantic_fields(cls):
        fields: Mapping[str, DataclassFieldLike] = {}
        for field, info in cls.__pydantic_fields__.items():
            if not include_init_vars and info.init_var:
                continue

            fields[field] = info

        if include_computed:
            fields.update(computed_fields_of(cls))

        fields = MappingProxyType(fields)
    elif is_dataclass_type(cls):
        fields = MappingProxyType({field.name: field for field in dataclasses.fields(cls)})
    else:
        raise TypeError(f"Unsupported type for `fields_of`: {cls}")

    if cache:
        fields = _field_caches[key].setdefault(cls, fields)

    return fields


_computed_fields_cache: WeakKeyDictionary[type, Mapping[str, ComputedFieldInfo]] = (
    WeakKeyDictionary()
)


def computed_fields_of(
    obj: MaybeType[Dataclass | PydanticDataclass | BaseModel],
    /,
    *,
    cache: bool = True,
) -> Mapping[str, ComputedFieldInfo]:
    cls = _as_class(obj)
    if cache:
        cached = _computed_fields_cache.get(cls, Undefined)
        if cached is not Undefined:
            return cached

    if is_pydantic_dataclass_type(cls):
        fields = MappingProxyType(
            {
                name: decorator.info
                for name, decorator in cls.__pydantic_decorators__.computed_fields.items()
            }
        )
    elif isinstance(obj, BaseModel):
        fields = MappingProxyType(obj.__pydantic_computed_fields__)
    elif is_dataclass_type(cls):
        fields = _EMPTY_MAPPING
    else:
        raise TypeError(f"Unsupported type for `computed_fields_of`: {cls}")

    if cache:
        fields = _computed_fields_cache.setdefault(cls, fields)

    return fields


def items_of(
    obj: DataclassLike,
    *,
    include: set[str] | None = None,
    exclude: set[str] | None = None,
    exclude_unset: bool = False,
    exclude_computed_fields: bool = True,
) -> Iterator[tuple[str, Any]]:
    if not _supports_fields_set(obj):
        fields_set = None
    else:
        fields_set = fields_set_on(obj) if exclude_unset else None

    for field in fields_of(obj, include_computed=not exclude_computed_fields):
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


def to_dict(
    obj: DataclassLike,
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


def dump(obj: object, /, **kwargs: Unpack[DumpKwargs]) -> Any:
    return adapt(type(obj)).dump_python(obj, **kwargs)


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


def to_json(obj: object, /, **kwargs: Unpack[ToJSONKwargs]) -> str:
    return adapt(type(obj)).dump_json(obj, **kwargs).decode()


class ToYAMLKwargs(ToJSONKwargs):
    pass


def to_yaml(obj: object, /, **kwargs: Unpack[ToYAMLKwargs]) -> str:
    import yaml

    return yaml.safe_dump(simplify(obj, **kwargs), indent=kwargs.get("indent", None))


class SimplifyKwargs(ToJSONKwargs):
    pass


def simplify(obj: object, /, **kwargs: Unpack[SimplifyKwargs]) -> Any:
    import json

    return json.loads(to_json(obj, **kwargs))


class ValidateKwargs(TypedDict, total=False):
    from_attributes: bool | None
    strict: bool | None
    extra: ExtraValues | None
    from_attributes: bool | None
    context: Any | None
    experimental_allow_partial: bool | Literal["off", "on", "trailing-strings"]
    by_alias: bool | None
    by_name: bool | None


@overload
def validate[T](type: type[T], data: Any, /, **kwargs: Unpack[ValidateKwargs]) -> T: ...
@overload
def validate(type: Any, data: Any, /, **kwargs: Unpack[ValidateKwargs]) -> Any: ...
def validate(type: Any, data: Any, /, **kwargs: Unpack[ValidateKwargs]) -> Any:
    return adapt(type).validate_python(data, **kwargs)


class FromJSONKwargs(TypedDict, total=False):
    strict: bool | None
    extra: ExtraValues | None
    experimental_allow_partial: bool | Literal["off", "on", "trailing-strings"]
    context: Any | None
    by_alias: bool | None
    by_name: bool | None


@overload
def from_json[T](type: type[T], data: str, /, **kwargs: Unpack[FromJSONKwargs]) -> T: ...
@overload
def from_json(type: Any, data: str, /, **kwargs: Unpack[FromJSONKwargs]) -> Any: ...
def from_json(type: Any, data: str, /, **kwargs: Unpack[FromJSONKwargs]) -> Any:
    return adapt(type).validate_json(data, **kwargs)


class FromYAMLKwargs(FromJSONKwargs, total=False):
    pass


@overload
def from_yaml[T](type: type[T], data: str, /, **kwargs: Unpack[FromYAMLKwargs]) -> T: ...
@overload
def from_yaml(type: Any, data: str, /, **kwargs: Unpack[FromYAMLKwargs]) -> Any: ...
def from_yaml(type: Any, data: str, /, **kwargs: Unpack[FromYAMLKwargs]) -> Any:
    import json

    try:
        parsed = json.loads(data)
    except Exception:
        import yaml

        parsed = yaml.safe_load(data)

    return validate(type, parsed, **kwargs)


BytesLike: TypeAlias = bytes | bytearray

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


Name: TypeAlias = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
NonEmptyStr: TypeAlias = Annotated[str, StringConstraints(min_length=1)]
NonBlankStr: TypeAlias = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


def __validate_date(value: date | None) -> date | None:
    return value


Date: TypeAlias = Annotated[date, AfterValidator(__validate_date)]


def __validate_datetime(value: object) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        instance = value
    else:
        instance: datetime | date = util.adapt(datetime | date).validate_python(value)  # type: ignore
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


DateTime: TypeAlias = Annotated[datetime, AfterValidator(__validate_datetime)]


def __validate_timedelta(value: Any) -> timedelta | None:
    if value is None:
        return None

    return util.decode_td(value)


TimeDelta: TypeAlias = Annotated[timedelta, BeforeValidator(__validate_timedelta)]

__ZERO_TIMEDELTA = timedelta()


def __validate_positive_timedelta(value: object) -> timedelta | None:
    delta = __validate_timedelta(value)
    if delta is None:
        return None

    assert delta > __ZERO_TIMEDELTA, "must be greater than zero"
    return delta


PositiveTimeDelta: TypeAlias = Annotated[timedelta, BeforeValidator(__validate_positive_timedelta)]


def __validate_non_negative_timedelta(value: object) -> timedelta | None:
    delta = __validate_timedelta(value)
    if delta is None:
        return None

    assert delta >= __ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return delta


NonNegativeTimeDelta: TypeAlias = Annotated[
    timedelta,
    BeforeValidator(__validate_non_negative_timedelta),
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


def __pre_validate_from_json(value: object) -> object:
    if isinstance(value, str | bytes):
        import json

        try:
            return json.loads(value)
        except Exception as error:
            raise ValueError(f"invalid JSON: {error}")

    return value


def __pre_validate_from_yaml(value: object) -> object:
    if isinstance(value, str | bytes):
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


_T = TypeVar("_T")

FromJSON: TypeAlias = Annotated[_T, BeforeValidator(__pre_validate_from_json), NoDecode]
FromYAML: TypeAlias = Annotated[_T, BeforeValidator(__pre_validate_from_yaml), NoDecode]


def __validate_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


def __serialize_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


Number: TypeAlias = Annotated[
    int | float,
    Field(union_mode="left_to_right"),
    BeforeValidator(__validate_number),
    PlainSerializer(__serialize_number),
]

type JSONValue = None | bool | Number | str | JSONList | JSONDict
JSONDict: TypeAlias = dict[str, JSONValue]
JSONList: TypeAlias = list[JSONValue]


def __validate_jsonable(value: object) -> object:
    try:
        to_json(value)
    except Exception as error:
        raise ValueError(f"not serializable to JSON: {error}")

    return value


_TAny = TypeVar("_TAny", default=Any)
JSONSerializable: TypeAlias = Annotated[_TAny, AfterValidator(__validate_jsonable)]

_TValue = TypeVar("_TValue", default=Any)
JSONSerializableDict: TypeAlias = JSONSerializable[dict[str, _TValue]]
JSONSerializableList: TypeAlias = JSONSerializable[list[_TValue]]

MaybeList: TypeAlias = _T | list[_T]

if TYPE_CHECKING:
    MaybeSequence: TypeAlias = _T | Sequence[_T]
else:
    MaybeSequence: TypeAlias = MaybeList


def __validate_non_empty(value: object) -> object:
    if isinstance(value, Sized):
        assert len(value) > 0, "cannot not be empty"

    return value


NonEmpty: TypeAlias = Annotated[_T, AfterValidator(__validate_non_empty)]


def __generate_validation_aliases(field: str) -> str | AliasChoices:
    if "_" not in field:
        return field

    return AliasChoices(field, field.replace("_", "-"))


_DATA_OBJECT_ALIAS_GENERATOR = AliasGenerator(
    validation_alias=__generate_validation_aliases,
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


class DataObjectMetaclass(
    type(Protocol),
    ABCMeta,  # type: ignore
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
        validate_on_init: bool | None = None,
        kw_only: bool = True,
        slots: bool = False,
        abstract: bool = False,
        **kwargs: Any,
    ) -> type[DataObject]:
        data_object_class_name = "DataObject"

        try:
            DataObject  # type: ignore
            is_data_object_class_defined = True
        except NameError:
            is_data_object_class_defined = False

        # `FrozenDataObject` may be undefined if it hasn't been built yet.
        try:
            Frozen = __Frozen__
        except NameError:
            Frozen = None

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
        if "__data_object_abstract__" in namespace:
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
            # Any subclass of `FrozenDataObject` is implicitly frozen.
            if Frozen is not None:
                frozen = any(issubclass(base, Frozen) for base in bases)
            else:
                frozen = False

        if frozen:
            # If `frozen` is set make sure `FrozenDataObject` is set the base classes.
            if Frozen is not None:
                # If `DataObject` is in the bases already, replace it with `FrozenDataObject`.
                bases = tuple(uniquify((Frozen if base is DataObject else base) for base in bases))
                # Ensure `FrozenDataObject` is in the bases if no subclass of it is already.
                if not any(issubclass(base, Frozen) for base in bases):
                    bases = tuple((Frozen, *bases))

        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        key = (cls.__module__, name)
        if key in _data_object_classes_being_built:
            return cls

        # Collect inherited Pydantic config from base classes with `__pydantic_config__` defined.
        inherited = ConfigDict()
        for base in reversed(bases):
            current: ConfigDict | None = getattr(base, "__pydantic_config__", None)
            if current:
                inherited.update(current)

        config: ConfigDict = {
            **inherited,
            "title": cls.__qualname__,
            **(config or {}),
        }

        # TODO: Use a more robust way to detect this.
        _data_object_classes_being_built.add(key)

        # Convert the class into a Pydantic dataclass.
        try:
            data_object_class = cast(
                "type[DataObject]",
                pydantic.dataclasses.dataclass(
                    repr=False,  # `DataObject` implements its own `__repr__`.
                    eq=eq,
                    order=order,
                    unsafe_hash=unsafe_hash,
                    frozen=frozen,
                    config=config,
                    validate_on_init=validate_on_init,
                    slots=slots and not abstract,
                    kw_only=kw_only,
                )(cls),
            )

            data_object_class.__module__ = cls.__module__
            data_object_class.__name__ = cls.__name__
            data_object_class.__qualname__ = cls.__qualname__
            data_object_class.__data_object_abstract__ = abstract

            __data_object_required_slots__: list[str] = []
            if is_data_object_class_defined:
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
                # TODO: Figure out how to avoid this hack.
                #
                # The generated Pydantic dataclass validator ends up being an entirely different
                # class, for some reason, when the dataclass has `slots=True`, and that class gets
                # passed as `cls` to all the field/model validators but misses all the class
                # attributes defined on the dataclass. So we copy them over here, for now.
                assert cls.__class__ is type(data_object_class)
                for attribute, value in data_object_class.__dict__.items():
                    if (
                        # Copy dataclass attributes.
                        attribute.startswith("__dataclass_")
                        # Copy Pydantic attributes.
                        or attribute.startswith("__pydantic_")
                        # Copy data object attributes.
                        or (attribute.startswith("__data_object_"))
                        or attribute == "__signature__"
                    ):
                        setattr(cls, attribute, value)
        finally:
            # if data_object_parameters is not None:
            #     data_object_parameters.frozen = False
            _data_object_classes_being_built.discard(key)

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
    def __ixor__(self, it: Set[_T]) -> Self:
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
    def __xor__(self, other: Set[_T]) -> Self:
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

    if TYPE_CHECKING:
        __data_object_fields_set__: FieldsSet
        """
        Set of field names that were explicitly set during initialization. Used for equivalent
        set/unset functionality as with Pydantic's `BaseModel`.
        """

        __data_object_abstract__: ClassVar[bool] = False
        __data_object_required_slots__: ClassVar[tuple[str, ...]] = ()

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
        return fields_of(cls)

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

    @class_property
    @classmethod
    def __data_object_validator__(cls) -> SchemaValidator:
        return cls.__pydantic_validator__

    @class_property
    @classmethod
    def __data_object_serializer__(cls) -> SchemaSerializer:
        return cls.__pydantic_serializer__

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
        instance = super().__new__(cls)

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

    @cached_class_property
    @classmethod
    def Model(cls) -> type[DataModel]:
        return cls.__data_object_create_model_class__()

    @classmethod
    def __data_object_create_model_class__(cls, name: str | None = None) -> type[DataModel]:
        if name is None:
            name = f"{cls.__name__}.Model"
            __qualname__ = name
        else:
            __qualname__ = None

        bases: tuple[type[Any], ...] = tuple(
            [
                *(
                    base.Model
                    for base in cls.__bases__
                    if issubclass(base, DataObject) and base not in (object, DataObject, __Frozen__)
                )
            ]
        )

        if not any(base for base in bases if issubclass(base, DataModel)):
            bases = tuple([DataModel, *bases])

        def get_copied_validator(name: str) -> Any:
            for current in cls.__mro__:
                if current is DataObject:
                    break

                value = current.__dict__.get(name, PydanticUndefined)
                if value is not PydanticUndefined:
                    return value

            return None

        decorator_descriptors: dict[str, Any] = {}
        decorator_infos = cls.__pydantic_decorators__
        for decorator_type in fields_of(cls.__pydantic_decorators__):
            decorators: dict[str, Decorator] = getattr(decorator_infos, decorator_type, {})
            for decorator_name, decorator in decorators.items():
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
            tokens.append(field)
            tokens.append("=")
            value = getattr(self, field, Undefined)
            if value is not Undefined:
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
        fields_set = set(self.__data_object_fields_set__)
        values = to_dict(self)
        if revalidate:
            model = Model.model_validate(values)
            model.__pydantic_fields_set__ = fields_set
        else:
            model = Model.model_construct(fields_set, **values)

        return model

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__()

    @property
    def __fields_set__(self) -> FieldsSet:
        return self.__data_object_fields_set__

    @property
    def __pydantic_fields_set__(self) -> FieldsSet:
        return self.__data_object_fields_set__

    @model_serializer(mode="wrap")
    def __serialize_data_object__(
        self,
        handler: ModelWrapValidatorHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if info.exclude_unset:
            fields_set = self.__data_object_fields_set__
            if not fields_set.is_full():
                fields_unset = ~fields_set
                for field in fields_unset:
                    data.pop(field, None)

        return data

    @model_validator(mode="wrap")
    @classmethod
    def __validate_data_object__(
        cls,
        data: object,
        handler: ModelWrapValidatorHandler[Self],
    ) -> DataObject:
        if cls.__data_object_abstract__:
            raise DataObjectAbstract(
                f"Cannot instantiate abstract `{DataObject.__name__}` subclass `{cls}`."
            )
        if type(data) is cls:
            computed = cls.__data_object_fields_set__
        elif isinstance(data, Mapping | ArgsKwargs):
            computed = cls._compute_fields_set(data)
        else:
            fields_set: Set[str] | None = getattr(data, "__pydantic_fields_set__", None)
            if fields_set is not None:
                computed = cls._compute_fields_set(fields_set)
            else:
                computed = FieldsSet(cls, cls.__data_object_fields__.keys())

        instance = handler(data)
        if instance is not data:
            _object_setattr(instance, "__data_object_fields_set__", computed)

        return instance

    @classmethod
    def _compute_fields_set(cls, values: Set[str] | Mapping[str, Any] | ArgsKwargs) -> FieldsSet:
        output = FieldsSet(cls)

        if isinstance(values, ArgsKwargs):
            values = cls.__data_object_resolve_args_kwargs__(values.args, values.kwargs)

        # Taken from Pydantic's implementation.
        for name, field in cls.__pydantic_fields__.items():
            if field.alias is not None and field.alias in values:
                output.add(name)

            if (name not in output) and (field.validation_alias is not None):
                aliases: list[str | AliasPath] = (
                    field.validation_alias.choices
                    if isinstance(field.validation_alias, AliasChoices)
                    else [field.validation_alias]
                )

                for alias in aliases:
                    if isinstance(alias, str) and alias in values:
                        output.add(name)
                        break

                    if isinstance(alias, AliasPath):
                        value = alias.search_dict_for_path(cast("dict[str, Any]", values))
                        if value is not PydanticUndefined:
                            output.add(name)
                            break

            if name not in output:
                if name in values:
                    output.add(name)
                elif not field.is_required():
                    pass

        return output

    @override
    def __setattr__(self, name: str, value: Any, /) -> None:
        super().__setattr__(name, value)
        if name in self.__pydantic_fields__:
            self.__data_object_fields_set__.add(name)

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


if TYPE_CHECKING:
    DataObject()  # Ensure class meets abstract class requirements.

if sys.version_info < (3, 13):
    DataObject.__dataclass_params__.frozen = True
else:
    DataObject.__dataclass_params__.frozen = None

try:

    class __Frozen__(DataObject, frozen=True):
        __slots__ = ()

    __Frozen__.__name__ = "Frozen"
    __Frozen__.__qualname__ = f"{DataObject.__name__}.{__Frozen__.__name__}"
finally:
    if sys.version_info < (3, 13):
        DataObject.__dataclass_params__.frozen = False

thing: type[DataObject.Frozen] = DataObject.Frozen

_ReducedDataObjectValues: TypeAlias = tuple[
    type[object],
    dict[str, Any] | None,
    list[Any] | None,
    int,
]
_ReducedDataObject: TypeAlias = tuple[Callable[..., Any], _ReducedDataObjectValues]

_object_getattribute: Final = object.__getattribute__
_object_setattr: Final = object.__setattr__


def _do[T: DataObject](
    cls: type[T],
    dictionary: dict[str, Any] | None,
    slots: list[Any] | None,
    fields_set_mask: int,
    /,
) -> T:
    instance = cls.__new__(cls)

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


class DataModel(BaseModel):
    model_config = {**_DATA_OBJECT_DEFAULT_CONFIG}

    __data_object_origin__: ClassVar[type[DataObject]] = DataObject

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

__USERNAME_PATTERN = r"[a-zA-Z\-_]+"

UsernameStr: TypeAlias = Annotated[
    str,
    StringConstraints(
        pattern=__USERNAME_PATTERN,
        min_length=1,
        max_length=64,
    ),
]


def __validate_password_str(value: str) -> str:
    bytes = len(value.encode())
    if bytes > 72:
        raise ValueError("password cannot exceed 72 bytes")

    return value


PasswordStr: TypeAlias = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32),
    AfterValidator(__validate_password_str),
]


def __validate_email_str(value: str) -> str:
    from email_validator import validate_email

    validated = validate_email(value, check_deliverability=False)
    return validated.normalized.lower()


EmailStr: TypeAlias = Annotated[
    str,
    AfterValidator(__validate_email_str),
]

__BCRYPT_HASH_PATTERN = r"^\$2[ayb]\$.{56}$"

if TYPE_CHECKING:
    util.blackhole(__BCRYPT_HASH_PATTERN)

BCryptHash = NewType(
    "BCryptHash",
    str if TYPE_CHECKING else Annotated[str, StringConstraints(pattern=__BCRYPT_HASH_PATTERN)],
)

__ARGON2_HASH_PATTERN = r"^\$argon2(?:(?:id)|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/$]+$"

if TYPE_CHECKING:
    util.blackhole(__ARGON2_HASH_PATTERN)

Argon2Hash = NewType(
    "Argon2Hash",
    str if TYPE_CHECKING else Annotated[str, StringConstraints(pattern=__ARGON2_HASH_PATTERN)],
)

PasswordHash: TypeAlias = BCryptHash | Argon2Hash


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


def get_assigned_fields(obj: SupportsFieldsSet, /) -> Set[str]:
    return obj.__pydantic_fields_set__


def defaulting[T: SupportsFieldsSet](
    original: T,
    defaults: T | dict[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> T:
    if defaults is None:
        return original

    is_mapping = util.is_mapping(defaults)

    update: dict[str, Any] = {}
    original_fields = get_assigned_fields(original)
    defaults_fields = get_assigned_fields(defaults) if not is_mapping else defaults.keys()

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


def replacing[T: DataclassLike](
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
    defaults: SupportsFieldsSet | Callable[[], SupportsFieldsSet] | None = None,
    /,
    **kwargs: Any,
) -> AfterValidator:
    if callable(defaults):
        defaults = defaults()

    def WithDefaults(obj: object) -> Any:
        if not isinstance(obj, SupportsFieldsSet):
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


RegexFlags = Annotated[RegexFlag, BeforeValidator(_pre_validate_regex_flags)]


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
            values = args[0]
            if isinstance(values, ArgsKwargs):
                values = cls.__data_object_resolve_args_kwargs__(values)
                args = (values, *args[1:])

        return function(cls, *args, **kwargs)

    if isinstance(method, classmethod):
        wrapper = classmethod(wrapper)  # type: ignore

    return wrapper  # type: ignore
