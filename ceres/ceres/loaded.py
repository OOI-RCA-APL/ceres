import importlib
import traceback
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Mapping,
    Sequence,
    TypeVar,
    overload,
)

from pydantic import Field, root_validator, validate_arguments, validator
from typing_extensions import Self, override

from .data import ImmutableDataObject, Name
from .internal.utilities import get_model, lenient_isinstance, lenient_issubclass, strify

if TYPE_CHECKING:
    from .component import Component
else:
    Component = "Component"

_T = TypeVar("_T")


class Loader(ImmutableDataObject):
    cls: type = Field(alias="class")
    args: Sequence[Any] | Mapping[str, Any] = ()

    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return []

    @root_validator(pre=True)
    def _pre_validate(cls, values: dict[str, Any]) -> dict[str, Any]:
        required = {field.alias for field in cls.__fields__.values() if field.alias != "extra"}

        extra: dict[str, Any] = {}
        for field_name in tuple(values.keys()):
            if field_name not in required:
                extra[field_name] = values.pop(field_name)

        args = values.get("args", {})

        if isinstance(args, Mapping):
            values["args"] = {**args, **extra}
        else:
            if extra:
                raise ValueError("positional args are not allowed")

        return values

    @validator("cls", pre=True)
    def _pre_validate_cls(cls, value: Any) -> type:
        if not isinstance(value, (type, str)):
            raise ValueError("class value must be a str import path or class instance")

        return cls._load_cls(value)

    @root_validator
    def _validate(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "cls" not in values:
            return values

        extra = {name: values[name] for name in cls._get_extra_kwarg_names()}
        args = values.get("args", {})
        if isinstance(args, Mapping):
            args = {**args, **extra}

        cls._load_obj(values["cls"], args)

        return values

    def load(self, *, base: type[_T] | None = None) -> _T:
        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}
        args = self.args
        if isinstance(args, Mapping):
            args = {**args, **extra}

        return self._load_obj(
            self.cls,
            args,
            base=base,
        )

    @classmethod
    def _load_cls(
        cls,
        source: type | str,
        *,
        base: type[_T] | None = None,
    ) -> type[_T]:
        if isinstance(source, type):
            if base is not None:
                if not lenient_issubclass(source, base):
                    raise ValueError(
                        f"{source} is not a subclass of {strify(base)}, got {strify(source)}"
                    )

            return source  # type: ignore

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
        if base is not None:
            if not lenient_issubclass(cls, base):
                raise ValueError(f"{source} is not a subclass of {strify(base)}, got {strify(cls)}")

        return cls  # type: ignore

    @classmethod
    def _load_obj(
        cls,
        source: type | str,
        args: Sequence[Any] | Mapping[str, Any] = MappingProxyType({}),
        *,
        base: type[_T] | None = None,
    ) -> _T:
        target_cls = cls._load_cls(source, base=base)
        model = get_model(target_cls)

        if model is not None:
            if isinstance(args, Mapping):
                instance = target_cls(**args)
            else:
                instance = target_cls(*args)
        else:
            instance = object.__new__(target_cls)
            init = validate_arguments(target_cls.__init__)
            if isinstance(args, Mapping):
                init(instance, **args)
            else:
                init(instance, *args)

        return instance


class ComponentLoader(Loader):
    name: Name

    @overload
    def load(self) -> Component:
        ...

    @overload
    def load(self, *, base: type[_T] | None = None) -> _T:
        ...

    def load(self, *, base: type[_T] | None = None) -> _T | Component:
        return super().load(base=base)

    @override
    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return [*super()._get_extra_kwarg_names(), "name"]

    @override
    @classmethod
    def _load_cls(
        cls,
        source: type | str,
        *,
        base: type[_T] | None = None,
    ) -> type[_T]:
        result = super()._load_cls(source, base=base)
        from .component import Component

        if not lenient_issubclass(result, Component):
            raise ValueError(f"class must be a subclass of {Component}")

        return result


_loaded_type_cache: dict[type, type["LoadedType"]] = {}


class LoadedType:
    cls: type = object

    def __class_getitem__(cls, target_cls: type, /) -> type[Self]:
        if target_cls in _loaded_type_cache:
            return _loaded_type_cache[target_cls]

        class Specialized(LoadedType):
            cls = target_cls

        Specialized.__name__ = f"{LoadedType.__name__}[{target_cls.__name__}]"
        Specialized.__qualname__ = LoadedType.__qualname__.replace(
            LoadedType.__name__,
            Specialized.__name__,
        )

        _loaded_type_cache[target_cls] = Specialized
        return Specialized

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> Any:
        if lenient_isinstance(value, cls.cls):
            return value
        if lenient_isinstance(value, Loader):
            return value.load(base=cls.cls)

        return Loader.parse_obj(value).load(base=cls.cls)


if TYPE_CHECKING:
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedType
