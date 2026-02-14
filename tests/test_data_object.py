import dataclasses
from dataclasses import FrozenInstanceError, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self

import pytest
from pydantic import (
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from ceres._internal.util import (
    CachedClassProperty,
    ClassProperty,
    cached_class_property,
    class_property,
)
from ceres.data import DataModel, DataObject, FieldsSet, FrozenDataObject


@pytest.mark.parametrize("frozen", [False, True])
def test_base(frozen: bool):
    cls = FrozenDataObject if frozen else DataObject

    assert cls.__pydantic_fields__ == {}
    assert cls.__data_object_fields__ == {}
    assert cls.__data_object_field_names__ == ()
    assert cls.__data_object_fields__ == {}

    instance = cls()
    assert instance.__data_object_fields__ == {}
    assert dataclasses.fields(instance) == ()
    assert instance.__fields_set__ == set()

    assert bool(cls.__dataclass_params__.frozen) == frozen


class Normal(DataObject):
    a: int
    b: str = "default"
    c: float = field(default=1.0)


class Slotted(DataObject, slots=True):
    a: int
    b: str = "default"
    c: float = field(default=1.0)


assert set(Slotted.__pydantic_fields__) == {"a", "b", "c"}

Object = Normal | Slotted


def test_name_module():
    assert Normal.__name__ == "Normal"
    assert Normal.__qualname__ == "Normal"
    assert Normal.__module__ == "tests.test_data_object"


@pytest.mark.parametrize("Object", [Normal, Slotted])
def test_init_fields_set(Object: type[Object]):
    instance = Object(a=10, c=2.5)

    assert set(Object.__pydantic_fields__) == {"a", "b", "c"}
    assert len(instance.__fields_set__) == 2
    assert instance.__fields_set__.mask == 0b101
    assert FieldsSet(type(instance), {"a", "c"}).mask == 0b101
    assert instance.__fields_set__ == {"a", "c"}
    assert instance.__fields_set__ is instance.__data_object_fields_set__
    assert instance.__fields_set__ is instance.__pydantic_fields_set__

    instance = Object(a=10)
    assert instance.__fields_set__ == {"a"}
    assert instance.__fields_set__.mask == 0b001


@pytest.mark.parametrize("Object", [Normal, Slotted])
def test_validate_python_fields_set(Object: type[Object]):
    instance = TypeAdapter(Object).validate_python({"a": 20, "c": 1.5})
    assert instance.__fields_set__ == {"a", "c"}


@pytest.mark.parametrize("Object", [Normal, Slotted])
def test_validate_json_fields_set(Object: type[Object]):
    instance = TypeAdapter(Object).validate_json('{"a": 15, "b": "json"}')
    assert instance.__fields_set__ == {"a", "b"}


@pytest.mark.parametrize("Object", [Normal, Slotted])
def test_set_attribute_adds_to_fields_set(Object: type[Object]):
    instance = Object(a=5)
    assert instance.__fields_set__ == {"a"}
    instance.b = "changed"
    assert instance.__fields_set__ == {"a", "b"}
    instance.c = 3
    assert instance.__fields_set__ == {"a", "b", "c"}
    instance.c = 4
    assert instance.__fields_set__ == {"a", "b", "c"}
    assert instance == Object(a=5, b="changed", c=4)


@pytest.mark.parametrize("slots", [False, True])
def test_positional_values_are_added_to_fields_set(slots: bool):
    class PositionalValues(DataObject, slots=slots):
        a: int = Field(kw_only=False)
        b: int = Field(default=0, kw_only=False)
        c: str = "default"
        d: float = field(default=1.0)

    instance = PositionalValues(10, 20, c="c")
    assert instance.__fields_set__ == {"a", "b", "c"}
    instance = PositionalValues(10)
    assert instance.__fields_set__ == {"a"}


@pytest.mark.parametrize("Object", [Normal, Slotted])
def test_can_be_pickled(Object: type[Object]):
    import pickle

    from ceres.data import _reconstruct_data_object

    assert Object.__qualname__ == Object.__name__
    assert Object.__module__ == "tests.test_data_object"

    if Object is Slotted:
        assert Object.__data_object_reduced_slots__ == ("a", "b", "c")
    else:
        assert Object.__data_object_reduced_slots__ == ()

    original = Object(a=42, b="pickle")
    assert original.__data_object_fields_set__ == {"a", "b"}
    assert original.__data_object_fields_set__ == FieldsSet(Object, {"a", "b"})
    assert tuple(original.__data_object_fields_set__._get_set_indexes()) == (0, 1)
    assert tuple(original.__data_object_fields__) == ("a", "b", "c")
    if Object is Slotted:
        assert original.__reduce__() == (
            _reconstruct_data_object,
            (Object, None, [42, "pickle", 1.0], original.__fields_set__.mask),
        )
    elif Object is Normal:
        assert original.__reduce__() == (
            _reconstruct_data_object,
            (Object, {"a": 42, "b": "pickle", "c": 1.0}, None, original.__fields_set__.mask),
        )

    dumped = pickle.dumps(original)
    reconstructed = pickle.loads(dumped)
    assert type(reconstructed) is type(original)
    assert reconstructed == original
    assert original.__fields_set__ == reconstructed.__fields_set__


def test_model_class_and_repr():
    class Values(DataObject):
        a: int
        b: str
        c: float = 1

        @field_validator("a")
        def _validate_a_is_even(cls, value: int) -> int:
            if value % 2 != 0:
                raise ValueError("a must be even")

            return value

        @model_validator(mode="after")
        def _validate_model(self) -> Any:
            if self.b == "donkey":
                raise ValueError("b cannot be 'donkey'")

            return self

    obj = Values(a=10, b="test")
    assert Values.__name__ == "Values"

    model = Values.Model(a=10, b="test")
    assert Values.Model.__name__ == "Values.Model"
    assert model.model_dump() == {"a": 10, "b": "test", "c": 1}
    assert model.model_fields_set == {"a", "b"}

    expected_object_repr = "Values(a=10, b='test')"
    expected_model_repr = "Values.Model(a=10, b='test')"

    assert repr(obj) == expected_object_repr
    assert str(obj) == expected_object_repr
    assert repr(model) == expected_model_repr
    assert str(model) == expected_model_repr

    # Ensure that the Model class is cached.
    assert Values.Model is Values.Model
    converted = obj.__data_object_to_model__()
    assert converted == model
    assert converted.model_fields_set == {"a", "b"}

    model = DataModel()
    expected_object_repr = "DataModel()"
    assert repr(model) == expected_object_repr
    assert str(model) == expected_object_repr

    with pytest.raises(ValidationError):
        Values(a=11, b="test")
    with pytest.raises(ValidationError):
        Values.Model(a=11, b="test")

    with pytest.raises(ValidationError):
        Values(a=9, b="donkey")
    with pytest.raises(ValidationError):
        Values.Model(a=9, b="donkey")


@pytest.mark.parametrize("slots", [False, True])
@pytest.mark.parametrize("kw_only", [False, True])
def test_validation_is_executed(slots: bool, kw_only: bool):
    class Values(DataObject, slots=slots, kw_only=kw_only):
        a: int
        b: str
        c: float = 1

    # Invalid input should raise ValidationError
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="missing"):
        Values()  # type: ignore
    with pytest.raises(ValidationError, match="int_parsing"):
        Values(a="not an int", b="test")  # type: ignore
    if not kw_only:
        with pytest.raises(ValidationError, match="string_type"):
            Values(10, 123)  # type: ignore


def test_private_slots():
    class PrivateSlots(DataObject, slots=True):
        a: int
        b: str
        _c: float = field(init=False)

        def __post_init__(self) -> None:
            self._c: float = 1.0

    assert PrivateSlots.__slots__ == ("a", "b", "_c")
    assert set(PrivateSlots.__pydantic_fields__) == {"a", "b"}
    instance = PrivateSlots(a=10, b="test")
    instance.__data_object_to_model__()


@pytest.mark.parametrize("slots", [False, True])
@pytest.mark.parametrize("mode", ["keyword", "class"])
def test_frozen_class(mode: Literal["keyword", "class"], slots: bool):
    if mode == "keyword":

        class A(DataObject, slots=slots, frozen=True):
            a: int

        class B(A, slots=slots, frozen=True):
            b: int
            _c: float = field(init=False)

        assert issubclass(A, FrozenDataObject)
    else:

        class A(FrozenDataObject, slots=slots):
            a: int

        class B(A, slots=slots):
            b: int
            _c: float = field(init=False)

    assert issubclass(A, FrozenDataObject)

    instance = B(a=1, b=2)
    with pytest.raises(FrozenInstanceError):
        instance.a = 0  # type: ignore
    with pytest.raises(FrozenInstanceError):
        instance.b = 0  # type: ignore

    object.__setattr__(instance, "a", 5)  # Should work fine.
    assert instance.a == 5


@pytest.mark.parametrize("frozen_base", [True])
@pytest.mark.parametrize("frozen_subclass", [True])
@pytest.mark.parametrize("slots", [False, True])
def test_inheritance(
    slots: bool,
    frozen_subclass: bool,
    frozen_base: bool,
):
    assert len(DataObject.__mro__) == 2
    assert not DataObject.__dataclass_params__.frozen

    class A(DataObject, slots=slots, frozen=frozen_base):
        a: int

    if frozen_base:
        assert issubclass(A, FrozenDataObject)

    def make_b():
        class B(A, slots=slots, frozen=frozen_subclass):
            b: int

        return B

    B = None
    if frozen_base and not frozen_subclass:
        with pytest.raises(TypeError, match="frozen dataclass"):
            B = make_b()

    if B is None:
        return

    instance = B(a=1, b=2)
    assert instance.a == 1
    assert instance.b == 2
    assert instance.__fields_set__ == {"a", "b"}


@pytest.mark.parametrize("slots", [False, True])
@pytest.mark.parametrize(
    "class_kind",
    [
        "normal",
        "dataclass",
        "pydantic-dataclass",
        "data-object",
    ],
)
def test_class_property_and_dataclasses(
    class_kind: Literal[
        "normal",
        "dataclass",
        "pydantic-dataclass",
        "data-object",
    ],
    slots: bool,
):
    if TYPE_CHECKING:
        from dataclasses import dataclass
    else:
        if class_kind == "pydantic-dataclass":
            from pydantic.dataclasses import dataclass
        else:
            from dataclasses import dataclass

    if "dataclass" in class_kind:

        @dataclass(slots=slots)
        class Example:
            value: int

            @class_property
            @classmethod
            def upper_class_name(cls) -> list[str]:
                return [cls.__name__.upper()]

            @cached_class_property
            @classmethod
            def lower_class_name_cached(cls) -> list[str]:
                return [cls.__name__.lower()]

            division_by_zero: ClassVar[int] = ~CachedClassProperty(lambda cls: 1 / 0)
            division_by_zero_cached = CachedClassProperty[Self, int](
                lambda cls: cls.division_by_zero
            )

        @dataclass(slots=slots)
        class Inherited(Example):
            pass
    else:
        base: type = DataObject if class_kind == "data-object" else object

        class Example(base):  # type: ignore
            value: int

            @class_property
            @classmethod
            def upper_class_name(cls) -> list[str]:
                return [cls.__name__.upper()]

            @cached_class_property
            @classmethod
            def lower_class_name_cached(cls) -> list[str]:
                return [cls.__name__.lower()]

            division_by_zero: ClassVar[int] = ~ClassProperty(lambda cls: 1 / 0)
            division_by_zero_cached = CachedClassProperty[Self, int](
                lambda cls: cls.division_by_zero
            )

        class Inherited(Example):
            pass

    if class_kind != "normal":
        assert set(field.name for field in dataclasses.fields(Example)) == {"value"}
        assert set(field.name for field in dataclasses.fields(Inherited)) == {"value"}

    if class_kind in ("pydantic-dataclass", "data-object"):
        assert set(Example.__pydantic_fields__) == {"value"}  # type: ignore
        assert set(Inherited.__pydantic_fields__) == {"value"}  # type: ignore

    assert Example.upper_class_name == ["EXAMPLE"]
    assert Inherited.upper_class_name == ["INHERITED"]

    assert Example.lower_class_name_cached == ["example"]
    assert Inherited.lower_class_name_cached == ["inherited"]

    # Ensure the class property's value is recomputed every time.
    assert Example.upper_class_name is not Example.upper_class_name
    assert Example.lower_class_name_cached is Example.lower_class_name_cached

    with pytest.raises(ZeroDivisionError):
        Example.division_by_zero
    with pytest.raises(ZeroDivisionError):
        Inherited.division_by_zero
    with pytest.raises(ZeroDivisionError):
        Example.division_by_zero_cached
    with pytest.raises(ZeroDivisionError):
        Inherited.division_by_zero_cached

    # Ensure properties can be accessed from the instance as well.
    if class_kind != "normal":
        example = Example(value=0)
        inherited = Inherited(value=0)

        assert example.upper_class_name == Example.upper_class_name
        assert example.lower_class_name_cached is Example.lower_class_name_cached

        with pytest.raises(ZeroDivisionError):
            example.division_by_zero
        with pytest.raises(ZeroDivisionError):
            inherited.division_by_zero


def test_default_config():
    from ceres.data import _DATA_OBJECT_DEFAULT_CONFIG

    assert DataObject.__pydantic_config__ == {
        "title": "DataObject",
        **_DATA_OBJECT_DEFAULT_CONFIG,
    }


def test_config_inheritance():
    import pydantic

    class A(DataObject, config=ConfigDict(validate_assignment=False)):
        value: int

    class B(A):
        pass

    class C(A, config=ConfigDict(validate_assignment=True)):
        pass

    class D(C):
        pass

    # These should run without error.
    a = A(value=10)
    a.value = "invalid"  # type: ignore
    b = B(value=10)
    b.value = "invalid"  # type: ignore

    # Validated assignment is enabled for C and D so this should raise a ValidationError.
    with pytest.raises(pydantic.ValidationError):
        c = C(value=10)
        c.value = "invalid"  # type: ignore
    with pytest.raises(pydantic.ValidationError):
        d = D(value=10)
        d.value = "invalid"  # type: ignore


def test_validate_snake_or_kebab():
    class Kebab(DataObject):
        could_be_kebab: int

    expected = Kebab(could_be_kebab=5)
    assert TypeAdapter(Kebab).validate_python({"could_be_kebab": 5}) == expected
    assert TypeAdapter(Kebab).validate_python({"could-be-kebab": 5}) == expected
    with pytest.raises(ValidationError, match="unexpected"):
        assert TypeAdapter(Kebab).validate_python({"could_be-kebab": 5}) == expected


def test_to_dict():
    class Example(DataObject):
        a: int
        b: str = "default"
        c: float = field(default=1.0)

    instance = Example(a=10, c=2.5)
    assert instance.__fields_set__ == {"a", "c"}
    assert "a" in instance.__fields_set__
    assert "b" not in instance.__fields_set__
    assert "c" in instance.__fields_set__
    assert instance.__data_object_to_dict__() == {"a": 10, "b": "default", "c": 2.5}
    assert instance.__data_object_to_dict__(exclude_unset=True) == {"a": 10, "c": 2.5}
    assert instance.__data_object_to_dict__(exclude={"a", "c"}) == {"b": "default"}
    assert instance.__data_object_to_dict__(exclude={"b"}) == {"a": 10, "c": 2.5}
    assert instance.__data_object_to_dict__(include={"a", "b"}) == {"a": 10, "b": "default"}
    assert instance.__data_object_to_dict__(include={"a", "c"}) == {"a": 10, "c": 2.5}
    assert instance.__data_object_to_dict__(include={"b"}) == {"b": "default"}
    assert instance.__data_object_to_dict__(include={"b"}, exclude={"b"}) == {}
    assert instance.__data_object_to_dict__(exclude={"a"}, include={"a", "b"}) == {"b": "default"}
    assert instance.__data_object_to_dict__(exclude={"a"}, include={"a", "c"}) == {"c": 2.5}
    assert instance.__data_object_to_dict__(exclude={"a"}, include={"b"}) == {"b": "default"}
    assert instance.__data_object_to_dict__(exclude={"a"}, exclude_unset=True) == {"c": 2.5}
