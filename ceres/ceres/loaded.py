import importlib
import traceback
from typing import TYPE_CHECKING, Annotated, Any, Iterable, Mapping, Sequence, TypeVar

from pydantic import BaseModel, Field, validate_arguments, validator

from .data import ImmutableDataObject
from .internal.utilities import lenient_isinstance, lenient_issubclass, strify

_T = TypeVar("_T")

LoadedSource = type[_T] | str


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
            f"component module '{cls_module_path}' raised an exception during import: {traceback.format_exc()}",
        )

    cls: type = getattr(module, cls_name, None)  # type: ignore
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
    parameters: Sequence[Any] | Mapping[str, Any] = (),
) -> _T:
    cls = _load_object_cls(base, source)
    if lenient_issubclass(cls, BaseModel):
        if isinstance(parameters, Mapping):
            return cls(**parameters)
        else:
            return cls(*parameters)

    instance = object.__new__(cls)
    init = validate_arguments(cls.__init__)
    if isinstance(parameters, Mapping):
        init(instance, **parameters)
    else:
        init(instance, *parameters)

    return instance


class Loader(ImmutableDataObject):
    cls: type = Field(alias="class")
    parameters: Sequence[Any] | Mapping[str, Any] = ()

    @validator("cls", pre=True)
    def _validate_cls(cls, value: Any) -> type:
        if not isinstance(value, (type, str)):
            raise ValueError("class value must be a str import path or class instance")

        return _load_object_cls(object, value)

    @validator("parameters")
    def _validate_parameters(
        cls,
        parameters: Sequence[Any] | Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> Sequence[Any] | Mapping[str, Any]:
        _load_object(object, values["cls"], parameters)
        return parameters

    def load(self, base: type[_T]) -> _T:
        return _load_object(base, self.cls, self.parameters)


_class_getitem_cache: dict[type, type] = {}


class LoadedAlias:
    base: type

    def __class_getitem__(cls, base: type, /) -> "type[LoadedAlias]":
        result = _class_getitem_cache.get(base)
        if result is None:

            class LoadedAliasImpl(LoadedAlias):  # type: ignore
                pass

            LoadedAliasImpl.base = base
            result = LoadedAliasImpl
            _class_getitem_cache[base] = result

        return result  # type: ignore

    @classmethod
    def __get_validators__(cls) -> Iterable[Any]:
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> Any:
        if lenient_isinstance(value, cls.base):
            return value
        if lenient_isinstance(value, Loader):
            return value.load(cls.base)

        return Loader.parse_obj(value).load(cls.base)


if TYPE_CHECKING:
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedAlias
