"""Binary packing schemas and utilities."""

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

DEFAULT_BYTE_ORDER: ByteOrder = "<"
_BYTE_ORDERS: tuple[ByteOrder, ...] = ("<", ">", "=")
_STRUCT_FORMAT_ITEMS_REGEX = re.compile(r"(\d*?)([A-Za-z?x])")


@dataclass(frozen=True, kw_only=True)
class PackingSchema:
    type: ClassVar[type] = object
    symbol: ClassVar[str] = ""

    annotation: Any = MISSING
    order: ByteOrder | None = None
    padding_before: int | None = None
    padding_after: int | None = None
    packer: Callable[[Any], bytes] | None = None
    validator: Callable[[Any], Any] | None = None

    if TYPE_CHECKING:
        _structs: dict[ByteOrder, Struct] = field(init=False)
        format: str = field(init=False)
        size: int = field(init=False)

    def __post_init__(self) -> None:
        if self.order is not None and self.order not in _BYTE_ORDERS:
            raise ValueError(f"`{PackingSchema.__name__}.order` must be one of: {_BYTE_ORDERS}.")
        if self.padding_before is not None:
            if self.padding_before < 0 or not self.padding_before.is_integer():
                raise TypeError(
                    f"`{PackingSchema.__name__}.padding_before` must be a non-negative integer."
                )
        if self.padding_after is not None:
            if self.padding_after < 0 or not self.padding_after.is_integer():
                raise TypeError(
                    f"`{PackingSchema.__name__}.padding_after` must be a non-negative integer."
                )

        object.__setattr__(self, "_structs", {})
        object.__setattr__(self, "format", self._compute_format())
        object.__setattr__(self, "size", self.struct().size)

    def pack(self, instance: Any, /, order: ByteOrder | None = None) -> bytes:
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
        from ceres.data import validate

        packed = self.struct(order).unpack_from(data, offset)
        instance = packed[0]
        if self.validator is not None:
            instance = self.validator(instance)
        if validate_annotation and self.annotation is not MISSING:
            instance = validate(self.annotation, instance)

        return instance

    def struct(self, order: ByteOrder | None = None) -> Struct:
        order = self._resolve_order(order)
        struct = self._structs.get(order)
        if struct is None:
            struct = Struct(f"{order}{self.format}")
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
            format = f"{self.padding_before if self.padding_before != 1 else ''}x{format}"
        if self.padding_after:
            format = f"{format}{self.padding_after if self.padding_after != 1 else ''}x"

        return self._compact_format(format)

    def _compute_inner_format(self) -> str:
        return self.symbol

    @classmethod
    def _compact_format(cls, format: str) -> str:
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


@dataclass(frozen=True)
class PackedBytes(PackingSchema):
    type = bytes
    symbol = "s"
    length: int

    @override
    def __post_init__(self) -> None:
        super().__post_init__()

        if self.length < 1:
            raise TypeError(f"`{PackedBytes.__name__}.length` must be a positive integer.")

    @override
    def _compute_inner_format(self) -> str:
        if self.length == 0:
            return ""
        if self.length == 1:
            return self.symbol

        return f"{self.length}{self.symbol}"


@dataclass(frozen=True)
class PackedBool(PackingSchema):
    type = bool
    symbol = "?"


@dataclass(frozen=True)
class PackedUInt8(PackingSchema):
    type = int
    symbol = "B"


@dataclass(frozen=True)
class PackedInt8(PackingSchema):
    type = int
    symbol = "b"


@dataclass(frozen=True)
class PackedUInt16(PackingSchema):
    type = int
    symbol = "H"


@dataclass(frozen=True)
class PackedInt16(PackingSchema):
    type = int
    symbol = "h"


@dataclass(frozen=True)
class PackedUInt32(PackingSchema):
    type = int
    symbol = "I"


@dataclass(frozen=True)
class PackedInt32(PackingSchema):
    type = int
    symbol = "i"


@dataclass(frozen=True)
class PackedUInt64(PackingSchema):
    type = int
    symbol = "Q"


@dataclass(frozen=True)
class PackedInt64(PackingSchema):
    type = int
    symbol = "q"


