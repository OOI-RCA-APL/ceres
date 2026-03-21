import dataclasses
import re
from abc import ABCMeta
from collections.abc import (
    Buffer,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    MutableSet,
    Sequence,
    Set,
)
from copy import deepcopy, replace
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
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
    NamedTuple,
    NewType,
    Protocol,
    Self,
    SupportsBytes,
    TypeAlias,
    TypeAliasType,
    TypedDict,
    TypeIs,
    TypeVar,
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
from annotated_types import Ge, Le
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
    WrapSerializer,
    WrapValidator,
    model_serializer,
    model_validator,
)
from pydantic.aliases import AliasChoices
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic_core import (
    MISSING,
    ArgsKwargs,
    CoreSchema,
    PydanticUndefined,
    SchemaSerializer,
    SchemaValidator,
)
from pydantic_core import from_json as _from_json
from pydantic_extra_types.color import Color as Color
from pydantic_settings import NoDecode
from typing_extensions import TypeForm

from ceres.__internal__.utilities.caching import cached
from ceres.__internal__.utilities.classes import (
    ClassProperty,
    cached_class_property,
    class_property,
    fields_cached_class_property,
    get_declared_slots,
)
from ceres.__internal__.utilities.collections import flatten, uniq
from ceres.__internal__.utilities.typing import extract_field_annotation, lenient_issubclass
from ceres.__internal__.utilities.undefined import Undefined

if TYPE_CHECKING:
    from inspect import Signature
    from struct import Struct as StructDefinition
    from types import CellType

    from pydantic._internal._decorators import Decorator, DecoratorInfos
    from pydantic.config import ExtraValues
    from pydantic.main import IncEx
    from pydantic_core.core_schema import (
        NoInfoValidatorFunction,
        NoInfoWrapValidatorFunction,
        WhenUsed,
        WithInfoValidatorFunction,
        WithInfoWrapValidatorFunction,
    )

if TYPE_CHECKING:
    from typing import _SpecialForm
else:
    type _SpecialForm = Any

__all__ = (
    # Local
    "adapt",
    "dump",
    "to_dict",
    "to_json",
    "to_yaml",
    "simplify",
    "validate",
    "validate_json",
    "validate_yaml",
    "create",
    "construct",
    "fields_of",
    "computed_fields_of",
    "items_of",
    "fields_set_on",
    "replacing",
    "defaulting",
    "WithDefaults",
    "DataObject",
    "DataModel",
    "Date",
    "Time",
    "DateTime",
    "TimeDelta",
    "uuid4",
    "uuid7",
    "Name",
    "Number",
    "FromJSON",
    "FromYAML",
    "JSONValue",
    "JSONDict",
    "JSONList",
    "JSONSerializable",
    "validated_type",
    "serialized_type",
    "ByteRepr",
    "DataStruct",
    "to_bytes",
    "validate_bytes",
    "Int8",
    "Byte",
    "Int16",
    "Int32",
    "Int64",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
    "Float32",
    "Float64",
    "BytesEncoding",
    "BytesErrorHandling",
    "BytesEncodingErrorHandling",
    "BytesDecodingErrorHandling",
    "BytesFromString",
    "BytesToString",
    # Re-exports
    "Color",
    "TypeAdapter",
    "Field",
    "field",
)


type TypeInput[T = Any] = (
    type[T]
    | TypeForm[T]
    | Annotated[T, ...]
    | UnionType
    | GenericAlias
    | FunctionType
    | TypeAliasType
    | _SpecialForm
)
type MaybeClass[T] = T | type[T]


_cached_class_type_adapters: WeakKeyDictionary[type, TypeAdapter[type]] = WeakKeyDictionary()
_cached_type_form_type_adapters: dict[Any, TypeAdapter[Any]] = {}
_cached_dataclasses: WeakKeyDictionary[type, type[PydanticDataclass]] = WeakKeyDictionary()
_cached_fields: WeakKeyDictionary[type, Mapping[str, FieldInfo]] = WeakKeyDictionary()
_cached_init_fields: WeakKeyDictionary[type, Mapping[str, FieldInfo]] = WeakKeyDictionary()
_cached_computed_fields: WeakKeyDictionary[type, Mapping[str, ComputedFieldInfo]] = (
    WeakKeyDictionary()
)


def adapt[T](ty: TypeInput[T], /, *, _namespace: int = 3) -> TypeAdapter[T]:
    key = cast("Any", ty)
    cache: MutableMapping[Any, Any]
    if isinstance(ty, type):
        cache = _cached_class_type_adapters
    else:
        cache = _cached_type_form_type_adapters

    adapter: TypeAdapter[Any] | None = cache.get(key)
    if adapter is None:
        adapter = TypeAdapter(ty, _parent_depth=_namespace)
        adapter = cache.setdefault(key, adapter)

    return adapter


def dump(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    mode: Literal["json", "python"] = "python",
    include: IncEx | None = None,
    exclude: IncEx | None = None,
    by_alias: bool | None = None,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    exclude_computed_fields: bool = False,
    round_trip: bool = False,
    warnings: bool | Literal["none", "warn", "error"] = True,
    fallback: Callable[[Any], Any] | None = None,
    serialize_as_any: bool = False,
    context: Any | None = None,
    _namespace: int = -4,
) -> Any:
    if as_type is None:
        as_type = type(obj)

    return adapt(
        as_type,
        _namespace=_namespace,
    ).dump_python(
        obj,
        mode=mode,
        include=include,
        exclude=exclude,
        by_alias=by_alias,
        exclude_unset=exclude_unset,
        exclude_defaults=exclude_defaults,
        exclude_none=exclude_none,
        exclude_computed_fields=exclude_computed_fields,
        round_trip=round_trip,
        warnings=warnings,
        fallback=fallback,
        serialize_as_any=serialize_as_any,
        context=context,
    )


def to_dict(
    obj: _SupportsPydanticFields | Dataclass,
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


def to_json(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    indent: int | None = None,
    ensure_ascii: bool = False,
    include: IncEx | None = None,
    exclude: IncEx | None = None,
    by_alias: bool | None = None,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    exclude_computed_fields: bool = False,
    round_trip: bool = False,
    warnings: bool | Literal["none", "warn", "error"] = True,
    fallback: Callable[[Any], Any] | None = None,
    serialize_as_any: bool = False,
    context: Any | None = None,
    _namespace: int = -4,
) -> str:
    if as_type is None:
        as_type = type(obj)

    return (
        adapt(
            as_type,
            _namespace=_namespace,
        )
        .dump_json(
            obj,
            indent=indent,
            ensure_ascii=ensure_ascii,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
            context=context,
        )
        .decode()
    )


def to_yaml(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    # Pydantic
    include: IncEx | None = None,
    exclude: IncEx | None = None,
    by_alias: bool | None = None,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    exclude_computed_fields: bool = False,
    warnings: bool | Literal["none", "warn", "error"] = True,
    fallback: Callable[[Any], Any] | None = None,
    serialize_as_any: bool = False,
    context: Any | None = None,
    # YAML-specific Options
    indent: int | None = None,
    default_style: str | None = None,
    default_flow_style: bool | None = False,
    canonical: bool | None = None,
    width: int | None = None,
    line_break: str | None = None,
    explicit_start: bool | None = None,
    explicit_end: bool | None = None,
    version: tuple[int, int] | None = None,
    tags: Mapping[str, str] | None = None,
    sort_keys: bool = False,
    # Type Adapter
    _namespace: int = -5,
) -> str:
    import yaml

    return yaml.safe_dump(
        simplify(
            obj,
            as_type,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
            context=context,
            _namespace=_namespace,
        ),
        indent=indent,
        default_style=default_style,
        default_flow_style=default_flow_style,
        canonical=canonical,
        width=width,
        line_break=line_break,
        explicit_start=explicit_start,
        explicit_end=explicit_end,
        version=version,
        tags=tags,
        sort_keys=sort_keys,
    )


def simplify(
    obj: object,
    as_type: TypeInput | None = None,
    /,
    *,
    include: IncEx | None = None,
    exclude: IncEx | None = None,
    by_alias: bool | None = None,
    exclude_unset: bool = False,
    exclude_defaults: bool = False,
    exclude_none: bool = False,
    exclude_computed_fields: bool = False,
    warnings: bool | Literal["none", "warn", "error"] = True,
    fallback: Callable[[Any], Any] | None = None,
    serialize_as_any: bool = False,
    context: Any | None = None,
    _namespace: int = -4,
) -> Any:
    return from_json(
        to_json(
            obj,
            as_type,
            include=include,
            exclude=exclude,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
            context=context,
            _namespace=_namespace,
        )
    )


def from_json(
    data: str | bytes | bytearray,
    /,
    *,
    allow_inf_nan: bool = True,
    cache_strings: bool | Literal["all", "keys", "none"] = True,
    allow_partial: bool | Literal["off", "on", "trailing-strings"] = False,
) -> Any:
    return _from_json(
        data,
        allow_inf_nan=allow_inf_nan,
        cache_strings=cache_strings,
        allow_partial=allow_partial,
    )


def create[T: DataObject | BaseModel](
    cls: type[T],
    field_values: Mapping[str, Any],
    fields_set: Iterable[str] | bool | None = None,
    /,
) -> T:
    """Construct an instance of `cls` with the provided field values without running validation.

    Args:
        cls: The `DataObject` or `BaseModel` subclass to instantiate.
        field_values: A mapping of field names to pre-validated values.
        fields_set: Fields to mark as explicitly set. Can be an iterable of field names, `True` to mark all fields as set, `False` to mark no fields as set, or `None` to infer set fields from `field_values`.
    Returns:
        An instance of the specified class with the provided field values.

    Raises:
        ValueError: If `cls` is not a subclass of `DataObject` or `BaseModel`, or if a required field value is missing from `field_values`.
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
    """Construct an instance of a `cls` with the provided arguments without running validation.

    Args:
        cls: The `DataObject` or `BaseModel` subclass to construct.
        *args: Positional arguments to pass to the constructor.
        **kwargs: Keyword arguments to pass to the constructor.

    Returns:
        An instance of `cls` constructed with the provided arguments.

    Raises:
        ValueError: If `cls` is not a subclass of `DataObject` or `BaseModel`, a required field is missing, or positional arguments are passed to a `BaseModel` subclass.
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


def validate[T](
    ty: TypeInput[T],
    data: Any,
    /,
    *,
    _namespace: int = -4,
    strict: bool | None = None,
    extra: ExtraValues | None = None,
    from_attributes: bool | None = None,
    context: Any | None = None,
    experimental_allow_partial: bool | Literal["off", "on", "trailing-strings"] = False,
    by_alias: bool | None = None,
    by_name: bool | None = None,
) -> Any:
    return adapt(ty, _namespace=_namespace).validate_python(
        data,
        strict=strict,
        extra=extra,
        from_attributes=from_attributes,
        context=context,
        experimental_allow_partial=experimental_allow_partial,
        by_alias=by_alias,
        by_name=by_name,
    )


class ValidateJSONKwargs(TypedDict, total=False):
    strict: bool | None
    extra: ExtraValues | None
    experimental_allow_partial: bool | Literal["off", "on", "trailing-strings"]
    context: Any | None
    by_alias: bool | None
    by_name: bool | None


def validate_json[T](
    ty: TypeInput[T],
    data: str | bytes | bytearray,
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ValidateJSONKwargs],
) -> T:
    return adapt(ty, _namespace=_namespace).validate_json(data, **kwargs)


class ValidateYAMLKwargs(ValidateJSONKwargs, total=False):
    pass


def validate_yaml[T](
    ty: TypeInput[T],
    data: str | bytes | bytearray,
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ValidateYAMLKwargs],
) -> T:
    from pydantic_core import from_json

    try:
        # Attempt to parse the data as JSON first. YAML is a superset of JSON, and parsing parsing
        # is mcuh faster, so this is a fast-path if the input is actually valid JSON data.
        parsed = from_json(data)
    except Exception:
        # Otherwise, actually parse the input as YAML.
        import yaml

        if isinstance(data, bytearray):
            data = bytes(data)

        parsed = yaml.safe_load(data)

    # Validate the parsed data using the standard validation logic.
    return validate(ty, parsed, _namespace=_namespace, **kwargs)


if TYPE_CHECKING:
    from _typeshed import DataclassInstance as __DataclassInstance

    class Dataclass(__DataclassInstance, Protocol):
        __slots__ = ()

    from pydantic._internal._dataclasses import PydanticDataclass as __PydanticDataclass

    class PydanticDataclass(__PydanticDataclass, Protocol):
        __slots__ = ()

    class _SupportsPydanticFields(Protocol):
        if TYPE_CHECKING:
            __pydantic_fields__: ClassVar[dict[str, FieldInfo]]

    class _SupportsPydanticFieldsSet(_SupportsPydanticFields, Protocol):
        @property
        def __pydantic_fields_set__(self) -> Set[str]: ...

    class _SupportsReplace(Protocol):
        def __replace__(self, *args: Any, **changes: Any) -> Any: ...
else:

    class Dataclass:
        __slots__ = ()

    class PydanticDataclass:
        __slots__ = ()


