import importlib
import traceback
from typing import TYPE_CHECKING, Annotated, Any, Iterable, Mapping, Sequence, TypeVar

from pydantic import BaseModel, Field, root_validator, validate_arguments, validator
from typing_extensions import Self

from .data import ImmutableDataObject
from .internal.utilities import lenient_isinstance, lenient_issubclass, strify

_T = TypeVar("_T")


class Loader(ImmutableDataObject):
    cls: type = Field(alias="class")
    args: Sequence[Any] = Field(default_factory=list)
    kwargs: Mapping[str, Any] = Field(default_factory=dict)

    @root_validator(pre=True)
    def _move_extra_to_kwargs(cls, values: dict[str, Any]) -> dict[str, Any]:
        required = {field.alias for field in cls.__fields__.values() if field.alias != "extra"}

        extra: dict[str, Any] = {}
        for field_name in tuple(values.keys()):
            if field_name not in required:
                extra[field_name] = values.pop(field_name)

        values["kwargs"] = {**extra, **values.get("kwargs", {})}
        return values

    @validator("cls", pre=True)
    def _validate_cls(cls, value: Any) -> type:
        if not isinstance(value, (type, str)):
            raise ValueError("class value must be a str import path or class instance")

        return _load_object_cls(object, value)

    @root_validator
    def _validate(cls, values: dict[str, Any]) -> dict[str, Any]:
        _load_object(object, values["cls"], values.get("args", []), values.get("kwargs", {}))
        return values

    def load(self, base: type[_T]) -> _T:
        return _load_object(base, self.cls, self.args, self.kwargs)


class LoadedType:
    cls: type = object
    _cache: dict[type, type[Self]] = {}

    def __class_getitem__(cls, target_cls: type, /) -> type[Self]:
        if target_cls in LoadedType._cache:
            return LoadedType._cache[target_cls]  # type: ignore

        class LoadedTypeSpec(LoadedType):  # type: ignore
            cls = target_cls

        LoadedTypeSpec.__name__ = f"{LoadedType.__name__}[{target_cls.__name__}]"
        LoadedTypeSpec.__qualname__ = LoadedType.__qualname__.replace(
            LoadedType.__name__,
            LoadedTypeSpec.__name__,
        )

        LoadedType._cache[target_cls] = LoadedTypeSpec
        return LoadedTypeSpec

    @classmethod
    def __get_validators__(cls) -> Iterable[Any]:
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> Any:
        if lenient_isinstance(value, cls.cls):
            return value
        if lenient_isinstance(value, Loader):
            return value.load(cls.cls)

        return Loader.parse_obj(value).load(cls.cls)


if TYPE_CHECKING:
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedType


def _load_object_cls(
    base: type[_T],
    source: type | str,
) -> type[_T]:
    if isinstance(source, type):
        if not lenient_issubclass(source, base):
            raise ValueError(f"{source} is not a subclass of {strify(base)}, got {strify(source)}")

        return source

    last_dot_index = source.rindex(".")
    cls_module_path = source[:last_dot_index]
    cls_name = source[last_dot_index + 1 :]

    try:
        module = importlib.import_module(cls_module_path)
    except Exception as exception:
        if isinstance(exception, ModuleNotFoundError) and exception.name == cls_module_path:
            raise ValueError(f"module '{cls_module_path}' was not found")

        raise ValueError(
            f"component module '{cls_module_path}' raised an exception during import: "
            f"{traceback.format_exc()}",
        )

    cls = getattr(module, cls_name, None)
    if cls is None:
        raise ValueError(f"module {module} does not contain class {cls_name}")
    if not isinstance(cls, type):
        raise ValueError(f"{source} is not a class, got {strify(cls)}")
    if not lenient_issubclass(cls, base):
        raise ValueError(f"{source} is not a subclass of {strify(base)}, got {strify(cls)}")

    return cls


def _load_object(
    base: type[_T],
    source: type | str,
    args: Sequence[Any],
    kwargs: Mapping[str, Any] = {},
) -> _T:
    cls = _load_object_cls(base, source)
    if lenient_issubclass(cls, BaseModel):
        return cls(*args, **kwargs)

    instance = object.__new__(cls)
    init = validate_arguments(cls.__init__)
    init(instance, *args, **kwargs)

    return instance
