"""Binary packing schemas and utilities.

Provides a layered API for converting Python objects to and from raw bytes for binary protocols. At
the lowest level, `PackingSchema` subclasses (`PackedUInt8`, `PackedFloat32`, `PackedBytes`, etc.)
wrap Python's `struct` module to define the wire format of individual fields. At a higher level,
`pack` and `unpack` accept a type annotation (e.g. a `Pydantic` model or a typed `Annotated` alias)
and infer the appropriate schema automatically.

Type aliases like `UInt8`, `Int32`, and `Float64` combine a numeric type with the right packing
schema and a value-range constraint, making them suitable for use as Pydantic model fields.
"""

__all__ = (
    "ByteOrder",
    "DEFAULT_BYTE_ORDER",
    "PackingSchema",
    "Packed",
    "PackedBytes",
    "PackedBool",
    "PackedUInt8",
    "PackedInt8",
    "PackedUInt16",
    "PackedInt16",
    "PackedUInt32",
    "PackedInt32",
    "PackedUInt64",
    "PackedInt64",
    "PackedFloat16",
    "PackedFloat32",
    "PackedFloat64",
    "PackedComplex64",
    "PackedComplex128",
    "PackedTuple",
    "PackedModel",
    "packed",
    "pack",
    "unpack",
    "packable",
    "Int8",
    "Int16",
    "Int32",
    "Int64",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
    "Byte",
    "Float16",
    "Float32",
    "Float64",
    "BytesEncoding",
    "BytesErrorHandling",
    "BytesEncodingErrorHandling",
    "BytesDecodingErrorHandling",
    "BytesFromString",
    "BytesToString",
)

import re
from collections.abc import Callable, Mapping
from copy import replace
from dataclasses import dataclass, field, is_dataclass
from struct import Struct
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Literal,
    TypeAlias,
    TypeAliasType,
    cast,
    override,
)

from annotated_types import Ge, Le
from pydantic import BeforeValidator, PlainSerializer
from pydantic_core import MISSING

from ceres.__internal__.utilities.typing import (
    AnnotationInfo,
    extract_annotation,
    lenient_issubclass,
)

if TYPE_CHECKING:
    from types import FunctionType, GenericAlias, UnionType

    from pydantic.fields import FieldInfo
    from pydantic_core.core_schema import WhenUsed
    from typing_extensions import TypeForm

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
else:
    TypeInput = Any


ByteOrder = Literal["<", ">", "="]
"""Byte order specifier matching Python's `struct` module conventions.

`"<"` selects little-endian, `">"` selects big-endian, `"="` selects native byte order without
alignment.
"""

DEFAULT_BYTE_ORDER: ByteOrder = "<"
"""Default byte order used when no explicit order is provided, little-endian to match common binary
protocols on x86 and ARM platforms."""

_BYTE_ORDERS: tuple[ByteOrder, ...] = ("<", ">", "=")

# Matches one item in a `struct` format string, capturing the optional repeat count and the type
# symbol (e.g. `"4s"` -> ("4", "s")).
_STRUCT_FORMAT_ITEMS_REGEX = re.compile(r"(\d*?)([A-Za-z?x])")


