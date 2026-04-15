"""Tests for binary packing schemas and related utilities in ceres.data."""

import struct
from typing import Annotated

import pytest

from ceres.data import (
    Byte,
    DataObject,
    Float32,
    Float64,
    Int8,
    Int16,
    Int32,
    Int64,
    PackedBool,
    PackedBytes,
    PackedComplex64,
    PackedComplex128,
    PackedFloat16,
    PackedFloat32,
    PackedFloat64,
    PackedInt8,
    PackedInt16,
    PackedInt32,
    PackedInt64,
    PackedModel,
    PackedTuple,
    PackedUInt8,
    PackedUInt16,
    PackedUInt32,
    PackedUInt64,
    PackingSchema,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    pack,
    packable,
    packed,
    unpack,
)


class TestPackingSchema:
    def test_default_post_init(self):
        schema = PackedUInt8()
        assert schema.format is not None
        assert schema.size > 0

    def test_invalid_byte_order_raises(self):
        with pytest.raises(ValueError, match="order"):
            PackedUInt8(order="!")  # type: ignore[arg-type]

    def test_valid_byte_orders(self):
        for order in ("<", ">", "="):
            schema = PackedUInt8(order=order)
            assert schema.order == order

    def test_negative_padding_before_raises(self):
        with pytest.raises(TypeError, match="padding_before"):
            PackedUInt8(padding_before=-1)

    def test_negative_padding_after_raises(self):
        with pytest.raises(TypeError, match="padding_after"):
            PackedUInt8(padding_after=-1)

    def test_padding_before_adds_bytes(self):
        schema_no_pad = PackedUInt8()
        schema_padded = PackedUInt8(padding_before=3)
        assert schema_padded.size == schema_no_pad.size + 3

    def test_padding_after_adds_bytes(self):
        schema_no_pad = PackedUInt8()
        schema_padded = PackedUInt8(padding_after=5)
        assert schema_padded.size == schema_no_pad.size + 5

    def test_padding_both(self):
        schema = PackedUInt8(padding_before=2, padding_after=3)
        assert schema.size == 1 + 2 + 3  # uint8 is 1 byte

    def test_struct_caching(self):
        schema = PackedUInt32()
        s1 = schema.struct("<")
        s2 = schema.struct("<")
        assert s1 is s2

    def test_struct_different_orders_are_different(self):
        schema = PackedUInt32()
        s_le = schema.struct("<")
        s_be = schema.struct(">")
        assert s_le is not s_be

    def test_struct_defaults_to_little_endian(self):
        schema = PackedUInt32()
        s = schema.struct()
        assert s.format == "<I"

    def test_struct_respects_schema_order(self):
        schema = PackedUInt32(order=">")
        s = schema.struct()
        assert s.format == ">I"

    def test_custom_packer(self):
        def my_packer(value):
            return b"\xab\xcd"

        schema = PackedUInt8(packer=my_packer)
        result = schema.pack(42)
        assert result == b"\xab\xcd"

    def test_custom_validator_on_unpack(self):
        def double(value):
            return value * 2

        schema = PackedUInt8(validator=double)
        data = struct.pack("<B", 5)
        result = schema.unpack(data)
        assert result == 10

    def test_frozen(self):
        schema = PackedUInt8()
        with pytest.raises(AttributeError):
            schema.order = ">"  # type: ignore[misc]


class TestCompactFormat:
    def test_compact_merges_repeated_symbols(self):
        result = PackingSchema._compact_format("BBB")
        assert result == "3B"

    def test_compact_single_symbol(self):
        result = PackingSchema._compact_format("B")
        assert result == "B"

    def test_compact_mixed_symbols(self):
        result = PackingSchema._compact_format("BBhh")
        assert result == "2B2h"

    def test_compact_s_is_not_merged(self):
        # 's' (bytes) should not be merged because '3s' means 3-byte string
        result = PackingSchema._compact_format("sss")
        assert result == "sss"

    def test_compact_padding_merged(self):
        result = PackingSchema._compact_format("xxx")
        assert result == "3x"

    def test_compact_empty(self):
        result = PackingSchema._compact_format("")
        assert result == ""


class TestPackedBytes:
    def test_basic(self):
        schema = PackedBytes(length=4)
        data = schema.pack(b"test")
        assert schema.unpack(data) == b"test"

    def test_length_must_be_positive(self):
        with pytest.raises(TypeError, match="positive integer"):
            PackedBytes(length=0)

    def test_negative_length_raises(self):
        with pytest.raises(TypeError, match="positive integer"):
            PackedBytes(length=-1)

    def test_format_length_1(self):
        schema = PackedBytes(length=1)
        assert schema._compute_inner_format() == "s"

    def test_format_length_gt_1(self):
        schema = PackedBytes(length=5)
        assert schema._compute_inner_format() == "5s"

    def test_size(self):
        schema = PackedBytes(length=8)
        assert schema.size == 8


class TestPackedBool:
    def test_round_trip_true(self):
        schema = PackedBool()
        data = schema.pack(True)
        assert schema.unpack(data) is True

    def test_round_trip_false(self):
        schema = PackedBool()
        data = schema.pack(False)
        assert schema.unpack(data) is False

    def test_symbol(self):
        assert PackedBool.symbol == "?"

    def test_size(self):
        assert PackedBool().size == 1


class TestPackedIntegers:
    @pytest.mark.parametrize(
        "schema_cls, value, size",
        [
            (PackedUInt8, 0, 1),
            (PackedUInt8, 255, 1),
            (PackedInt8, -128, 1),
            (PackedInt8, 127, 1),
            (PackedUInt16, 0, 2),
            (PackedUInt16, 65535, 2),
            (PackedInt16, -32768, 2),
            (PackedInt16, 32767, 2),
            (PackedUInt32, 0, 4),
            (PackedUInt32, 4294967295, 4),
            (PackedInt32, -2147483648, 4),
            (PackedInt32, 2147483647, 4),
            (PackedUInt64, 0, 8),
            (PackedUInt64, 18446744073709551615, 8),
            (PackedInt64, -9223372036854775808, 8),
            (PackedInt64, 9223372036854775807, 8),
        ],
    )
    def test_round_trip(self, schema_cls, value, size):
        schema = schema_cls()
        assert schema.size == size
        data = schema.pack(value)
        assert len(data) == size
        result = schema.unpack(data)
        assert result == value

    @pytest.mark.parametrize(
        "schema_cls, symbol",
        [
            (PackedUInt8, "B"),
            (PackedInt8, "b"),
            (PackedUInt16, "H"),
            (PackedInt16, "h"),
            (PackedUInt32, "I"),
            (PackedInt32, "i"),
            (PackedUInt64, "Q"),
            (PackedInt64, "q"),
        ],
    )
    def test_symbol(self, schema_cls, symbol):
        assert schema_cls.symbol == symbol


class TestPackedFloats:
    @pytest.mark.parametrize(
        "schema_cls, size",
        [
            (PackedFloat16, 2),
            (PackedFloat32, 4),
            (PackedFloat64, 8),
        ],
    )
    def test_round_trip(self, schema_cls, size):
        schema = schema_cls()
        assert schema.size == size
        value = 3.14
        data = schema.pack(value)
        assert len(data) == size
        result = schema.unpack(data)
        # Float16/32 lose precision so just check approximate
        assert abs(result - value) < 0.1

    def test_float64_exact(self):
        schema = PackedFloat64()
        value = 1.23456789012345
        data = schema.pack(value)
        result = schema.unpack(data)
        assert result == value

    @pytest.mark.parametrize(
        "schema_cls, symbol",
        [
            (PackedFloat16, "e"),
            (PackedFloat32, "f"),
            (PackedFloat64, "d"),
        ],
    )
    def test_symbol(self, schema_cls, symbol):
        assert schema_cls.symbol == symbol


class TestPackedComplex:
    def test_complex64_round_trip(self):
        schema = PackedComplex64()
        value = complex(1.0, 2.0)
        data = schema.pack(value)
        result = schema.unpack(data)
        assert abs(result.real - value.real) < 0.01
        assert abs(result.imag - value.imag) < 0.01

    def test_complex128_round_trip(self):
        schema = PackedComplex128()
        value = complex(1.23456789, -9.87654321)
        data = schema.pack(value)
        result = schema.unpack(data)
        assert result == value

    def test_sizes(self):
        assert PackedComplex64().size == 8  # 2 x float32
        assert PackedComplex128().size == 16  # 2 x float64


class TestByteOrder:
    def test_little_endian(self):
        schema = PackedUInt32()
        data = schema.pack(1, order="<")
        assert data == b"\x01\x00\x00\x00"

    def test_big_endian(self):
        schema = PackedUInt32()
        data = schema.pack(1, order=">")
        assert data == b"\x00\x00\x00\x01"

    def test_unpack_with_order(self):
        schema = PackedUInt16()
        data_be = struct.pack(">H", 0x1234)
        result = schema.unpack(data_be, order=">")
        assert result == 0x1234


class TestPackedTuple:
    def test_basic_round_trip(self):
        schema = PackedTuple(values=(PackedUInt8(), PackedUInt16()))
        value = (42, 1000)
        data = schema.pack(value)
        result = schema.unpack(data)
        assert result == value

    def test_size_is_sum_of_parts(self):
        schema = PackedTuple(values=(PackedUInt8(), PackedUInt32(), PackedFloat64()))
        assert schema.size == 1 + 4 + 8

    def test_format_is_concatenated(self):
        schema = PackedTuple(values=(PackedUInt8(), PackedFloat32()))
        assert "B" in schema.format
        assert "f" in schema.format

    def test_offset(self):
        schema = PackedTuple(values=(PackedUInt8(), PackedUInt8()))
        prefix = b"\xff"  # 1 byte of junk
        payload = schema.pack((10, 20))
        data = prefix + payload
        result = schema.unpack(data, offset=1)
        assert result == (10, 20)

    def test_nested_tuples(self):
        inner = PackedTuple(values=(PackedUInt8(), PackedUInt8()))
        outer = PackedTuple(values=(inner, PackedFloat32()))
        value = ((1, 2), 3.0)
        data = outer.pack(value)
        result = outer.unpack(data)
        assert result[0] == (1, 2)
        assert abs(result[1] - 3.0) < 0.001

    def test_empty_tuple(self):
        schema = PackedTuple(values=())
        data = schema.pack(())
        assert data == b""
        result = schema.unpack(data)
        assert result == ()

    def test_custom_validator(self):
        def sort_it(value):
            return tuple(sorted(value))

        schema = PackedTuple(
            values=(PackedUInt8(), PackedUInt8(), PackedUInt8()),
            validator=sort_it,
        )
        data = schema.pack((3, 1, 2))
        result = schema.unpack(data)
        assert result == (1, 2, 3)


class TestPackedModel:
    def test_basic_round_trip(self):
        class Point(DataObject):
            x: Int32
            y: Int32

        schema = PackedModel(
            model=Point,
            fields={"x": PackedInt32(), "y": PackedInt32()},
        )
        point = Point(x=10, y=20)
        data = schema.pack(point)
        result = schema.unpack(data)
        assert result.x == 10
        assert result.y == 20

    def test_size(self):
        schema = PackedModel(
            model=object,
            fields={"a": PackedUInt8(), "b": PackedFloat64()},
        )
        assert schema.size == 1 + 8

    def test_format_combined(self):
        schema = PackedModel(
            model=object,
            fields={"a": PackedUInt8(), "b": PackedUInt16()},
        )
        assert "B" in schema.format
        assert "H" in schema.format


class TestInferPackingSchema:
    def test_infer_bool(self):
        schema = packed(bool)
        assert isinstance(schema, PackedBool)

    def test_infer_int(self):
        schema = packed(int)
        assert isinstance(schema, PackedInt64)

    def test_infer_float(self):
        schema = packed(float)
        assert isinstance(schema, PackedFloat64)

    def test_infer_complex(self):
        schema = packed(complex)
        assert isinstance(schema, PackedComplex128)

    def test_infer_annotated_int_with_schema(self):
        schema = packed(UInt8)
        assert isinstance(schema, PackedUInt8)

    def test_packed_tuple_constructed_directly(self):
        schema = PackedTuple(values=(packed(int), packed(float)))
        assert isinstance(schema, PackedTuple)
        assert len(schema.values) == 2
        assert isinstance(schema.values[0], PackedInt64)
        assert isinstance(schema.values[1], PackedFloat64)

    def test_infer_bare_tuple_generic(self):
        schema = packed(tuple[int, float])
        assert isinstance(schema, PackedTuple)
        assert len(schema.values) == 2
        assert isinstance(schema.values[0], PackedInt64)
        assert isinstance(schema.values[1], PackedFloat64)

    def test_infer_unpackable_type_raises(self):
        with pytest.raises(TypeError, match="Failed to infer"):
            packed(str)

    def test_caching(self):
        s1 = packed(int)
        s2 = packed(int)
        assert s1 is s2


class TestPackedAnnotatedMerging:
    def test_schema_with_order(self):
        schema = packed(Annotated[int, PackedUInt32(order=">")])
        assert isinstance(schema, PackedUInt32)
        assert schema.order == ">"

    def test_schema_with_padding(self):
        schema = packed(Annotated[int, PackedUInt16(padding_before=2, padding_after=1)])
        assert isinstance(schema, PackedUInt16)
        assert schema.padding_before == 2
        assert schema.padding_after == 1

    def test_validator_mismatch_without_validator_raises(self):
        with pytest.raises(TypeError, match="not annotated as a subclass"):
            packed(Annotated[str, PackedUInt8()])


class TestPack:
    def test_pack_int(self):
        result = pack(42)
        expected = struct.pack("<q", 42)
        assert result == expected

    def test_pack_bool_true(self):
        result = pack(True)
        expected = struct.pack("<?", True)
        assert result == expected

    def test_pack_bool_false(self):
        result = pack(False)
        expected = struct.pack("<?", False)
        assert result == expected

    def test_pack_float(self):
        result = pack(3.14)
        expected = struct.pack("<d", 3.14)
        assert result == expected

    def test_pack_complex(self):
        value = complex(1.5, -2.5)
        data = pack(value)
        result = unpack(complex, data)
        assert result == value

    def test_pack_with_explicit_uint8_schema(self):
        result = pack(200, PackedUInt8())
        expected = struct.pack("<B", 200)
        assert result == expected

    def test_pack_with_explicit_int32_schema(self):
        result = pack(-1000, PackedInt32())
        expected = struct.pack("<i", -1000)
        assert result == expected

    def test_pack_with_explicit_float64_schema(self):
        result = pack(3.14, PackedFloat64())
        expected = struct.pack("<d", 3.14)
        assert result == expected

    def test_pack_with_explicit_uint16_schema(self):
        result = pack(60000, PackedUInt16())
        expected = struct.pack("<H", 60000)
        assert result == expected

    def test_pack_round_trips_with_unpack(self):
        data = pack(12345)
        assert unpack(int, data) == 12345

    def test_pack_float_round_trips_with_unpack(self):
        data = pack(2.718)
        assert unpack(float, data) == 2.718

    def test_pack_bool_round_trips_with_unpack(self):
        data = pack(True)
        assert unpack(bool, data) is True


class TestPackUnpackFunctions:
    def test_unpack_int(self):
        data = struct.pack("<q", 42)
        result = unpack(int, data)
        assert result == 42

    def test_unpack_float(self):
        data = struct.pack("<d", 2.5)
        result = unpack(float, data)
        assert result == 2.5

    def test_unpack_with_offset(self):
        prefix = b"\x00\x00"
        payload = struct.pack("<d", 99.5)
        data = prefix + payload
        result = unpack(float, data, offset=2)
        assert result == 99.5

    def test_unpack_bool(self):
        data = struct.pack("<?", True)
        result = unpack(bool, data)
        assert result is True

    def test_unpack_annotated(self):
        data = struct.pack("<B", 200)
        result = unpack(Annotated[int, PackedUInt8()], data)
        assert result == 200


class TestPackable:
    def test_packable_type_returns_type(self):
        result = packable(int)
        assert result is int

    def test_non_packable_type_raises(self):
        with pytest.raises(TypeError, match="not binary-packable"):
            packable(str)


class TestTypeAliases:
    @pytest.mark.parametrize(
        "alias, schema_cls",
        [
            (Int8, PackedInt8),
            (Int16, PackedInt16),
            (Int32, PackedInt32),
            (Int64, PackedInt64),
            (UInt8, PackedUInt8),
            (UInt16, PackedUInt16),
            (UInt32, PackedUInt32),
            (UInt64, PackedUInt64),
            (Float32, PackedFloat32),
            (Float64, PackedFloat64),
        ],
    )
    def test_alias_uses_correct_schema(self, alias, schema_cls):
        schema = packed(alias)
        assert isinstance(schema, schema_cls)

    def test_byte_is_uint8(self):
        schema = packed(Byte)
        assert isinstance(schema, PackedUInt8)

    @pytest.mark.parametrize(
        "alias, value",
        [
            (Int8, 100),
            (Int16, 1000),
            (Int32, 100000),
            (Int64, 10**15),
            (UInt8, 200),
            (UInt16, 60000),
            (UInt32, 3_000_000_000),
            (UInt64, 10**18),
        ],
    )
    def test_int_alias_round_trip(self, alias, value):
        schema = packed(alias)
        data = schema.pack(value)
        result = schema.unpack(data)
        assert result == value

    @pytest.mark.parametrize(
        "alias, value",
        [
            (Float32, 1.5),
            (Float64, 1.23456789012345),
        ],
    )
    def test_float_alias_round_trip(self, alias, value):
        schema = packed(alias)
        data = schema.pack(value)
        result = schema.unpack(data)
        if alias is Float32:
            assert abs(result - value) < 1e-6
        else:
            assert result == value


class TestDataObjectPacking:
    def test_infer_data_object_model(self):
        class Pair(DataObject):
            a: UInt8
            b: UInt16

        schema = packed(Pair)
        assert isinstance(schema, PackedModel)
        assert schema.size == 1 + 2

    def test_data_object_round_trip(self):
        class Pair(DataObject):
            a: UInt8
            b: UInt16

        schema = packed(Pair)
        instance = Pair(a=10, b=5000)
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.a == 10
        assert result.b == 5000

    def test_nested_data_objects(self):
        class Inner(DataObject):
            x: UInt8

        class Outer(DataObject):
            inner: Inner
            y: UInt16

        schema = packed(Outer)
        instance = Outer(inner=Inner(x=42), y=1000)
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.inner.x == 42
        assert result.y == 1000

    def test_tuple_field_in_data_object(self):
        class WithTuple(DataObject):
            pair: tuple[int, float]

        schema = packed(WithTuple)
        assert isinstance(schema, PackedModel)
        pair_schema = schema.fields["pair"]
        assert isinstance(pair_schema, PackedTuple)
        assert len(pair_schema.values) == 2

        instance = WithTuple(pair=(7, 3.14))
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.pair[0] == 7
        assert abs(result.pair[1] - 3.14) < 1e-10

    def test_tuple_field_with_explicit_schemas(self):
        class Coords(DataObject):
            xy: tuple[Int16, Int16]

        schema = packed(Coords)
        assert isinstance(schema, PackedModel)
        pair_schema = schema.fields["xy"]
        assert isinstance(pair_schema, PackedTuple)
        assert all(isinstance(v, PackedInt16) for v in pair_schema.values)
        assert pair_schema.size == 4

        instance = Coords(xy=(-100, 200))
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.xy == (-100, 200)

    def test_tuple_of_three_mixed_types(self):
        class Mixed(DataObject):
            values: tuple[bool, int, float]

        schema = packed(Mixed)
        assert isinstance(schema, PackedModel)
        values_schema = schema.fields["values"]
        assert isinstance(values_schema, PackedTuple)
        assert len(values_schema.values) == 3
        assert isinstance(values_schema.values[0], PackedBool)
        assert isinstance(values_schema.values[1], PackedInt64)
        assert isinstance(values_schema.values[2], PackedFloat64)

        instance = Mixed(values=(True, 42, 2.5))
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.values == (True, 42, 2.5)

    def test_nested_tuple_in_data_object(self):
        class Nested(DataObject):
            matrix_row: tuple[tuple[int, int], tuple[int, int]]

        schema = packed(Nested)
        assert isinstance(schema, PackedModel)
        row_schema = schema.fields["matrix_row"]
        assert isinstance(row_schema, PackedTuple)
        assert all(isinstance(v, PackedTuple) for v in row_schema.values)

        instance = Nested(matrix_row=((1, 2), (3, 4)))
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.matrix_row == ((1, 2), (3, 4))

    def test_data_object_with_tuple_and_scalars(self):
        class Record(DataObject):
            id: UInt32
            coords: tuple[Float32, Float32]
            flags: UInt8

        schema = packed(Record)
        assert schema.size == 4 + 4 + 4 + 1

        instance = Record(id=999, coords=(1.5, -2.5), flags=7)
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.id == 999
        assert abs(result.coords[0] - 1.5) < 1e-6
        assert abs(result.coords[1] - (-2.5)) < 1e-6
        assert result.flags == 7

    def test_deeply_nested_data_objects(self):
        class Leaf(DataObject):
            value: UInt8

        class Branch(DataObject):
            left: Leaf
            right: Leaf

        class Root(DataObject):
            branch: Branch
            tag: UInt16

        schema = packed(Root)
        assert schema.size == 1 + 1 + 2

        instance = Root(branch=Branch(left=Leaf(value=10), right=Leaf(value=20)), tag=5000)
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.branch.left.value == 10
        assert result.branch.right.value == 20
        assert result.tag == 5000

    def test_data_object_with_nested_model_and_tuple(self):
        class Point(DataObject):
            xy: tuple[Int16, Int16]

        class Segment(DataObject):
            start: Point
            end: Point

        schema = packed(Segment)
        assert schema.size == 4 + 4

        instance = Segment(start=Point(xy=(0, 10)), end=Point(xy=(100, -50)))
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.start.xy == (0, 10)
        assert result.end.xy == (100, -50)

    def test_many_fields_data_object(self):
        class Wide(DataObject):
            a: UInt8
            b: UInt16
            c: UInt32
            d: UInt64
            e: Float32
            f: Float64
            g: bool

        schema = packed(Wide)
        assert schema.size == 1 + 2 + 4 + 8 + 4 + 8 + 1

        instance = Wide(a=1, b=2, c=3, d=4, e=5.0, f=6.0, g=True)
        data = schema.pack(instance)
        result = schema.unpack(data)
        assert result.a == 1
        assert result.b == 2
        assert result.c == 3
        assert result.d == 4
        assert abs(result.e - 5.0) < 1e-6
        assert result.f == 6.0
        assert result.g is True

    def test_tuple_with_ellipsis_in_data_object_raises(self):
        class Bad(DataObject):
            items: tuple[int, ...]

        with pytest.raises(TypeError, match="cannot contain"):
            packed(Bad)

    def test_data_object_byte_order_round_trip(self):
        class Pair(DataObject):
            x: UInt16
            y: UInt16

        schema = packed(Pair)
        instance = Pair(x=0x1234, y=0xABCD)

        data_le = schema.pack(instance, order="<")
        data_be = schema.pack(instance, order=">")
        assert data_le != data_be

        result_le = schema.unpack(data_le, order="<")
        result_be = schema.unpack(data_be, order=">")
        assert result_le.x == 0x1234 and result_le.y == 0xABCD
        assert result_be.x == 0x1234 and result_be.y == 0xABCD


class TestEdgeCases:
    def test_zero_padding_does_not_add_size(self):
        schema = PackedUInt8(padding_before=0, padding_after=0)
        assert schema.size == 1

    def test_padding_before_1_format(self):
        schema = PackedUInt8(padding_before=1)
        assert "x" in schema.format

    def test_unpack_from_offset(self):
        schema = PackedUInt32()
        data = b"\x00" * 4 + struct.pack("<I", 12345)
        result = schema.unpack(data, offset=4)
        assert result == 12345

    def test_large_padding(self):
        schema = PackedUInt8(padding_before=100, padding_after=100)
        assert schema.size == 1 + 100 + 100
