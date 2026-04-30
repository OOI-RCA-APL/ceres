import pytest

from ceres.data import DataObject, validate
from ceres.loaded import Loaded, Loader, _LoadedType


class SimpleClass:
    def __init__(self, value: int = 0) -> None:
        self.value = value


class AnotherClass:
    def __init__(self, name: str = "default") -> None:
        self.name = name


class SimpleModel(DataObject):
    name: str = "test"
    count: int = 0


class TestLoader:
    def test_create_with_no_init_class(self) -> None:
        loader = validate(
            Loader,
            {"class": "tests.test_loaded:SimpleClass"},
        )
        result = loader.create()
        assert isinstance(result, SimpleClass)
        assert result.value == 0

    def test_create_instantiates_with_arguments(self) -> None:
        loader = validate(
            Loader,
            {
                "class": "tests.test_loaded:SimpleClass",
                "arguments": {"value": 42},
            },
        )
        result = loader.create()
        assert isinstance(result, SimpleClass)
        assert result.value == 42

    def test_create_with_override_arguments(self) -> None:
        loader = validate(
            Loader,
            {
                "class": "tests.test_loaded:SimpleClass",
                "arguments": {"value": 10},
            },
        )
        result = loader.create(arguments={"value": 99})
        assert isinstance(result, SimpleClass)
        assert result.value == 99

    def test_invalid_import_string_raises(self) -> None:
        with pytest.raises(Exception):
            validate(Loader, {"class": "nonexistent.module:FakeClass"})

    def test_create_with_pydantic_model(self) -> None:
        loader = validate(
            Loader,
            {
                "class": "tests.test_loaded:SimpleModel",
                "arguments": {"name": "hello", "count": 5},
            },
        )
        result = loader.create()
        assert isinstance(result, SimpleModel)
        assert result.name == "hello"
        assert result.count == 5

    def test_create_with_plain_class(self) -> None:
        loader = validate(
            Loader,
            {
                "class": "tests.test_loaded:AnotherClass",
                "arguments": {"name": "custom"},
            },
        )
        result = loader.create()
        assert isinstance(result, AnotherClass)
        assert result.name == "custom"

    def test_create_with_no_arguments(self) -> None:
        loader = validate(
            Loader,
            {"class": "tests.test_loaded:SimpleClass"},
        )
        result = loader.create()
        assert isinstance(result, SimpleClass)
        assert result.value == 0


class ModelWithLoaded(DataObject):
    target: Loaded[SimpleModel]  # type: ignore[type-arg]


class ModelWithLoadedPlain(DataObject):
    target: Loaded[SimpleClass]  # type: ignore[type-arg]


class TestLoaded:
    def test_accepts_direct_instance(self) -> None:
        instance = SimpleModel(name="direct", count=1)
        model = validate(ModelWithLoaded, {"target": instance})
        assert isinstance(model.target, SimpleModel)
        assert model.target.name == "direct"
        assert model.target.count == 1

    def test_accepts_loader_dict(self) -> None:
        model = validate(
            ModelWithLoaded,
            {
                "target": {
                    "class": "tests.test_loaded:SimpleModel",
                    "arguments": {"name": "loaded", "count": 7},
                },
            },
        )
        assert isinstance(model.target, SimpleModel)
        assert model.target.name == "loaded"
        assert model.target.count == 7

    def test_rejects_wrong_type(self) -> None:
        with pytest.raises(Exception):
            validate(
                ModelWithLoaded,
                {
                    "target": {
                        "class": "tests.test_loaded:AnotherClass",
                        "arguments": {"name": "wrong"},
                    },
                },
            )

    def test_accepts_loader_dict_for_plain_class(self) -> None:
        model = validate(
            ModelWithLoadedPlain,
            {
                "target": {
                    "class": "tests.test_loaded:SimpleClass",
                    "arguments": {"value": 33},
                },
            },
        )
        assert isinstance(model.target, SimpleClass)
        assert model.target.value == 33


class TestLoadedTypeCache:
    def test_repeated_access_returns_same_type(self) -> None:
        first = _LoadedType[SimpleModel]
        second = _LoadedType[SimpleModel]
        assert first is second

    def test_different_types_return_different_specializations(self) -> None:
        loaded_model = _LoadedType[SimpleModel]
        loaded_class = _LoadedType[SimpleClass]
        assert loaded_model is not loaded_class