def fields_of(
    obj: MaybeClass[_SupportsPydanticFields | Dataclass],
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
    obj: MaybeClass[_SupportsPydanticFields | Dataclass],
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
    obj: _SupportsPydanticFields | Dataclass,
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


def fields_set_on(obj: _SupportsPydanticFieldsSet, /) -> Set[str]:
    try:
        return obj.__pydantic_fields_set__
    except AttributeError:
        raise TypeError(f"Unsupported type for `{fields_set_on.__name__}`: {type(obj)}")


if TYPE_CHECKING:

    class _SupportsDefaulting(_SupportsPydanticFieldsSet, _SupportsReplace, Protocol):
        pass


def _get_items(
    obj: Mapping[str, Any] | _SupportsPydanticFieldsSet | None,
) -> Iterable[tuple[str, Any]]:
    if obj is None:
        return ()
    if isinstance(obj, Mapping):
        return obj.items()

    return items_of(obj, exclude_unset=True)


def defaulting[T: _SupportsDefaulting](
    original: T,
    defaults_object: T | dict[str, Any] | None = None,
    /,
    **defaults: Any,
) -> T:
    for field, value in _get_items(defaults_object):
        defaults.setdefault(field, value)

    existing = original.__pydantic_fields_set__
    updates = {field: value for field, value in defaults.items() if field not in existing}

    return replace(original, **updates)


if TYPE_CHECKING:

    class _SupportsReplacing(_SupportsPydanticFieldsSet, _SupportsReplace, Protocol):
        pass


def replacing[T: _SupportsReplacing](
    original: T,
    updates_object: T | dict[str, Any] | None = None,
    /,
    **updates: Any,
) -> T:
    for field, value in _get_items(updates_object):
        updates.setdefault(field, value)

    return replace(original, **updates)


def WithDefaults(
    defaults_object: _SupportsDefaulting | Callable[[], _SupportsDefaulting] | None = None,
    /,
    **defaults: Any,
) -> AfterValidator:
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


@overload
def _is_dataclass(obj: type) -> TypeIs[type[Dataclass]]: ...
@overload
def _is_dataclass(obj: object) -> TypeIs[MaybeClass[Dataclass]]: ...
def _is_dataclass(obj: object) -> TypeIs[MaybeClass[Dataclass]]:
    return dataclasses.is_dataclass(obj)


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

    return pydantic.dataclasses.dataclass(cls, config={"arbitrary_types_allowed": True})


def _as_class[T](obj: MaybeClass[T]) -> type[T]:
    return obj if isinstance(obj, type) else type(obj)


def _decorators_of(cls: type[PydanticDataclass]) -> Iterable[tuple[str, Decorator]]:
    for _, decorators in items_of(cls.__pydantic_decorators__):
        if isinstance(decorators, Mapping):
            yield from decorators.items()


def _generate_validation_aliases(field: str) -> str | AliasChoices:
    if "_" not in field:
        return field

    return AliasChoices(field, field.replace("_", "-"))


_object_setattr: Final = object.__setattr__


class DataObjectConfigDict(ConfigDict):
    pass


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


class DataObjectClassInvalid(TypeError):
    pass


class DataObjectAbstract(RuntimeError):
    pass


_data_object_classes_being_built: set[Any] = set()
_is_data_object_class_defined = False
_is_data_object_frozen_class_defined = False


class _Empty:
    pass


class DataObjectMetaclass(
    type(Protocol) if not TYPE_CHECKING else _Empty,
    ABCMeta,  # Allow data objects to inherit from `ABC`.
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

        if "__data_object_is_generic_alias__" not in namespace:
            namespace["__data_object_is_generic_alias__"] = False

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
        from ceres.data import __Frozen__ as __Frozen

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
    __data_object_is_generic_alias__: ClassVar[bool] = False

    if TYPE_CHECKING:
        from ceres.data import DataObject as __DataObject

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

        alias: GenericAlias = super().__class_getitem__(__args__)  # type: ignore
        if not isinstance(__args__, tuple):
            __args__ = (__args__,)

        from pydantic._internal._generics import replace_types

        parameters: tuple[TypeVar, ...] = getattr(cls, "__parameters__", ())
        replace = {parameter: argument for parameter, argument in zip(parameters, __args__)}
        replaced_annotations: dict[str, Any] = {}
        replaced_fields: dict[str, FieldInfo] = {}

        for field, info in cls.__data_object_fields__.items():
            replaced = replace_types(info.annotation, replace)
            if info.annotation != replaced:
                info = info._copy()
                info.annotation = replaced
                replaced_annotations[field] = replaced
                replaced_fields[field] = info

        names: list[str] = []
        for argument in __args__:
            name = getattr(argument, "__qualname__", None)
            if name is None:
                name = getattr(argument, "__name__", None)
            if name is None:
                name = repr(argument)

            names.append(name)

        __name__ = f"{cls.__name__}[{', '.join(names)}]"

        class Alias(*(alias,)):
            __annotations__ = replaced_annotations
            __data_object_is_generic_alias__ = True
            for field, info in replaced_fields.items():
                locals()[field] = info

        Alias.__qualname__ = Alias.__qualname__.replace(Alias.__name__, __name__)
        Alias.__name__ = __name__
        Alias.__module__ = cls.__module__

        # Add `GenericAlias`-like attributes.
        Alias.__origin__ = cls
        Alias.__args__ = __args__
        Alias.__parameters__ = parameters

        return _data_object_generic_alias_class_cache.setdefault(key, Alias)

    @class_property
    @classmethod
    def __data_object_config__(cls) -> DataObjectConfigDict:
        return cast("DataObjectConfigDict", cls.__pydantic_config__)

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
            for field, value in items_of(self):
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
    model_config = {**_DATA_OBJECT_DEFAULT_CONFIG}

    __data_object_class__: ClassVar[type[DataObject] | None] = None

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


_REGEX_FLAG_CHARACTERS = set(member for member in RegexFlag.__members__ if len(member) == 1)


def _pre_validate_regex_flags(value: object) -> object:
    if not isinstance(value, str):
        return value

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


type RegexFlags = Annotated[RegexFlag, BeforeValidator(_pre_validate_regex_flags)]


if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

    ToBytes: TypeAlias = bytes | bytearray | memoryview | SupportsBytes | ReadableBuffer
    AsBytes: TypeAlias = bytes | bytearray | memoryview | ReadableBuffer
else:
    ToBytes: TypeAlias = bytes | bytearray
    AsBytes: TypeAlias = bytes | bytearray


_NAME_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"
type Name = Annotated[str, StringConstraints(pattern=_NAME_PATTERN)]
type NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
type NonBlankStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


type Date = date
type Time = time

_DATETIME_OR_DATE_TYPE_ADAPTER: TypeAdapter[datetime | date] = TypeAdapter(
    Annotated[datetime | date, Field(union_mode="left_to_right")]
)


def _pre_validate_datetime(value: object | None) -> object | None:
    if value is None:
        return None

    value = _DATETIME_OR_DATE_TYPE_ADAPTER.validate_python(value)
    # If the value is a date and not a date-time, convert it to a date-time at midnight UTC. Don't
    # change this to `isinstance(value, date)` because `datetime` is a subclass of `date`.
    if not isinstance(value, datetime):
        return datetime(
            value.year,
            value.month,
            value.day,
            tzinfo=UTC,
        )

    # If the value is already timezone-aware and in UTC, return it as is.
    if value.tzinfo is UTC:
        return value
    # If the value is missing timezone information, assume it's UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    # Otherwise, convert the value from its current timezone to UTC.
    return value.astimezone(UTC)


type DateTimeInput = datetime | date | int | float | str
type DateTime = Annotated[datetime, BeforeValidator(_pre_validate_datetime)]

_TIMEDELTA_TYPE_ADAPTER = TypeAdapter(timedelta)


def _pre_validate_timedelta(value: object) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value

    if isinstance(value, str):
        try:
            return _TIMEDELTA_TYPE_ADAPTER.validate_python(value)
        except Exception:
            pass

        from ceres.timing import _parse_sdelta

        return _parse_sdelta(value)

    if isinstance(value, (int, float)):
        return timedelta(seconds=value)

    raise ValueError(
        "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', "
        "'ms', 's', 'm', 'h' or 'd'."
    )


type TimeDeltaInput = timedelta | int | float | str
type TimeDelta = Annotated[timedelta, BeforeValidator(_pre_validate_timedelta)]

_ZERO_TIMEDELTA = timedelta()


def _validate_positive_timedelta(value: timedelta) -> timedelta | None:
    assert value > _ZERO_TIMEDELTA, "must be greater than zero"
    return value


type PositiveTimeDelta = Annotated[TimeDelta, AfterValidator(_validate_positive_timedelta)]


def _validate_non_negative_timedelta(value: timedelta) -> timedelta | None:
    assert value >= _ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return value


type NonNegativeTimeDelta = Annotated[
    TimeDelta,
    AfterValidator(_validate_non_negative_timedelta),
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
    if not isinstance(value, (str, bytes)):
        return value

    try:
        return validate_json(Any, value)
    except Exception as exception:
        raise ValueError(f"invalid JSON: {exception}")


type FromJSON[T] = Annotated[T, BeforeValidator(_pre_validate_from_json), NoDecode]


def _pre_validate_from_yaml(value: object) -> object:
    if not isinstance(value, (str, bytes)):
        return value

    try:
        return validate_yaml(Any, value)
    except Exception as exception:
        raise ValueError(f"invalid YAML: {exception}")


type FromYAML[T] = Annotated[T, BeforeValidator(_pre_validate_from_yaml), NoDecode]


def _pre_validate_number(value: object) -> object:
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
    BeforeValidator(_pre_validate_number),
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


@overload
def validated_type[T: TypeInput[Any]](
    ty: T, mode: Literal["before"] = "before"
) -> Callable[[NoInfoValidatorFunction | WithInfoValidatorFunction], T]: ...


@overload
def validated_type[T: TypeInput[Any]](
    ty: T, mode: Literal["after"]
) -> Callable[[NoInfoValidatorFunction | WithInfoValidatorFunction], T]: ...


@overload
def validated_type[T: TypeInput[Any]](
    ty: T, mode: Literal["wrap"]
) -> Callable[[NoInfoWrapValidatorFunction | WithInfoWrapValidatorFunction], T]: ...


def validated_type[T: TypeInput[Any]](
    ty: T, mode: Literal["before", "after", "wrap"] = "before"
) -> Callable[[Callable[..., Any]], T]:
    def validated_type(function: Callable[..., Any]) -> T:
        match mode:
            case "before":
                return cast("T", Annotated[ty, BeforeValidator(function)])
            case "after":
                return cast("T", Annotated[ty, AfterValidator(function)])
            case "wrap":
                return cast("T", Annotated[ty, WrapValidator(function)])
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'before', 'after', or 'wrap'")

    return validated_type


@overload
def serialized_type[T: TypeInput[Any]](
    ty: T, mode: Literal["plain"] = "plain"
) -> Callable[[Callable[..., Any]], T]: ...


@overload
def serialized_type[T: TypeInput[Any]](
    ty: T, mode: Literal["wrap"]
) -> Callable[[Callable[..., Any]], T]: ...


def serialized_type[T: TypeInput[Any]](
    ty: T, mode: Literal["plain", "wrap"] = "plain"
) -> Callable[[Callable[..., Any]], T]:
    def serialized_type(function: Callable[..., Any]) -> T:
        match mode:
            case "plain":
                return cast("T", Annotated[ty, PlainSerializer(function)])
            case "wrap":
                return cast("T", Annotated[ty, WrapSerializer(function)])
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'plain' or 'wrap'")

    return serialized_type


class BytePadding(DataObject, slots=True):
    before: int = Field(default=0, ge=0)
    after: int = Field(default=0, ge=0)


class __BR(NamedTuple):
    code: ByteReprCode
    symbol: str
    type: type | tuple[type, ...]


ByteReprCode = Literal[
    "bytes",
    "boolean",
    "u8",
    "i8",
    "u16",
    "i16",
    "u32",
    "i32",
    "u64",
    "i64",
    "f16",
    # `float`
    "f32",
    "f64",
    # Complex
    "c64",
    "c128",
]

_BYTE_REPR_DEFINITIONS = (
    __BR("bytes", "s", (bytes, bytearray)),
    __BR("boolean", "?", bool),
    __BR("u8", "B", int),
    __BR("i8", "b", int),
    __BR("u16", "H", int),
    __BR("i16", "h", int),
    __BR("u32", "I", int),
    __BR("i32", "i", int),
    __BR("u64", "Q", int),
    __BR("i64", "q", int),
    __BR("f16", "e", float),
    __BR("f32", "f", float),
    __BR("f64", "d", float),
    __BR("c64", "F", complex),
    __BR("c128", "D", complex),
)


@dataclass(frozen=True, kw_only=True)
class ByteRepr:
    code: ByteReprCode | None = field(default=None, kw_only=False)
    length: int | None = field(default=None, kw_only=True)
    validator: Callable[[Any], Any] | None = None
    serializer: Callable[[Any], bytes] | None = None
    padding_before: int | None = None
    padding_after: int | None = None
    format: str = field(init=False)

    def __post_init__(self) -> None:
        if self.code is None:
            if self.length is not None:
                object.__setattr__(self, "code", "bytes")

        definition = _BYTE_REPR_DEFINITION_LOOKUP.get(self.code or "")
        if self.code is not None and definition is None:
            raise TypeError(
                f"Invalid `{ByteRepr.__name__}.code` {self.code!r}, must be one of: "
                f"{list(_BYTE_REPR_DEFINITION_LOOKUP)}"
            )

        if self.length is not None and self.length < 1:
            raise TypeError(f"`{ByteRepr.__name__}.length` must be a positive integer.")

        if self.code == "bytes":
            if self.length is None:
                raise TypeError(
                    f"`{ByteRepr.__name__}.length` must be specified for the 'bytes' byte "
                    "representation."
                )
        else:
            if self.length is not None:
                raise TypeError(
                    f"`{ByteRepr.__name__}.length` can only be specified for the 'bytes' byte "
                    "representation."
                )

        if self.padding_before is not None:
            if self.padding_before < 0 or not self.padding_before.is_integer():
                raise TypeError(
                    f"`{ByteRepr.__name__}.padding_before` must be a non-negative integer."
                )
        if self.padding_after is not None:
            if self.padding_after < 0 or not self.padding_after.is_integer():
                raise TypeError(
                    f"`{ByteRepr.__name__}.padding_after` must be a non-negative integer."
                )

        if definition is None:
            format = ""
        else:
            repeats = 1 if self.length is None else self.length
            if repeats < 1:
                format = ""
            elif repeats == 1:
                format = definition.symbol
            else:
                format = f"{repeats}{definition.symbol}"

            if self.padding_before:
                format = f"{self.padding_before if self.padding_before != 1 else ''}x{format}"
            if self.padding_after:
                format = f"{format}{self.padding_after if self.padding_after != 1 else ''}x"

        object.__setattr__(self, "format", format)


ByteOrder = Literal["big-endian", "little-endian", "native"]

_BYTE_REPR_SUPPORTED_TYPES = tuple(
    uniq(flatten(current.type for current in _BYTE_REPR_DEFINITIONS))
)
_BYTE_REPR_DEFINITION_LOOKUP = {current.code: current for current in _BYTE_REPR_DEFINITIONS}


class __BO(NamedTuple):
    name: ByteOrder
    symbol: str


_BYTE_ORDER_DEFINITIONS = (
    __BO("big-endian", ">"),
    __BO("little-endian", "<"),
    __BO("native", "="),
)

_BYTE_ORDER_SYMBOL_LOOKUP = {current.name: current.symbol for current in _BYTE_ORDER_DEFINITIONS}
_STRUCT_FORMAT_ITEMS_REGEX = re.compile(r"(\d*?)([A-Za-z?x])")


class DataStruct(DataObject):
    __slots__ = ()

    __data_struct_byte_order__: ClassVar[ByteOrder] = "little-endian"

    @classmethod
    @override
    def __data_object_init_subclass__(cls, **kwargs: Any) -> None:
        super().__data_object_init_subclass__(**kwargs)
        cls.__data_struct__

    @fields_cached_class_property
    @classmethod
    def __data_struct__(cls) -> StructDefinition:
        from struct import Struct

        order = cls.__data_struct_byte_order__
        try:
            byte_order_symbol = _BYTE_ORDER_SYMBOL_LOOKUP[order]
        except KeyError:
            raise TypeError(
                f"Invalid byte order {order!r}. Must be one of: {list(_BYTE_ORDER_SYMBOL_LOOKUP)}"
            )

        format: list[str] = [byte_order_symbol]
        pairs: list[tuple[int, str]] = []

        # Iterate through the byte representations of all fields and combine consecutive formats
        # with the same symbol into a single format specifier with a count.
        for representation in cls.__data_struct_field_reprs__.values():
            for match in _STRUCT_FORMAT_ITEMS_REGEX.finditer(representation.format):
                count_text, symbol = match.group(1), match.group(2)
                count = int(count_text) if count_text else 1
                if symbol != "s" and pairs and pairs[-1][1] == symbol:
                    pairs[-1] = (pairs[-1][0] + count, symbol)
                else:
                    pairs.append((count, symbol))

        for count, symbol in pairs:
            format.append(f"{count}{symbol}" if count > 1 else symbol)

        return Struct("".join(format))

    @fields_cached_class_property
    @classmethod
    def __data_struct_field_reprs__(cls) -> Mapping[str, ByteRepr]:
        return MappingProxyType(
            {
                field: cls.__data_struct_compute_field_repr__(field, info)
                for field, info in cls.__data_object_fields__.items()
            }
        )

    @classmethod
    def __data_struct_compute_field_repr__(cls, field: str, info: FieldInfo) -> ByteRepr:
        if info.annotation is None:
            raise TypeError(f"Field `{cls}.{field}` is missing a type annotation.")

        field_type, field_metadata = extract_field_annotation(info)

        representations = [current for current in field_metadata if isinstance(current, ByteRepr)]
        if not representations:
            representation = None
        elif len(representations) == 1:
            representation = representations[0]
        else:
            arguments = {}
            for inherited_representation in representations:
                for inherited_field, inherited_value in dataclasses.asdict(
                    inherited_representation
                ).items():
                    if inherited_field == "format":
                        continue
                    if inherited_value is not None:
                        arguments[inherited_field] = inherited_value

            representation = ByteRepr(**arguments)

        if representation is None:
            if lenient_issubclass(field_type, bool):
                representation = ByteRepr("boolean")
        elif representation.code is None:
            if lenient_issubclass(field_type, bool):
                representation = replace(representation, name="boolean")
            elif lenient_issubclass(field_type, (bytes, bytearray)):
                representation = replace(representation, name="bytes")

        if representation is None or representation.code is None or representation.format == "":
            raise TypeError(
                f"{representation}, Failed to infer byte representation for field `{field_type}.{field}`. Either use a "
                f"numeric alias such as `ceres.data.UInt8` or `ceres.data.Float32`, add an "
                f"explicit `Annotated[..., `{ByteRepr.__name__}(<name>)` to the field's type "
                f"annotation, and/or ensure the field's type is one of {_BYTE_REPR_SUPPORTED_TYPES}."
            )
        if not lenient_issubclass(field_type, _BYTE_REPR_SUPPORTED_TYPES):
            if representation is None or representation.validator is None:
                raise TypeError(
                    f"Field `{cls}.{field}` has unsupported type `{info.annotation!r}` for byte "
                    f"validation/serialization. Must be one of {_BYTE_REPR_SUPPORTED_TYPES} or "
                    "have declared a `ByteRepr` with an assigned `validator`."
                )

        if representation.validator is None:
            definition = _BYTE_REPR_DEFINITION_LOOKUP[representation.code]
            if not lenient_issubclass(field_type, definition.type):
                raise TypeError(
                    f"Field `{field_type}.{field}` has byte representation {representation!r} but is not "
                    f"annotated as `{definition.type}`. Either change the type or add a `validator` to "
                    f"to the field's `{ByteRepr.__name__}`."
                )

        return representation

    def __data_struct_serialize__(self) -> bytes:
        values: list[Any] = []
        for field, representation in self.__data_struct_field_reprs__.items():
            value = getattr(self, field)
            serializer = representation.serializer
            if serializer is not None:
                value = serializer(value)

            values.append(value)

        return self.__data_struct__.pack(*values)

    @classmethod
    def __data_struct_deserialize__(cls, data: Buffer, offset: int = 0, /) -> Self:
        values: dict[str, Any] = {}
        for (field, representation), value in zip(
            cls.__data_struct_field_reprs__.items(),
            cls.__data_struct__.unpack_from(data, offset),
        ):
            validator = representation.validator
            if validator is not None:
                value = validator(value)

            values[field] = value

        return validate(cls, values)

    def __bytes__(self) -> bytes:
        return self.__data_struct_serialize__()


def to_bytes(struct: DataStruct) -> bytes:
    return struct.__data_struct_serialize__()


def validate_bytes[T: DataStruct](cls: type[T], data: Buffer, offset: int = 0, /) -> T:
    return cls.__data_struct_deserialize__(data, offset)


type Int8 = Annotated[int, ByteRepr("i8"), Ge(-128), Le(127)]
type Byte = UInt8
type Int16 = Annotated[int, ByteRepr("i16"), Ge(-32768), Le(32767)]
type Int32 = Annotated[int, ByteRepr("i32"), Ge(-2147483648), Le(2147483647)]
type Int64 = Annotated[int, ByteRepr("i64"), Ge(-9223372036854775808), Le(9223372036854775807)]

type UInt8 = Annotated[int, ByteRepr("u8"), Ge(0), Le(255)]
type UInt16 = Annotated[int, ByteRepr("u16"), Ge(0), Le(65535)]
type UInt32 = Annotated[int, ByteRepr("u32"), Ge(0), Le(4294967295)]
type UInt64 = Annotated[int, ByteRepr("u64"), Ge(0), Le(18446744073709551615)]

type Float32 = Annotated[float, ByteRepr("f32")]
type Float64 = Annotated[float, ByteRepr("f64")]

type BytesEncoding = (
    Literal[
        "ascii",
        "utf-8",
        "latin-1",
        "base-64",
    ]
    | str
)

type BytesErrorHandling = Literal[
    "strict",
    "ignore",
    "replace",
    "backslashreplace",
    "surrogateescape",
    "surrogatepass",
]

type BytesEncodingErrorHandling = (
    BytesErrorHandling
    | Literal[
        "xmlcharrefreplace",
        "namereplace",
    ]
)

type BytesDecodingErrorHandling = BytesErrorHandling


def _normalize_encoding(encoding: BytesEncoding) -> BytesEncoding:
    return encoding.lower().replace("-", "").replace("_", "")


def BytesFromString(
    encoding: BytesEncoding,
    errors: BytesEncodingErrorHandling = "strict",
) -> BeforeValidator:
    if _normalize_encoding(encoding) == "base64":
        from base64 import b64decode

        def convert(value: str) -> bytes:
            return b64decode(value)
    else:

        def convert(value: str) -> bytes:
            return value.encode(encoding, errors)

    def BytesFromString(value: Any) -> bytes:
        if isinstance(value, str):
            return convert(value)

        return bytes(value)

    return BeforeValidator(BytesFromString, str)


def BytesToString(
    encoding: BytesEncoding,
    errors: BytesDecodingErrorHandling = "strict",
    when_used: WhenUsed = "json-unless-none",
) -> PlainSerializer:
    if _normalize_encoding(encoding) == "base64":
        from base64 import b64encode

        def encode(value: Any) -> Any:
            return str(b64encode(value))
    else:

        def encode(value: Any) -> Any:
            return str(value, encoding, errors)

    def BytesToString(value: Any) -> str:
        if value is None or isinstance(value, str):
            return value

        return encode(value)

    return PlainSerializer(BytesToString, str, when_used)
