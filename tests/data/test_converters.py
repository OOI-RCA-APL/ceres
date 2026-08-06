import json
import re
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from ceres.config import Config, ServerConfig
from ceres.data.converters import (
    adapt,
    dump,
    from_json,
    serialized_type,
    simplify,
    to_json,
    to_json_schema,
    to_yaml,
    validate,
    validate_json,
    validate_yaml,
    validated_type,
)


class TestAdapt:
    def test_adapt_class_returns_type_adapter(self) -> None:
        adapter = adapt(int)
        assert isinstance(adapter, TypeAdapter)

    def test_adapt_class_caches_result(self) -> None:
        first = adapt(str)
        second = adapt(str)
        assert first is second

    def test_adapt_union_type(self) -> None:
        adapter = adapt(int | str)
        assert adapter.validate_python(42) == 42
        assert adapter.validate_python("hello") == "hello"

    def test_adapt_union_caches_result(self) -> None:
        first = adapt(int | str)
        second = adapt(int | str)
        assert first is second


class TestDump:
    def test_dump_primitive(self) -> None:
        result = dump(42)
        assert result == 42

    def test_dump_with_explicit_type(self) -> None:
        result = dump(42, int)
        assert result == 42

    def test_dump_infers_type_from_runtime(self) -> None:
        result = dump({"key": "value"})
        assert result == {"key": "value"}

    def test_dump_model_to_dict(self) -> None:
        class Point(BaseModel):
            x: int
            y: int

        point = Point(x=1, y=2)
        result = dump(point)
        assert result == {"x": 1, "y": 2}

    def test_dump_json_mode(self) -> None:
        now = datetime(2024, 1, 1, tzinfo=UTC)
        result = dump(now, mode="json")
        assert isinstance(result, str)

    def test_dump_exclude_none(self) -> None:
        class Optional(BaseModel):
            value: int | None = None
            name: str = "test"

        result = dump(Optional(), exclude_none=True)
        assert result == {"name": "test"}


class TestToJson:
    def test_serialize_dict(self) -> None:
        result = to_json({"a": 1, "b": 2})
        assert result == '{"a":1,"b":2}'

    def test_serialize_with_explicit_type(self) -> None:
        result = to_json(42, int)
        assert result == "42"

    def test_serialize_infers_type(self) -> None:
        result = to_json([1, 2, 3])
        assert result == "[1,2,3]"

    def test_serialize_with_indent(self) -> None:
        result = to_json({"a": 1}, indent=2)
        assert "\n" in result

    def test_serialize_model(self) -> None:
        class Item(BaseModel):
            name: str
            count: int

        result = to_json(Item(name="widget", count=5))
        assert '"name":"widget"' in result
        assert '"count":5' in result


class TestToYaml:
    def test_serialize_dict(self) -> None:
        result = to_yaml({"greeting": "hello"})
        assert "greeting: hello" in result

    def test_serialize_with_explicit_type(self) -> None:
        result = to_yaml({"value": 42}, dict[str, int])
        assert "value: 42" in result

    def test_serialize_infers_type(self) -> None:
        result = to_yaml([1, 2, 3])
        assert "- 1" in result
        assert "- 2" in result

    def test_serialize_model(self) -> None:
        class Config(BaseModel):
            host: str
            port: int

        result = to_yaml(Config(host="localhost", port=8080))
        assert "host: localhost" in result
        assert "port: 8080" in result

    def test_sort_keys(self) -> None:
        result = to_yaml({"z": 1, "a": 2}, sort_keys=True)
        lines = result.strip().splitlines()
        assert lines[0].startswith("a:")
        assert lines[1].startswith("z:")


class TestSimplify:
    def test_simplify_model(self) -> None:
        class Nested(BaseModel):
            value: int

        class Outer(BaseModel):
            nested: Nested

        result = simplify(Outer(nested=Nested(value=42)))
        assert result == {"nested": {"value": 42}}

    def test_simplify_datetime_to_string(self) -> None:
        now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = simplify(now)
        assert isinstance(result, str)

    def test_simplify_list(self) -> None:
        result = simplify([1, 2, 3])
        assert result == [1, 2, 3]


class TestFromJson:
    def test_parse_dict(self) -> None:
        result = from_json('{"a": 1}')
        assert result == {"a": 1}

    def test_parse_bytes(self) -> None:
        result = from_json(b"[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_parse_bytearray(self) -> None:
        result = from_json(bytearray(b'"hello"'))
        assert result == "hello"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ValueError):
            from_json("{invalid}")


class TestValidate:
    def test_validate_int(self) -> None:
        assert validate(int, 42) == 42

    def test_validate_coerces_string_to_int(self) -> None:
        assert validate(int, "42") == 42

    def test_validate_strict_rejects_coercion(self) -> None:
        with pytest.raises(ValidationError):
            validate(int, "42", strict=True)

    def test_validate_model(self) -> None:
        class User(BaseModel):
            name: str
            age: int

        result = validate(User, {"name": "Alice", "age": 30})
        assert result.name == "Alice"
        assert result.age == 30

    def test_validate_union(self) -> None:
        result = validate(int | str, "hello")
        assert result == "hello"


class TestValidateJson:
    def test_parse_and_validate_dict(self) -> None:
        result = validate_json(dict[str, int], '{"count": 5}')
        assert result == {"count": 5}

    def test_parse_and_validate_model(self) -> None:
        class Item(BaseModel):
            name: str

        result = validate_json(Item, '{"name": "widget"}')
        assert result.name == "widget"

    def test_invalid_data_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            validate_json(int, '"not a number"')

    def test_bytes_input(self) -> None:
        result = validate_json(list[int], b"[1, 2, 3]")
        assert result == [1, 2, 3]


class TestValidateYaml:
    def test_json_fast_path(self) -> None:
        # Valid JSON should be parsed via the fast JSON path.
        result = validate_yaml(dict[str, int], '{"count": 5}')
        assert result == {"count": 5}

    def test_yaml_fallback(self) -> None:
        # YAML-only syntax forces the YAML fallback path.
        result = validate_yaml(dict[str, int], "count: 5")
        assert result == {"count": 5}

    def test_yaml_bytes_input(self) -> None:
        result = validate_yaml(dict[str, str], b"name: hello")
        assert result == {"name": "hello"}

    def test_yaml_bytearray_input(self) -> None:
        result = validate_yaml(dict[str, int], bytearray(b"value: 42"))
        assert result == {"value": 42}

    def test_invalid_yaml_raises(self) -> None:
        with pytest.raises(Exception):
            validate_yaml(int, ":\n  - ][")

    def test_validates_against_type(self) -> None:
        with pytest.raises(ValidationError):
            validate_yaml(int, "not_a_number: true")


class TestValidatedType:
    def test_before_mode(self) -> None:
        @validated_type(int, "before")
        def double(value: object) -> object:
            if isinstance(value, int):
                return value * 2
            return value

        adapter = TypeAdapter(double)
        assert adapter.validate_python(5) == 10

    def test_after_mode(self) -> None:
        @validated_type(int, "after")
        def clamp(value: int) -> int:
            return max(0, min(value, 100))

        adapter = TypeAdapter(clamp)
        assert adapter.validate_python(200) == 100
        assert adapter.validate_python(-5) == 0

    def test_wrap_mode(self) -> None:
        @validated_type(int, "wrap")
        def add_one(value: object, handler: object) -> int:
            # handler is the inner validator callable
            result = handler(value)  # type: ignore[operator]
            return result + 1

        adapter = TypeAdapter(add_one)
        assert adapter.validate_python(10) == 11

    def test_default_mode_is_before(self) -> None:
        @validated_type(str)
        def strip_whitespace(value: object) -> object:
            if isinstance(value, str):
                return value.strip()
            return value

        adapter = TypeAdapter(strip_whitespace)
        assert adapter.validate_python("  hello  ") == "hello"

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            validated_type(int, "invalid")(lambda v: v)  # type: ignore[arg-type]


class TestSerializedType:
    def test_plain_mode(self) -> None:
        @serialized_type(int, "plain")
        def as_string(value: int) -> str:
            return str(value)

        adapter = TypeAdapter(as_string)
        assert adapter.dump_python(42) == "42"

    def test_wrap_mode(self) -> None:
        @serialized_type(int, "wrap")
        def negate(value: int, handler: object) -> int:
            result = handler(value)  # type: ignore[operator]
            return -result

        adapter = TypeAdapter(negate)
        assert adapter.dump_python(5) == -5

    def test_default_mode_is_plain(self) -> None:
        @serialized_type(str)
        def upper(value: str) -> str:
            return value.upper()

        adapter = TypeAdapter(upper)
        assert adapter.dump_python("hello") == "HELLO"

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            serialized_type(int, "invalid")(lambda v: v)  # type: ignore[arg-type]


class TestToJsonSchema:
    def test_native_section_describes_its_own_keys(self) -> None:
        schema = to_json_schema(ServerConfig)
        assert "port" in schema["properties"]

    def test_multi_word_keys_are_kebab_case(self) -> None:
        cors = to_json_schema(ServerConfig)["$defs"]["RawServerCorsConfig"]
        assert "allow-origins" in cors["properties"]

    def test_whole_config_resolves_every_reference(self) -> None:
        schema = to_json_schema(Config)
        defined = set(schema.get("$defs", {}))
        named = {
            found.removeprefix("#/$defs/")
            for found in re.findall(r'"\$ref": "([^"]+)"', json.dumps(schema))
        }
        assert named <= defined