@dataclass(frozen=True)
class PackedFloat16(PackingSchema):
    type = float
    symbol = "e"


@dataclass(frozen=True)
class PackedFloat32(PackingSchema):
    type = float
    symbol = "f"


@dataclass(frozen=True)
class PackedFloat64(PackingSchema):
    type = float
    symbol = "d"


@dataclass(frozen=True)
class PackedComplex64(PackingSchema):
    type = complex
    symbol = "F"


@dataclass(frozen=True)
class PackedComplex128(PackingSchema):
    type = complex
    symbol = "D"


@dataclass(frozen=True)
class PackedTuple(PackingSchema):
    type = tuple
    symbol = "t"
    values: tuple[PackingSchema, ...]

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
    type = object
    symbol = "m"
    model: type[Any]
    fields: Mapping[str, PackingSchema] = field(default_factory=dict)

    @override
    def __post_init__(self) -> None:
        super().__post_init__()

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


_struct_schema_cache: dict[Any, PackingSchema] = {}


def _infer_packing_schema(
    extracted: AnnotationInfo,
) -> PackingSchema | None:
    from ceres.data.object import _supports_pydantic_fields, fields_of

    annotated_type = extracted.type

    if not isinstance(annotated_type, type):
        return None

    if issubclass(annotated_type, bool):
        return PackedBool()
    if issubclass(annotated_type, int):
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
    cached = _struct_schema_cache.get(annotation)
    if cached is not None:
        return cached

    extracted = extract_annotation(annotation)

    schemas: list[PackingSchema] = []

    for current in extracted.metadata:
        if isinstance(current, PackingSchema):
            schemas.append(current)
        elif lenient_issubclass(current, PackingSchema):
            try:
                schemas.append(current())
            except Exception as exception:
                raise TypeError(
                    f"Failed to instantiate packing schema class `{current}` in `{annotation}`: "
                    f"{exception}"
                ) from exception

    schema_subclass_instances = list(
        schema for schema in schemas if type(schema) is not PackingSchema
    )
    if not schema_subclass_instances:
        inferred = _infer_packing_schema(extracted)
        if inferred is None:
            raise TypeError(f"Failed to infer packing schema for `{annotation}`.")

        schemas = [inferred, *schemas]

    if len(schemas) == 1:
        schema = schemas[0]
    else:
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
    """
    Serialize a value into binary data using the given packing type/schema. If no schema is
    provided, a schema will be inferred from the type of `value`.
    """
    if schema is None:
        schema = packed(type(value))
    elif not isinstance(schema, PackingSchema):
        schema = packed(schema)

    return schema.pack(value)


def unpack(schema: FieldInfo | TypeInput | PackingSchema, data: bytes, /, offset: int = 0) -> Any:
    """
    Deserialize an instance of the given type/schema from binary data.
    """
    if not isinstance(schema, PackingSchema):
        schema = packed(schema)

    return schema.unpack(data, offset)


def packable[T: type[Any]](type: T, /) -> T:
    """Decorator for ensuring a class is binary-packable."""
    try:
        packed(type)
    except Exception as exception:
        from traceback import format_exception

        raise TypeError(
            f"Type `{type}` is not binary-packable. {format_exception(exception)}"
        ) from exception

    return type


type Int8 = Annotated[int, PackedInt8(), Ge(-128), Le(127)]
type Int16 = Annotated[int, PackedInt16(), Ge(-32768), Le(32767)]
type Int32 = Annotated[int, PackedInt32(), Ge(-2147483648), Le(2147483647)]
type Int64 = Annotated[int, PackedInt64(), Ge(-9223372036854775808), Le(9223372036854775807)]

type UInt8 = Annotated[int, PackedUInt8(), Ge(0), Le(255)]
type UInt16 = Annotated[int, PackedUInt16(), Ge(0), Le(65535)]
type UInt32 = Annotated[int, PackedUInt32(), Ge(0), Le(4294967295)]
type UInt64 = Annotated[int, PackedUInt64(), Ge(0), Le(18446744073709551615)]

type Byte = UInt8

type Float16 = Annotated[float, PackedFloat16()]
type Float32 = Annotated[float, PackedFloat32()]
type Float64 = Annotated[float, PackedFloat64()]

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
