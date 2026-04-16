"""General data conversion, validation, and serialization utilities.

These helpers wrap Pydantic's `TypeAdapter` to provide a consistent surface for validating and
serializing values against arbitrary type forms (classes, type aliases, `Annotated` types, unions,
generics, etc). Adapters are cached per-type to avoid the overhead of rebuilding them on each
call.
"""

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
"""Any value that can be interpreted as a type for validation and serialization purposes.

Includes plain classes, generic aliases, `Annotated` types, union types, type alias types, and
function-style type forms.
"""

type MaybeClass[T] = T | type[T]
"""Either an instance of `T` or the class `T` itself, used where helpers accept either form."""


# Classes use a `WeakKeyDictionary` so adapters do not keep dynamically-generated classes alive.
# Type forms (unions, generic aliases, etc.) are not weak-referenceable, so they use a regular dict.
_cached_class_type_adapters: WeakKeyDictionary[type, TypeAdapter[type]] = WeakKeyDictionary()
_cached_type_form_type_adapters: dict[Any, TypeAdapter[Any]] = {}


def adapt[T](ty: TypeInput[T], /, *, _namespace: int = 3) -> TypeAdapter[T]:
    """Get a cached `TypeAdapter` for the given type form.

    Args:
        ty: The type to adapt. May be a class, type alias, `Annotated` type, union, etc.
        _namespace: Parent frame depth used by Pydantic to resolve forward references in the type.
            The default of `3` matches direct callers of `adapt`, helpers that wrap `adapt` should
            pass a smaller (more negative or shallower) value to point at their own caller.

    Returns:
        A `TypeAdapter` instance that can validate and serialize values of type `ty`. The same
        adapter is returned on subsequent calls with the same type.
    """
    key = cast("Any", ty)
    cache: MutableMapping[Any, Any]
    if isinstance(ty, type):
        cache = _cached_class_type_adapters
    else:
        cache = _cached_type_form_type_adapters

    adapter: TypeAdapter[Any] | None = cache.get(key)
    if adapter is None:
        adapter = TypeAdapter(ty, _parent_depth=_namespace)
        # Use `setdefault` to handle the race where another thread builds and caches the adapter
        # between our `get` and `set`, ensuring all callers see the same instance.
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
    """Serialize an object to a Python data structure using Pydantic's serialization rules.

    Args:
        obj: The object to serialize.
        as_type: Type to use for serialization. Defaults to the runtime type of `obj`, pass an
            explicit type to use a base class or interface for serialization.
        mode: `"python"` to produce a Python data structure, `"json"` to produce a JSON-compatible
            structure (using strings for non-JSON-native types like `datetime`).
        include: Field selection rules to include during serialization.
        exclude: Field selection rules to exclude during serialization.
        by_alias: Whether to serialize fields using their aliases.
        exclude_unset: Skip fields that were not explicitly set on the model.
        exclude_defaults: Skip fields whose value equals the field default.
        exclude_none: Skip fields whose value is `None`.
        exclude_computed_fields: Skip computed fields.
        round_trip: Serialize so the result can be re-validated to produce an equivalent object.
        warnings: How to handle serialization warnings, see Pydantic's documentation for details.
        fallback: Callable invoked for values that cannot otherwise be serialized.
        serialize_as_any: Treat all fields as `Any` for serialization purposes.
        context: Arbitrary context object made available to custom serializers.
        _namespace: Parent frame depth for forward reference resolution.

    Returns:
        A Python data structure (typically `dict`, `list`, or primitives) representing `obj`.
    """
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
    """Serialize an object to a JSON string using Pydantic's serialization rules.

    Args:
        obj: The object to serialize.
        as_type: Type to use for serialization. Defaults to the runtime type of `obj`.
        indent: Number of spaces to use for indentation, or `None` for a compact single-line form.
        ensure_ascii: Escape non-ASCII characters in the output.
        include: Field selection rules to include during serialization.
        exclude: Field selection rules to exclude during serialization.
        by_alias: Whether to serialize fields using their aliases.
        exclude_unset: Skip fields that were not explicitly set on the model.
        exclude_defaults: Skip fields whose value equals the field default.
        exclude_none: Skip fields whose value is `None`.
        exclude_computed_fields: Skip computed fields.
        round_trip: Serialize so the result can be re-validated to produce an equivalent object.
        warnings: How to handle serialization warnings.
        fallback: Callable invoked for values that cannot otherwise be serialized.
        serialize_as_any: Treat all fields as `Any` for serialization purposes.
        context: Arbitrary context object made available to custom serializers.
        _namespace: Parent frame depth for forward reference resolution.

    Returns:
        A JSON-encoded string representation of `obj`.
    """
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
    """Serialize an object to a YAML string.

    Internally serializes through JSON first to apply Pydantic's serialization rules, then dumps
    the resulting structure to YAML.

    Args:
        obj: The object to serialize.
        as_type: Type to use for serialization. Defaults to the runtime type of `obj`.
        include: Field selection rules to include during serialization.
        exclude: Field selection rules to exclude during serialization.
        by_alias: Whether to serialize fields using their aliases.
        exclude_unset: Skip fields that were not explicitly set on the model.
        exclude_defaults: Skip fields whose value equals the field default.
        exclude_none: Skip fields whose value is `None`.
        exclude_computed_fields: Skip computed fields.
        warnings: How to handle serialization warnings.
        fallback: Callable invoked for values that cannot otherwise be serialized.
        serialize_as_any: Treat all fields as `Any` for serialization purposes.
        context: Arbitrary context object made available to custom serializers.
        indent: YAML indentation width.
        default_style: Default scalar style, see PyYAML documentation.
        default_flow_style: Use flow style by default for collections.
        canonical: Emit canonical YAML form.
        width: Preferred line width.
        line_break: Line break character to use.
        explicit_start: Emit an explicit document start marker (`---`).
        explicit_end: Emit an explicit document end marker (`...`).
        version: YAML version to declare.
        tags: Default tag prefixes.
        sort_keys: Sort mapping keys alphabetically.
        _namespace: Parent frame depth for forward reference resolution.

    Returns:
        A YAML-encoded string representation of `obj`.
    """
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
    """Reduce an object to plain JSON-compatible Python primitives.

    Round-trips the object through JSON to coerce all values into the smallest set of types
    (`dict`, `list`, `str`, `int`, `float`, `bool`, `None`) that Pydantic's JSON serializer
    produces. Useful for handing data off to libraries that only understand primitive types.

    Args:
        obj: The object to simplify.
        as_type: Type to use for serialization. Defaults to the runtime type of `obj`.
        include: Field selection rules to include during serialization.
        exclude: Field selection rules to exclude during serialization.
        by_alias: Whether to serialize fields using their aliases.
        exclude_unset: Skip fields that were not explicitly set on the model.
        exclude_defaults: Skip fields whose value equals the field default.
        exclude_none: Skip fields whose value is `None`.
        exclude_computed_fields: Skip computed fields.
        warnings: How to handle serialization warnings.
        fallback: Callable invoked for values that cannot otherwise be serialized.
        serialize_as_any: Treat all fields as `Any` for serialization purposes.
        context: Arbitrary context object made available to custom serializers.
        _namespace: Parent frame depth for forward reference resolution.

    Returns:
        A plain Python data structure containing only JSON-compatible primitives.
    """
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
    """Parse JSON data into a Python value using `pydantic_core`'s fast parser.

    Args:
        data: JSON-encoded text or bytes.
        allow_inf_nan: Allow `Infinity`, `-Infinity`, and `NaN` literals (not strict JSON).
        cache_strings: Cache repeated strings to reduce memory usage. Pass `"keys"` to cache only
            object keys.
        allow_partial: Tolerate truncated input by returning the longest valid prefix.

    Returns:
        The parsed Python value, typically a `dict`, `list`, or primitive.
    """
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
    """Validate raw data against a type and return a validated instance.

    Args:
        ty: The expected type of the data.
        data: The raw value to validate, typically a `dict`, `list`, or primitive.
        _namespace: Parent frame depth for forward reference resolution.
        strict: Disable type coercion (e.g. don't accept `"1"` for `int`).
        extra: How to handle fields not declared on the model (`"allow"`, `"forbid"`, `"ignore"`).
        from_attributes: Read values from object attributes when the input is not a mapping.
        context: Arbitrary context object made available to custom validators.
        experimental_allow_partial: Tolerate incomplete input where possible.
        by_alias: Match incoming field names against aliases.
        by_name: Match incoming field names against the canonical Python field names.

    Returns:
        A validated instance of `ty`.

    Raises:
        pydantic.ValidationError: If `data` does not satisfy `ty`'s constraints.
    """
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
    """Keyword arguments accepted by `validate_json`."""

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
    """Parse JSON data and validate it against a type.

    Args:
        ty: The expected type of the data.
        data: JSON-encoded text or bytes.
        _namespace: Parent frame depth for forward reference resolution.
        **kwargs: Additional validation options, see `ValidateJSONKwargs`.

    Returns:
        A validated instance of `ty`.

    Raises:
        pydantic.ValidationError: If the parsed JSON does not satisfy `ty`'s constraints.
    """
    return adapt(ty, _namespace=_namespace).validate_json(data, **kwargs)


class ValidateYAMLKwargs(ValidateJSONKwargs, total=False):
    """Keyword arguments accepted by `validate_yaml`, currently identical to JSON kwargs."""


def validate_yaml[T](
    ty: TypeInput[T],
    data: str | bytes | bytearray,
    /,
    *,
    _namespace: int = -4,
    **kwargs: Unpack[ValidateYAMLKwargs],
) -> T:
    """Parse YAML data and validate it against a type.

    Attempts to parse the input as JSON first since JSON is a subset of YAML and `pydantic_core`'s
    JSON parser is significantly faster than PyYAML. Falls back to a full YAML parse on failure.

    Args:
        ty: The expected type of the data.
        data: YAML-encoded text or bytes.
        _namespace: Parent frame depth for forward reference resolution.
        **kwargs: Additional validation options, see `ValidateYAMLKwargs`.

    Returns:
        A validated instance of `ty`.

    Raises:
        pydantic.ValidationError: If the parsed YAML does not satisfy `ty`'s constraints.
        yaml.YAMLError: If the input is not valid YAML.
    """
    from pydantic_core import from_json

    try:
        # Attempt to parse the data as JSON first. YAML is a superset of JSON, and JSON parsing is
        # much faster, so this is a fast-path if the input is actually valid JSON data.
        parsed = from_json(data)
    except Exception:
        # Otherwise, actually parse the input as YAML.
        import yaml

        if isinstance(data, bytearray):
            data = bytes(data)

        parsed = yaml.safe_load(data)

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
    """Decorator factory that attaches a validator function to a type.

    The decorated function becomes the validator for the resulting `Annotated` type, allowing
    custom validation logic to be expressed concisely as a typed alias.

    Args:
        ty: The base type to wrap with a validator.
        mode: When the validator runs relative to Pydantic's built-in validation. `"before"` runs
            on the raw input, `"after"` runs on the validated value, `"wrap"` lets the validator
            invoke the inner validator manually.

    Returns:
        A decorator that takes a validator function and returns the annotated type.

    Raises:
        ValueError: If `mode` is not one of `"before"`, `"after"`, or `"wrap"`.
    """

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
    """Decorator factory that attaches a serializer function to a type.

    Args:
        ty: The base type to wrap with a serializer.
        mode: `"plain"` replaces Pydantic's default serializer entirely, `"wrap"` lets the
            function call the inner serializer to post-process its output.

    Returns:
        A decorator that takes a serializer function and returns the annotated type.

    Raises:
        ValueError: If `mode` is not one of `"plain"` or `"wrap"`.
    """

    def serialized_type(function: Callable[..., Any]) -> T:
        match mode:
            case "plain":
                return cast("T", Annotated[ty, PlainSerializer(function)])
            case "wrap":
                return cast("T", Annotated[ty, WrapSerializer(function)])
            case _:
                raise ValueError(f"Invalid mode: {mode}. Must be 'plain' or 'wrap'")

    return serialized_type