@dataclass(frozen=True, kw_only=True)
class PackingSchema:
    """Base class for binary packing schemas describing how a value is laid out in bytes.

    Each subclass wraps a `struct` format symbol and exposes `pack` and `unpack` operations.
    Subclasses are expected to declare their `type` (the Python type the schema represents) and
    `symbol` (the `struct` format character) as class variables.
    """

    type: ClassVar[type] = object
    symbol: ClassVar[str] = ""

    annotation: Any = MISSING
    """The original type annotation this schema was inferred from, used to perform additional
    Pydantic validation after unpacking. `MISSING` if not derived from an annotation."""
    order: ByteOrder | None = None
    """Optional byte order override. When `None`, falls back to the order passed to `pack`/`unpack`,
    then to `DEFAULT_BYTE_ORDER`."""
    padding_before: int | None = None
    """Number of pad bytes inserted before the value when packed."""
    padding_after: int | None = None
    """Number of pad bytes inserted after the value when packed."""
    packer: Callable[[Any], bytes] | None = None
    """Optional custom packer function called instead of the default `struct` packing."""
    validator: Callable[[Any], Any] | None = None
    """Optional callable applied to the unpacked value before annotation validation."""

    if TYPE_CHECKING:
        # Computed in `__post_init__`, declared here only for type checkers.
        _structs: dict[ByteOrder, Struct] = field(init=False)
        format: str = field(init=False)
        size: int = field(init=False)

    def __post_init__(self) -> None:
        if self.order is not None and self.order not in _BYTE_ORDERS:
            raise ValueError(f"`{PackingSchema.__name__}.order` must be one of: {_BYTE_ORDERS}.")
        if self.padding_before is not None and self.padding_before < 0:
            raise TypeError(
                f"`{PackingSchema.__name__}.padding_before` must be a non-negative integer."
            )
        if self.padding_after is not None and self.padding_after < 0:
            raise TypeError(
                f"`{PackingSchema.__name__}.padding_after` must be a non-negative integer."
            )

        # Bypass `frozen=True` to populate computed fields. The struct cache starts empty and is
        # populated lazily by `struct()` keyed on byte order.
        object.__setattr__(self, "_structs", {})
        object.__setattr__(self, "format", self._compute_format())
        object.__setattr__(self, "size", self.struct().size)

    def pack(self, instance: Any, /, order: ByteOrder | None = None) -> bytes:
        """Serialize an instance to its binary representation.

        Args:
            instance: The Python value to pack.
            order: Byte order to use, falling back to the schema's configured order, then to
                `DEFAULT_BYTE_ORDER`.

        Returns:
            The packed binary representation of `instance`.
        """
        if self.packer is not None:
            return self.packer(instance)

        return self.struct(order).pack(instance)

    def unpack(
        self,
        data: bytes,
        /,
        offset: int = 0,
        order: ByteOrder | None = None,
        *,
        validate_annotation: bool = True,
    ) -> Any:
        """Deserialize an instance from its binary representation.

        Args:
            data: The byte buffer to read from.
            offset: Number of bytes to skip in `data` before reading.
            order: Byte order to use for unpacking.
            validate_annotation: When `True` and the schema was derived from a type annotation,
                run Pydantic validation against that annotation after unpacking. Disabled by
                composite schemas (`PackedTuple`, `PackedModel`) so they can validate the entire
                composite value once instead of validating each field.

        Returns:
            The unpacked Python value.
        """
        from ceres.data import validate

        packed = self.struct(order).unpack_from(data, offset)
        instance = packed[0]
        if self.validator is not None:
            instance = self.validator(instance)
        if validate_annotation and self.annotation is not MISSING:
            instance = validate(self.annotation, instance)

        return instance

    def struct(self, order: ByteOrder | None = None) -> Struct:
        """Get a `Struct` object for this schema in the given byte order.

        Cached per byte order so subsequent calls with the same order reuse the same `Struct`
        instance.

        Args:
            order: Byte order to build the `Struct` for, defaults to the schema's resolved order.

        Returns:
            A `Struct` whose format string includes the byte order prefix.
        """
        order = self._resolve_order(order)
        struct = self._structs.get(order)
        if struct is None:
            struct = Struct(f"{order}{self.format}")
            # Use `setdefault` to handle the race where another thread builds and caches the
            # `Struct` between our `get` and `set`.
            struct = self._structs.setdefault(order, struct)

        return struct

    def _resolve_order(self, order: ByteOrder | None) -> ByteOrder:
        if order is None:
            order = self.order
        if order is None:
            order = DEFAULT_BYTE_ORDER

        return order

    def _compute_format(self) -> str:
        format = self._compute_inner_format()
        if self.padding_before:
            # Use `Nx` for N > 1 pad bytes, the bare `x` for a single pad byte to keep the format
            # string compact.
            format = f"{self.padding_before if self.padding_before != 1 else ''}x{format}"
        if self.padding_after:
            format = f"{format}{self.padding_after if self.padding_after != 1 else ''}x"

        return self._compact_format(format)

    def _compute_inner_format(self) -> str:
        """Return the `struct` format string for this schema, excluding padding."""
        return self.symbol

    @classmethod
    def _compact_format(cls, format: str) -> str:
        """Combine adjacent identical format symbols by summing their counts.

        For example, `"xxBB"` becomes `"2x2B"`. The `"s"` symbol (bytes) is intentionally never
        merged because in `struct` it represents a single fixed-length field rather than a repeated
        value.
        """
        compacted: list[str] = []
        pairs: list[tuple[int, str]] = []

        for match in _STRUCT_FORMAT_ITEMS_REGEX.finditer(format):
            count_text, symbol = match.group(1), match.group(2)
            count = int(count_text) if count_text else 1
            if symbol != "s" and pairs and pairs[-1][1] == symbol:
                pairs[-1] = (pairs[-1][0] + count, symbol)
            else:
                pairs.append((count, symbol))

        for count, symbol in pairs:
            compacted.append(f"{count}{symbol}" if count > 1 else symbol)

        return "".join(compacted)


Packed: TypeAlias = PackingSchema
"""Convenience alias for `PackingSchema`, intended for use as an `Annotated` metadata marker."""


@dataclass(frozen=True)
class PackedBytes(PackingSchema):
    """Schema for a fixed-length sequence of raw bytes."""

    type = bytes
    symbol = "s"
    length: int
    """Number of bytes in the field. Must be a positive integer."""

    @override
    def __post_init__(self) -> None:
        super().__post_init__()

        if self.length < 1:
            raise TypeError(f"`{PackedBytes.__name__}.length` must be a positive integer.")

    @override
    def _compute_inner_format(self) -> str:
        if self.length == 1:
            return self.symbol

        return f"{self.length}{self.symbol}"


@dataclass(frozen=True)
class PackedBool(PackingSchema):
    """Schema for a single-byte boolean value, packed as `?` in `struct` format."""

    type = bool
    symbol = "?"


@dataclass(frozen=True)
class PackedUInt8(PackingSchema):
    """Schema for an 8-bit unsigned integer."""

    type = int
    symbol = "B"


@dataclass(frozen=True)
class PackedInt8(PackingSchema):
    """Schema for an 8-bit signed integer."""

    type = int
    symbol = "b"


@dataclass(frozen=True)
class PackedUInt16(PackingSchema):
    """Schema for a 16-bit unsigned integer."""

    type = int
    symbol = "H"


@dataclass(frozen=True)
class PackedInt16(PackingSchema):
    """Schema for a 16-bit signed integer."""

    type = int
    symbol = "h"


@dataclass(frozen=True)
class PackedUInt32(PackingSchema):
    """Schema for a 32-bit unsigned integer."""

    type = int
    symbol = "I"


@dataclass(frozen=True)
class PackedInt32(PackingSchema):
    """Schema for a 32-bit signed integer."""

    type = int
    symbol = "i"


@dataclass(frozen=True)
class PackedUInt64(PackingSchema):
    """Schema for a 64-bit unsigned integer."""

    type = int
    symbol = "Q"


@dataclass(frozen=True)
class PackedInt64(PackingSchema):
    """Schema for a 64-bit signed integer."""

    type = int
    symbol = "q"


@dataclass(frozen=True)
class PackedFloat16(PackingSchema):
    """Schema for a 16-bit IEEE 754 half-precision float."""

    type = float
    symbol = "e"


@dataclass(frozen=True)
class PackedFloat32(PackingSchema):
    """Schema for a 32-bit IEEE 754 single-precision float."""

    type = float
    symbol = "f"


@dataclass(frozen=True)
class PackedFloat64(PackingSchema):
    """Schema for a 64-bit IEEE 754 double-precision float."""

    type = float
    symbol = "d"


@dataclass(frozen=True)
class PackedComplex64(PackingSchema):
    """Schema for a complex number with 32-bit real and imaginary parts."""

    type = complex
    symbol = "F"


@dataclass(frozen=True)
class PackedComplex128(PackingSchema):
    """Schema for a complex number with 64-bit real and imaginary parts."""

    type = complex
    symbol = "D"


@dataclass(frozen=True)
class PackedTuple(PackingSchema):
    """Schema for a fixed-length heterogeneous tuple of packed values."""

    type = tuple
    symbol = "t"
    values: tuple[PackingSchema, ...]
    """Schema for each element of the tuple, in positional order."""

    @override
    def pack(self, instance: Any, /, order: ByteOrder | None = None) -> bytes:
        order = self._resolve_order(order)
        packed = bytearray()
        for value, schema in zip(instance, self.values):
            packed.extend(schema.pack(value, order))

        return bytes(packed)

    @override
    def unpack(
        self,
        data: bytes,
        /,
        offset: int = 0,
        order: ByteOrder | None = None,
        *,
        validate_annotation: bool = True,
    ) -> Any:
        from ceres.data import validate

        order = self._resolve_order(order)

        values: list[Any] = []
        for schema in self.values:
            # Skip per-element annotation validation, the assembled tuple is validated against the
            # outer annotation below if one is set.
            values.append(schema.unpack(data, offset, order, validate_annotation=False))
            offset += schema.size

        instance = tuple(values)
        if self.validator is not None:
            instance = self.validator(instance)
        if validate_annotation and self.annotation is not MISSING:
            instance = validate(self.annotation, instance)

        return instance

    @override
    def _compute_inner_format(self) -> str:
        return "".join(schema.format for schema in self.values)


@dataclass(frozen=True)
class PackedModel(PackingSchema):
    """Schema for a Pydantic model or dataclass packed as a sequence of its fields."""

    type = object
    symbol = "m"
    model: type[Any]
    """The model class to pack and unpack."""
    fields: Mapping[str, PackingSchema] = field(default_factory=dict)
    """Mapping from field name to its packing schema, defining the wire order of fields."""

    @override
    def __post_init__(self) -> None:
        super().__post_init__()

        # Allow models to declare a default byte order via the `__byte_order__` class attribute.
        # Only use it when the schema doesn't already have an explicit order set.
        if self.order is None:
            order = getattr(self.model, "__byte_order__", None)
            if order is not None:
                if order not in _BYTE_ORDERS:
                    raise TypeError(
                        f"{self.__class__}.__byte_order__ must be one of: {list(_BYTE_ORDERS)}."
                    )

                object.__setattr__(self, "order", order)

    @override
    def pack(self, instance: Any, /, order: ByteOrder | None = None) -> bytes:
        order = self._resolve_order(order)
        data = bytearray()
        for field, schema in self.fields.items():
            data.extend(schema.pack(getattr(instance, field), order))

        return bytes(data)

    @override
    def unpack(
        self,
        data: bytes,
        /,
        offset: int = 0,
        order: ByteOrder | None = None,
        *,
        validate_annotation: bool = True,  # Models are always validated.
    ) -> Any:
        from ceres.data import validate

        order = self._resolve_order(order)

        arguments = {}
        for field, schema in self.fields.items():
            # Defer per-field annotation validation, validating the assembled instance once below
            # is sufficient and avoids duplicate work.
            arguments[field] = schema.unpack(data, offset, order, validate_annotation=False)
            offset += schema.size

        instance = validate(self.model, arguments)
        if self.validator is not None:
            instance = self.validator(instance)
        if validate_annotation and self.annotation is not MISSING:
            instance = validate(self.annotation, instance)

        return instance

    @override
    def _compute_inner_format(self) -> str:
        return "".join(schema.format for schema in self.fields.values())


# Cache of inferred schemas keyed on type annotation, avoids re-running the inference machinery
# (which walks Pydantic field metadata) on every pack/unpack call.
_struct_schema_cache: dict[Any, PackingSchema] = {}


def _infer_packing_schema(
    extracted: AnnotationInfo,
) -> PackingSchema | None:
    """Infer a packing schema from an annotation's underlying type, returning `None` on failure."""
    from ceres.data.object import _supports_pydantic_fields, fields_of

    annotated_type = extracted.type

    if not isinstance(annotated_type, type):
        return None

    if issubclass(annotated_type, bool):
        return PackedBool()
    if issubclass(annotated_type, int):
        # Default to 64 bits for plain `int`, narrower types must be requested explicitly via the
        # type aliases below (e.g. `UInt8`, `Int32`).
        return PackedInt64()
    if issubclass(annotated_type, float):
        return PackedFloat64()
    if lenient_issubclass(annotated_type, complex):
        return PackedComplex128()
    if lenient_issubclass(annotated_type, tuple):
        values = extracted.generic_args
        if any(value is Ellipsis for value in values):
            raise TypeError(
                f"Cannot infer packing schema for `{extracted.annotation}`. Tuple fields must have "
                "a specific number of items, meaning they cannot contain `...`."
            )
        if not values:
            raise TypeError(
                f"Cannot infer packing schema for field `{extracted.annotation}` because it is a tuple"
                "with no specified item types. Either specify an item types or provide an "
                "explicit packing schema."
            )

        return PackedTuple(values=tuple(packed(value) for value in values))

    if _supports_pydantic_fields(annotated_type) or is_dataclass(annotated_type):
        return PackedModel(
            cast("type", annotated_type),
            {field: packed(info) for field, info in fields_of(annotated_type).items()},
        )

    return None


def packed(annotation: FieldInfo | TypeInput) -> PackingSchema:
    """Build (or fetch from cache) the `PackingSchema` for a type annotation.

    Walks the annotation's metadata looking for explicit `PackingSchema` markers. If one is found,
    it is used directly, otherwise the schema is inferred from the underlying type. Multiple
    schemas of the same kind may appear in the metadata, in which case their non-default fields
    are merged into a single schema.

    Args:
        annotation: A Pydantic `FieldInfo`, a type, or a type form to derive a schema for.

    Returns:
        The cached or freshly-built schema describing how values of `annotation` are laid out.

    Raises:
        TypeError: If no schema can be inferred, if multiple incompatible schemas are present, or
            if the inferred type does not match the schema's expected `type`.
    """
    cached = _struct_schema_cache.get(annotation)
    if cached is not None:
        return cached

    extracted = extract_annotation(annotation)

    schemas: list[PackingSchema] = []

    for current in extracted.metadata:
        if isinstance(current, PackingSchema):
            schemas.append(current)
        elif lenient_issubclass(current, PackingSchema):
            # Allow bare schema classes (e.g. `PackedUInt8` rather than `PackedUInt8()`) by
            # instantiating them with default arguments.
            try:
                schemas.append(current())
            except Exception as exception:
                raise TypeError(
                    f"Failed to instantiate packing schema class `{current}` in `{annotation}`: "
                    f"{exception}"
                ) from exception

    # Filter out bare `PackingSchema` instances, only proper subclasses count as concrete schemas.
    schema_subclass_instances = list(
        schema for schema in schemas if type(schema) is not PackingSchema
    )
    if not schema_subclass_instances:
        inferred = _infer_packing_schema(extracted)
        if inferred is None:
            raise TypeError(f"Failed to infer packing schema for `{annotation}`.")

        # Place the inferred concrete schema first so its fields take precedence during the merge.
        schemas = [inferred, *schemas]

    if len(schemas) == 1:
        schema = schemas[0]
    else:
        # Merge multiple schemas by combining their non-default field values into a single
        # instance. All concrete schemas must be of the same subclass to merge cleanly.
        schema_class = type(schema_subclass_instances[0])
        schema_arguments = {}

        for inherited_schema in schemas:
            if type(inherited_schema) is not PackingSchema and not isinstance(
                inherited_schema, schema_class
            ):
                raise TypeError(
                    f"Multiple packing schemas of different types found for "
                    f"`{annotation}`. All schemas must be of the same type or be a bare "
                    f"`{PackingSchema.__name__}`. Currently defined non-bare packing schemas "
                    f"are {schema_subclass_instances}."
                )

            from ceres.data import to_items

            for inherited_field, inherited_value in to_items(inherited_schema):
                if inherited_value not in (None, MISSING):
                    schema_arguments[inherited_field] = inherited_value

        schema = schema_class(**schema_arguments)

    if schema.annotation is MISSING:
        # Stamp the annotation onto the schema so `unpack` can validate against it later.
        schema = replace(schema, annotation=annotation)

    if schema.validator is None:
        if not lenient_issubclass(extracted.type, schema.type):
            raise TypeError(
                f"`{annotation}` has packing schema {schema!r} but is not annotated as a subclass "
                f"of `{schema.type}`. Either change the type or add a `validator` to the "
                "annotation's packing schema."
            )

    return _struct_schema_cache.setdefault(annotation, schema)


def pack(
    value: Any,
    schema: TypeInput | FieldInfo | PackingSchema | None = None,
    /,
) -> bytes:
    """Serialize a value into binary data using the given packing type or schema.

    Args:
        value: The Python value to serialize.
        schema: An explicit `PackingSchema`, a Pydantic `FieldInfo`, or a type to derive a schema
            from. When `None`, infers a schema from `type(value)`.

    Returns:
        The packed binary representation of `value`.
    """
    if schema is None:
        schema = packed(type(value))
    elif not isinstance(schema, PackingSchema):
        schema = packed(schema)

    return schema.pack(value)


def unpack(schema: FieldInfo | TypeInput | PackingSchema, data: bytes, /, offset: int = 0) -> Any:
    """Deserialize an instance of the given type or schema from binary data.

    Args:
        schema: An explicit `PackingSchema`, a Pydantic `FieldInfo`, or a type to derive a schema
            from.
        data: The byte buffer to read from.
        offset: Number of bytes to skip in `data` before reading.

    Returns:
        The unpacked Python value.
    """
    if not isinstance(schema, PackingSchema):
        schema = packed(schema)

    return schema.unpack(data, offset)


def packable[T: type[Any]](type: T, /) -> T:
    """Class decorator that asserts a type is binary-packable at decoration time.

    Useful for catching schema inference failures eagerly rather than waiting for the first
    `pack`/`unpack` call to fail at runtime.

    Args:
        type: The class to verify.

    Returns:
        The decorated class, unchanged.

    Raises:
        TypeError: If a packing schema cannot be inferred for `type`.
    """
    try:
        packed(type)
    except Exception as exception:
        from traceback import format_exception

        raise TypeError(
            f"Type `{type}` is not binary-packable. {format_exception(exception)}"
        ) from exception

    return type


type Int8 = Annotated[int, PackedInt8(), Ge(-128), Le(127)]
"""Signed 8-bit integer constrained to its valid range."""

type Int16 = Annotated[int, PackedInt16(), Ge(-32768), Le(32767)]
"""Signed 16-bit integer constrained to its valid range."""

type Int32 = Annotated[int, PackedInt32(), Ge(-2147483648), Le(2147483647)]
"""Signed 32-bit integer constrained to its valid range."""

type Int64 = Annotated[int, PackedInt64(), Ge(-9223372036854775808), Le(9223372036854775807)]
"""Signed 64-bit integer constrained to its valid range."""

type UInt8 = Annotated[int, PackedUInt8(), Ge(0), Le(255)]
"""Unsigned 8-bit integer constrained to its valid range."""

type UInt16 = Annotated[int, PackedUInt16(), Ge(0), Le(65535)]
"""Unsigned 16-bit integer constrained to its valid range."""

type UInt32 = Annotated[int, PackedUInt32(), Ge(0), Le(4294967295)]
"""Unsigned 32-bit integer constrained to its valid range."""

type UInt64 = Annotated[int, PackedUInt64(), Ge(0), Le(18446744073709551615)]
"""Unsigned 64-bit integer constrained to its valid range."""

type Byte = UInt8
"""Single byte value, alias for `UInt8`."""

type Float16 = Annotated[float, PackedFloat16()]
"""IEEE 754 half-precision float (16 bits)."""

type Float32 = Annotated[float, PackedFloat32()]
"""IEEE 754 single-precision float (32 bits)."""

type Float64 = Annotated[float, PackedFloat64()]
"""IEEE 754 double-precision float (64 bits)."""

type BytesEncoding = (
    Literal[
        "ascii",
        "utf-8",
        "latin-1",
        "base-64",
    ]
    | str
)
"""Encoding name for converting between strings and bytes, accepts any encoding Python supports."""

type BytesErrorHandling = Literal[
    "strict",
    "ignore",
    "replace",
    "backslashreplace",
    "surrogateescape",
    "surrogatepass",
]
"""Error handling modes shared by both encoding and decoding."""

type BytesEncodingErrorHandling = (
    BytesErrorHandling
    | Literal[
        "xmlcharrefreplace",
        "namereplace",
    ]
)
"""Error handling modes valid when encoding text into bytes."""

type BytesDecodingErrorHandling = BytesErrorHandling
"""Error handling modes valid when decoding bytes into text."""


def _normalize_encoding(encoding: BytesEncoding) -> BytesEncoding:
    # Strip case and separators so `"base-64"`, `"BASE_64"`, and `"base64"` all compare equal.
    return encoding.lower().replace("-", "").replace("_", "")


def BytesFromString(
    encoding: BytesEncoding,
    errors: BytesEncodingErrorHandling = "strict",
) -> BeforeValidator:
    """Pydantic validator that decodes incoming `str` values to `bytes`.

    Use as `Annotated[bytes, BytesFromString("utf-8")]` to accept either bytes or strings as input.
    The `"base-64"` encoding name (or any spelling normalized to `"base64"`) is special-cased to use
    base64 decoding instead of text encoding.

    Args:
        encoding: The text encoding to use, or `"base-64"` for base64 decoding.
        errors: Error handling mode applied during conversion.

    Returns:
        A `BeforeValidator` suitable for placement in an `Annotated` type.
    """
    if _normalize_encoding(encoding) == "base64":
        from base64 import b64decode

        def convert(value: str) -> bytes:
            return b64decode(value)
    else:

        def convert(value: str) -> bytes:
            return value.encode(encoding, errors)

    def BytesFromString(value: Any) -> Any:
        if isinstance(value, str):
            return convert(value)

        return value

    return BeforeValidator(BytesFromString, str)


def BytesToString(
    encoding: BytesEncoding,
    errors: BytesDecodingErrorHandling = "strict",
    when_used: WhenUsed = "json-unless-none",
) -> PlainSerializer:
    """Pydantic serializer that encodes `bytes` values to `str` for output.

    Mirrors `BytesFromString`, the `"base-64"` encoding name uses base64 encoding instead of text
    decoding.

    Args:
        encoding: The text encoding to use, or `"base-64"` for base64 encoding.
        errors: Error handling mode applied during conversion.
        when_used: Pydantic's `WhenUsed` setting controlling when the serializer runs (e.g. only
            for JSON output, always, etc.).

    Returns:
        A `PlainSerializer` suitable for placement in an `Annotated` type.
    """
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
