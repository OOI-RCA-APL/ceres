"""General data conversion, validation, and serialization utilities."""

from __future__ import annotations

__all__ = [
    "TypeInput",
    "MaybeClass",
    "adapt",
    "dump",
    "to_json",
    "to_yaml",
    "simplify",
    "from_json",
    "validate",
    "ValidateJSONKwargs",
    "validate_json",
    "ValidateYAMLKwargs",
    "validate_yaml",
    "validated_type",
    "serialized_type",
]

from collections.abc import Callable, Mapping
from types import FunctionType, GenericAlias, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    TypeAliasType,
    TypedDict,
    Unpack,
    cast,
    overload,
)
from weakref import WeakKeyDictionary

from pydantic import (
    AfterValidator,
    BeforeValidator,
    PlainSerializer,
    TypeAdapter,
    WrapSerializer,
    WrapValidator,
)
from pydantic_core import from_json as _from_json
from typing_extensions import TypeForm

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from pydantic.config import ExtraValues
    from pydantic.main import IncEx
    from pydantic_core.core_schema import (
        NoInfoValidatorFunction,
        NoInfoWrapValidatorFunction,
        WithInfoValidatorFunction,
        WithInfoWrapValidatorFunction,
    )

if TYPE_CHECKING:
    from typing import _SpecialForm
else:
    type _SpecialForm = Any


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
    # YAML
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
