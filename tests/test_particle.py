import re
import struct
from datetime import UTC, datetime
from re import DOTALL, VERBOSE, compile
from typing import Annotated, override

import pytest
from pydantic import Field

from ceres import Particle, ParticleData, RegexParticle
from ceres.__internal__.utilities.typing import get_generic_superclass_argument
from ceres.address import Address
from ceres.connection.buffer import Buffer
from ceres.data import Number, PackedBytes, UInt16, packable
from ceres.message import Message, MessageData
from ceres.particle import (
    BinaryRegexParticle,
    GroupedRegexParticle,
    ParseFailed,
)
from ceres.timing import utc
from tests import testing


def test_particle_subclassing():
    class MyParticleData(ParticleData):
        value: int

    class MyParticle(Particle[MyParticleData]):
        type = "my-particle"

    assert MyParticle.type == "my-particle"
    assert MyParticle.Data is MyParticleData

    class Subclass(MyParticle):
        type = "subclass"

    assert issubclass(Subclass, Particle)
    assert get_generic_superclass_argument(Subclass, Particle, 0) is MyParticleData
    assert Subclass.Data is MyParticleData
    assert Subclass.type == "subclass"

    class OtherData(ParticleData):
        value: str

    class WithGenericData[T: ParticleData](Particle[T]):
        __abstract__ = True

    assert WithGenericData[OtherData].Data is OtherData

    class WithAssignedGenericData(WithGenericData[OtherData]):
        type = "assigned-generic"

    assert issubclass(WithAssignedGenericData, Particle)
    assert WithAssignedGenericData.Data is OtherData
    assert WithAssignedGenericData.__data_object_fields__["data"].annotation is OtherData
    assert WithAssignedGenericData.type == "assigned-generic"


class TestRegexParticleAbstract:
    def test_cannot_instantiate_without_from_match(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(RegexParticle[Data]):
            type = "test/abstract"
            regex = compile(rb"(?P<value>\d+)")

        with pytest.raises(TypeError, match="from_match"):
            MyParticle(type="test/abstract", address="@test", data=Data(value=1))  # type: ignore[reportAbstractUsage]

    def test_from_bytes_returns_none_without_from_match(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(RegexParticle[Data]):
            type = "test/abstract-bytes"
            regex = compile(rb"(?P<value>\d+)")

        # Abstract from_match returns None, so from_bytes returns None.
        result = MyParticle.from_bytes(b"42", address=Address("@test"))
        assert result is None

    def test_subclass_with_custom_from_match_works(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(RegexParticle[Data]):
            type = "test/custom-match"
            regex = compile(rb"(?P<value>\d+)")

            @classmethod
            @override
            def from_match(cls, match, /, address=Address("@test"), timestamp=None):
                from ceres.data import construct, validate
                from ceres.timing import utc

                return construct(
                    cls,
                    type=cls.type,
                    address=address,
                    timestamp=utc(timestamp),
                    data=validate(cls.Data, match.groupdict()),
                    span=match.span(),
                )

        particle = MyParticle.from_bytes(b"42", address=Address("@test"))
        assert particle.data.value == 42


class TestGroupedRegexParticleFromBytes:
    def test_single_field(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/single"
            regex = compile(rb"(?P<value>\d+)")

        particle = MyParticle.from_bytes(b"42", address=Address("@test"))
        assert particle.data.value == 42
        assert particle.type == "test/single"

    def test_multiple_fields(self):
        class Data(ParticleData):
            name: str
            count: Number
            ratio: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/multi"
            regex = compile(rb"(?P<name>\w+),(?P<count>\d+),(?P<ratio>[\d.]+)")

        particle = MyParticle.from_bytes(b"sensor,100,3.14", address=Address("@test"))
        assert particle.data.name == "sensor"
        assert particle.data.count == 100
        assert particle.data.ratio == 3.14

    def test_no_match_raises_parse_failed(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/nomatch"
            regex = compile(rb"(?P<value>\d+)")

        with pytest.raises(ParseFailed, match="did not match"):
            MyParticle.from_bytes(b"not-a-number", address=Address("@test"))

    def test_preserves_address(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/address"
            regex = compile(rb"(?P<value>\d+)")

        address = Address("@sensor.gauge-1")
        particle = MyParticle.from_bytes(b"42", address=address)
        assert particle.address == address

    def test_preserves_timestamp(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/timestamp"
            regex = compile(rb"(?P<value>\d+)")

        timestamp = datetime(2024, 1, 1, tzinfo=UTC)
        particle = MyParticle.from_bytes(b"42", timestamp=timestamp, address=Address("@test"))
        assert particle.timestamp == timestamp

    def test_span_reflects_match(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/span"
            regex = compile(rb"(?P<value>\d+)")

        particle = MyParticle.from_bytes(b"42", address=Address("@test"))
        assert particle.span == (0, 2)

    def test_verbose_dotall_regex(self):
        class Data(ParticleData):
            key: str
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/verbose"
            regex = compile(
                rb"""
                (?P<key>\w+)
                =
                (?P<value>\d+)
                """,
                VERBOSE | DOTALL,
            )

        particle = MyParticle.from_bytes(b"temp=25", address=Address("@test"))
        assert particle.data.key == "temp"
        assert particle.data.value == 25


class TestGroupedRegexParticleFromMatch:
    def test_from_match_basic(self):
        class Data(ParticleData):
            x: Number
            y: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/match"
            regex = compile(rb"(?P<x>\d+),(?P<y>\d+)")

        match = MyParticle.regex.match(b"10,20")
        assert match is not None
        particle = MyParticle.from_match(match, address=Address("@test"))
        assert particle.data.x == 10
        assert particle.data.y == 20
        assert particle.span == (0, 5)

    def test_from_match_with_optional_group_present(self):
        class Data(ParticleData):
            prefix: str | None = None
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/opt-present"
            regex = compile(rb"(?P<prefix>[A-Z]+)?(?P<value>\d+)")

        match = MyParticle.regex.match(b"ABC123")
        assert match is not None
        particle = MyParticle.from_match(match, address=Address("@test"))
        assert particle.data.prefix == "ABC"
        assert particle.data.value == 123

    def test_from_match_with_optional_group_absent(self):
        class Data(ParticleData):
            prefix: str | None = None
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/opt-absent"
            regex = compile(rb"(?P<prefix>[A-Z]+)?(?P<value>\d+)")

        match = MyParticle.regex.match(b"456")
        assert match is not None
        particle = MyParticle.from_match(match, address=Address("@test"))
        assert particle.data.prefix is None
        assert particle.data.value == 456

    def test_from_match_validation_error_raises_parse_failed(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/validate-fail"
            regex = compile(rb"(?P<value>[a-z]+)")

        match = MyParticle.regex.match(b"abc")
        assert match is not None
        with pytest.raises(ParseFailed, match="validation failed"):
            MyParticle.from_match(match, address=Address("@test"))


class TestGroupedRegexParticleFromMessage:
    def test_from_message(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/message"
            regex = compile(rb"(?P<value>\d+)")

        message = Message(
            data=b"42",
            direction=Message.Direction.RECEIVE,
            address=Address("@test"),
        )
        particle = MyParticle.from_message(message)
        assert particle.data.value == 42
        assert particle.address == Address("@test")

    def test_from_message_no_match_raises(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/msg-nomatch"
            regex = compile(rb"(?P<value>\d+)")

        message = Message(
            data=b"abc",
            direction=Message.Direction.RECEIVE,
            address=Address("@test"),
        )
        with pytest.raises(ParseFailed):
            MyParticle.from_message(message)


class TestGroupedRegexParticleScan:
    def test_scan_returns_matches_with_correct_spans(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/scan"
            regex = compile(rb"(?P<value>\d+)")

        buffer = Buffer()
        buffer.push(b"abc 42 def 99 ghi", utc())

        matches = list(MyParticle.scan(buffer, address=Address("@test")))
        assert len(matches) == 2
        assert matches[0].span == (4, 6)
        assert matches[1].span == (11, 13)

    def test_scan_uses_buffer_timestamps(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/scan-ts"
            regex = compile(rb"(?P<value>\d+)")

        time_1 = datetime(2024, 1, 1, tzinfo=UTC)
        time_2 = datetime(2024, 6, 1, tzinfo=UTC)

        buffer = Buffer()
        buffer.push(b"42\n", time_1)
        buffer.push(b"99\n", time_2)

        matches = list(MyParticle.scan(buffer, address=Address("@test")))
        assert len(matches) == 2
        assert matches[0].timestamp == time_1
        assert matches[1].timestamp == time_2

    def test_scan_match_properties(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/scan-props"
            regex = compile(rb"(?P<value>\d+)")

        buffer = Buffer()
        buffer.push(b"abc 42 def", utc())

        matches = list(MyParticle.scan(buffer, address=Address("@test")))
        assert len(matches) == 1
        match = matches[0]
        assert match.start == 4
        assert match.end == 6
        assert match.bytes == b"42"
        assert match.pattern is MyParticle.regex

    def test_scan_match_parse(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/scan-parse"
            regex = compile(rb"(?P<value>\d+)")

        buffer = Buffer()
        buffer.push(b"42", utc())

        matches = list(MyParticle.scan(buffer, address=Address("@test")))
        particle = matches[0].parse()
        assert particle.data.value == 42

    def test_scan_match_parse_with_default(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/scan-default"
            regex = compile(rb"(?P<value>[a-z]+)")

        buffer = Buffer()
        buffer.push(b"abc", utc())

        matches = list(MyParticle.scan(buffer, address=Address("@test")))
        result = matches[0].parse(default=None)
        assert result is None


class TestGroupedRegexParticleExtract:
    def test_extract_multiple(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/extract"
            regex = compile(rb"(?P<value>\d+)")

        buffer = Buffer()
        buffer.push(b"42 99", utc())

        particles = list(MyParticle.extract(buffer, address=Address("@test")))
        assert len(particles) == 2
        assert particles[0].data.value == 42
        assert particles[1].data.value == 99

    def test_extract_with_optional_groups(self):
        class Data(ParticleData):
            prefix: str | None = None
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/opt-extract"
            regex = compile(rb"(?P<prefix>[A-Z]+)?(?P<value>\d+)")

        buffer = Buffer()
        buffer.push(b"ABC123 456", utc())

        particles = list(MyParticle.extract(buffer, address=Address("@test")))
        assert len(particles) == 2
        assert particles[0].data.prefix == "ABC"
        assert particles[0].data.value == 123
        assert particles[1].data.prefix is None
        assert particles[1].data.value == 456

    def test_extract_errors_ignore(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/ignore"
            regex = compile(rb"(?P<value>[a-z0-9]+)")

        buffer = Buffer()
        buffer.push(b"abc 42 def", utc())

        # "abc" and "def" will fail validation, "42" should succeed.
        particles = list(MyParticle.extract(buffer, errors="ignore", address=Address("@test")))
        assert len(particles) == 1
        assert particles[0].data.value == 42

    def test_extract_errors_raise(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/raise"
            regex = compile(rb"(?P<value>[a-z]+)")

        buffer = Buffer()
        buffer.push(b"abc", utc())

        with pytest.raises(ParseFailed):
            list(MyParticle.extract(buffer, errors="raise", address=Address("@test")))

    def test_extract_errors_callback(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/callback"
            regex = compile(rb"(?P<value>[a-z]+)")

        errors: list[ParseFailed] = []
        buffer = Buffer()
        buffer.push(b"abc", utc())
        list(MyParticle.extract(buffer, errors=errors.append, address=Address("@test")))
        assert len(errors) == 1
        assert isinstance(errors[0], ParseFailed)

    def test_extract_empty_buffer(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/empty"
            regex = compile(rb"(?P<value>\d+)")

        buffer = Buffer()
        particles = list(MyParticle.extract(buffer, address=Address("@test")))
        assert particles == []

    def test_extract_no_matches(self):
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/no-match"
            regex = compile(rb"(?P<value>\d+)")

        buffer = Buffer()
        buffer.push(b"no numbers here", utc())
        particles = list(MyParticle.extract(buffer, address=Address("@test")))
        assert particles == []


class TestGroupedRegexParticleDefinition:
    def test_missing_capture_groups_raises(self):
        with pytest.raises(ValueError, match="missing capture groups"):

            class Data(ParticleData):
                value: Number

            class MyParticle(GroupedRegexParticle[Data]):
                type = "test/missing"
                regex = compile(rb"\d+")

    def test_partial_capture_groups_raises(self):
        with pytest.raises(ValueError, match="missing capture groups"):

            class Data(ParticleData):
                x: Number
                y: Number

            class MyParticle(GroupedRegexParticle[Data]):
                type = "test/partial"
                regex = compile(rb"(?P<x>\d+)")  # Missing 'y'.

    def test_extra_capture_groups_allowed(self):
        # Extra named groups beyond the data fields should not cause an error.
        class Data(ParticleData):
            value: Number

        class MyParticle(GroupedRegexParticle[Data]):
            type = "test/extra"
            regex = compile(rb"(?P<value>\d+),(?P<extra>\w+)")

        particle = MyParticle.from_bytes(b"42,ignored", address=Address("@test"))
        assert particle.data.value == 42


BINARY_SYNC = b"\xa5\x01"


@packable
class BinaryTestData(ParticleData):
    __byte_order__ = "<"
    sync: Annotated[MessageData, PackedBytes(len(BINARY_SYNC))] = Field(
        default=BINARY_SYNC, exclude=True
    )
    value: UInt16


class BinaryTestParticle(BinaryRegexParticle[BinaryTestData]):
    type = "test/binary"
    regex = re.compile(rb"%s.{2}" % BINARY_SYNC, re.DOTALL)


class TestBinaryRegexParticle:
    def test_from_bytes(self):
        raw = BINARY_SYNC + struct.pack("<H", 1234)
        particle = BinaryTestParticle.from_bytes(raw, address=Address("@test"))
        assert particle.data.value == 1234
        assert particle.span == (0, 4)

    def test_extract_from_buffer(self):
        buffer = Buffer()
        buffer.push(
            BINARY_SYNC + struct.pack("<H", 100) + b"\x00" + BINARY_SYNC + struct.pack("<H", 200),
            utc(),
        )

        particles = list(BinaryTestParticle.extract(buffer, address=Address("@test")))
        assert len(particles) == 2
        assert particles[0].data.value == 100
        assert particles[1].data.value == 200

    def test_from_match_delegates_to_from_bytes(self):
        raw = BINARY_SYNC + struct.pack("<H", 999)
        match = BinaryTestParticle.regex.match(raw)
        assert match is not None
        particle = BinaryTestParticle.from_match(match, address=Address("@test"))
        assert particle.data.value == 999
        assert particle.span == (0, 4)

    def test_extract_skips_non_matching_data(self):
        buffer = Buffer()
        buffer.push(b"\x00\x00\x00\x00", utc())

        particles = list(BinaryTestParticle.extract(buffer, address=Address("@test")))
        assert particles == []


class TestParseFailed:
    def test_message_only(self):
        error = ParseFailed("something broke")
        assert str(error) == "something broke"
        assert error.validation is None

    def test_with_validation_error(self):
        from pydantic import ValidationError

        class Data(ParticleData):
            value: Number

        try:
            Data(value="not-a-number")  # type: ignore
        except ValidationError as validation:
            error = ParseFailed("validation failed", validation)
            assert "validation failed" in str(error)
            assert error.validation is validation


async def test_particle_id_filtering():
    await testing.execute_id_filter_test(Particle)


async def test_particle_address_filtering():
    await testing.execute_address_filter_test(Particle)


async def test_particle_timestamp_filtering():
    await testing.execute_timestamp_filter_test(Particle)


async def test_particle_type_filtering():
    await testing.execute_string_filter_test(Particle, "type")


async def test_particle_data_filtering():
    await testing.execute_json_data_filter_test(Particle, "data")


class _ClsFilterData(ParticleData):
    value: int


class _ClsFilterAParticle(Particle[_ClsFilterData]):
    type = "test/cls-filter-a"


class _ClsFilterBParticle(Particle[_ClsFilterData]):
    type = "test/cls-filter-b"


def _cls_filter_particle(cls: type, value: int) -> Particle:
    return cls(
        type=cls.type,
        address=Address("@cls-filter"),
        timestamp=utc(),
        data=_ClsFilterData(value=value),
    )


async def _cls_filter_engine():
    from ceres import Engine

    engine = Engine()
    await engine.database.migrate()

    for cls, count in ((_ClsFilterAParticle, 3), (_ClsFilterBParticle, 2)):
        for value in range(count):
            particle = _cls_filter_particle(cls, value)
            await engine.database.particles.create(particle.to_dynamic())

    return engine


async def test_where_cls_constrains_the_query_to_the_particle_type() -> None:
    """`where(cls=...)` with a `Particle` subclass must filter in SQL, not by dropped rows."""
    engine = await _cls_filter_engine()

    rows = await engine.database.particles.where(cls=_ClsFilterAParticle).all()
    assert len(rows) == 3
    assert all(row.type == "test/cls-filter-a" for row in rows)

    rows = await engine.database.particles.where(cls=_ClsFilterBParticle).all()
    assert len(rows) == 2


async def test_a_stored_particle_keeps_the_connection_it_came_from() -> None:
    """`to_dynamic` is the storage path, so a connection dropped there is a connection lost."""
    engine = await _cls_filter_engine()

    particle = _cls_filter_particle(_ClsFilterAParticle, 9)
    particle.connection = "pressure-1"
    await engine.database.particles.create(particle.to_dynamic())

    rows = await engine.database.particles.where(connection="pressure-1").all()
    assert [row.connection for row in rows] == ["pressure-1"]


async def test_where_cls_count_matches_all() -> None:
    """`count()` must agree with `all()` when filtering by particle class."""
    engine = await _cls_filter_engine()

    count = await engine.database.particles.where(cls=_ClsFilterAParticle).count()
    assert count == 3


def test_filter_matches_by_particle_class() -> None:
    from ceres.particle import ParticleFilter

    particle = _cls_filter_particle(_ClsFilterAParticle, 1)

    # The `cls` field is aliased to "class", a keyword, so construct via validation.
    filter_a = ParticleFilter.model_validate({"cls": _ClsFilterAParticle})
    filter_b = ParticleFilter.model_validate({"cls": _ClsFilterBParticle})
    assert filter_a.matches(particle)
    assert not filter_b.matches(particle)
