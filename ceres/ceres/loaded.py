from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Mapping,
    Sequence,
    TypeVar,
)

from pydantic import Field, root_validator, validate_arguments, validator
from typing_extensions import Self, override

from ceres.data import ClassPath, ImmutableDataObject, Name
from ceres.internal.utilities import get_model, lenient_isinstance, lenient_issubclass

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = "Component"

_T = TypeVar("_T")


class Loader(ImmutableDataObject):
    class Config(ImmutableDataObject.Config):
        json_encoders = {
            **ImmutableDataObject.Config.json_encoders,
            ClassPath: str,
        }
        pass

    cls_path: ClassPath = Field(alias="class")
    args: Sequence[Any] | Mapping[str, Any] = ()

    @property
    def cls(self) -> type:
        return self.cls_path.cls

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

    @root_validator
    def _validate(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "cls_path" not in values:
            return values

        extra = {name: values[name] for name in cls._get_extra_kwarg_names()}
        args = values.get("args", {})
        if isinstance(args, Mapping):
            args = {**args, **extra}

        cls._load_obj(values["cls_path"].cls, args)

        return values

    def load(self, *, args: Sequence[Any] | Mapping[str, Any] | None = None) -> Any:
        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}

        if args is not None:
            if not isinstance(args, Mapping):
                applied_args = args
            elif isinstance(self.args, Mapping):
                applied_args = {**args, **self.args, **extra}
            else:
                applied_args = args
        else:
            if isinstance(self.args, Mapping):
                applied_args = {**self.args, **extra}
            else:
                applied_args = self.args

        return self._load_obj(
            self.cls_path.cls,
            applied_args,
        )

    @classmethod
    def _load_obj(
        cls,
        target: type,
        args: Sequence[Any] | Mapping[str, Any] = MappingProxyType({}),
    ) -> Any:
        model = get_model(target)

        if model is not None:
            if isinstance(args, Mapping):
                instance = target(**args)
            else:
                instance = target(*args)
        else:
            instance = object.__new__(target)
            init = validate_arguments(target.__init__)
            if isinstance(args, Mapping):
                init(instance, **args)
            else:
                init(instance, *args)

        return instance


class ComponentLoader(Loader):
    name: Name

    def load(self, *, args: Sequence[Any] | Mapping[str, Any] | None = None) -> Component:
        return super().load(args=args)

    @override
    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return [*super()._get_extra_kwarg_names(), "name"]

    @validator("cls_path")
    def _validate_cls_path(cls, value: ClassPath) -> ClassPath:
        from ceres.component import Component

        if not lenient_issubclass(value.cls, Component):
            raise ValueError(f"must be a subclass of {Component}")

        return value


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
            loader = value
        else:
            loader = Loader.parse_obj(value)

        instance = loader.load()
        if not lenient_isinstance(instance, cls.cls):
            raise ValueError(f"must be an instance of {cls.cls}")

        return instance


if TYPE_CHECKING:
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedType
