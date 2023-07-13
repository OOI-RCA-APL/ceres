from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Mapping,
    Sequence,
    TypeVar,
)

from pydantic import Field, root_validator, validate_arguments
from typing_extensions import Self

from ceres.data import ClassPath, ImmutableDataObject
from ceres.internal.utilities import get_model, is_mapping, lenient_isinstance

_T = TypeVar("_T")


class Loader(ImmutableDataObject):
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

        if is_mapping(args):
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
        if is_mapping(args):
            args = {**args, **extra}

        cls._load_obj(values["cls_path"].cls, args)

        return values

    def create(self, *, args: Sequence[Any] | Mapping[str, Any] | None = None) -> Any:
        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}

        if args is not None:
            if not is_mapping(args):
                applied_args = args
            elif is_mapping(self.args):
                applied_args = {**args, **self.args, **extra}
            else:
                applied_args = args
        else:
            if is_mapping(self.args):
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
            if is_mapping(args):
                model.validate(args)
                instance = target(**args)
            else:
                instance = target(*args)
        else:
            instance = object.__new__(target)
            init = validate_arguments(target.__init__)
            if is_mapping(args):
                init(instance, **args)
            else:
                init(instance, *args)

        return instance


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

        instance = loader.create()
        if not lenient_isinstance(instance, cls.cls):
            raise ValueError(f"must be an instance of {cls.cls}")

        return instance


if TYPE_CHECKING:
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedType
