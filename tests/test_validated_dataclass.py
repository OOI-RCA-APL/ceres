from dataclasses import field

from pydantic import TypeAdapter

from ceres.data import ValidatedDataclass


class Values(ValidatedDataclass):
    a: int
    b: str = "default"
    c: float = field(default=1.0)


def test_init_fields_set():
    instance = Values(a=10, c=2.5)
    assert instance.__pydantic_fields_set__ == {"a", "c"}


def test_validate_python_fields_set():
    instance = TypeAdapter(Values).validate_python({"a": 20, "c": 1.5})
    assert instance.__pydantic_fields_set__ == {"a", "c"}


def test_validate_json_fields_set():
    instance = TypeAdapter(Values).validate_json('{"a": 15, "b": "json"}')
    assert instance.__pydantic_fields_set__ == {"a", "b"}


def test_set_attribute_adds_to_fields_set():
    instance = Values(a=5)
    assert instance.__pydantic_fields_set__ == {"a"}
    instance.b = "changed"
    assert instance.__pydantic_fields_set__ == {"a", "b"}
    instance.c = 3
    assert instance.__pydantic_fields_set__ == {"a", "b", "c"}
