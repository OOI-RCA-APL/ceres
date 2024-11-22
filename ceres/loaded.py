from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Mapping, Self, Sequence, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    ImportString,
    model_validator,
    validate_call,
)
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function

from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject

with lazy_imports(__name__):
    from ceres._internal import util


class Loader[T](ImmutableDataObject):
    cls: ImportString[type[T]] = Field(validation_alias="class", serialization_alias="class")
    arguments: Mapping[str, Any] = Field(default_factory=dict)

    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}
        arguments = {**self.arguments, **extra}
        self._load_obj(self.cls, arguments)
        return self

    def create(self, arguments: Mapping[str, Any] | None = None) -> T:
        if arguments is None:
            arguments = {}

        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}
        arguments = {**self.arguments, **extra, **arguments}

        return self._load_obj(self.cls, arguments)

    @classmethod
    def _load_obj(
        cls,
        target: type,
        arguments: Mapping[str, Any] | None = None,
    ) -> T:
        if arguments is None:
            arguments = {}

        if util.lenient_issubclass(target, BaseModel) or util.is_pydantic_dataclass_type(target):
            if util.is_mapping(arguments):
                instance = target(**arguments)
            else:
                instance = target(*arguments)
        else:
            instance = object.__new__(target)
            if target.__init__ is not object.__init__:
                init = validate_call(config=ConfigDict(arbitrary_types_allowed=True))(
                    target.__init__
                )
                if util.is_mapping(arguments):
                    init(instance, **arguments)
                else:
                    init(instance, *arguments)

        return instance  # type: ignore


_loaded_type_cache: dict[type, type[LoadedType]] = {}


class LoadedType:
    cls: type = object

    def __class_getitem__(cls, target_cls: type, /) -> type[LoadedType]:
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
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return no_info_after_validator_function(cls.validate, handler(Any))

    @classmethod
    def validate(cls, value: Any) -> Any:
        if util.lenient_isinstance(value, cls.cls):
            return value

        if util.lenient_isinstance(value, Loader):
            loader = value
        else:
            loader = Loader.model_validate(value)

        instance = loader.create()
        if not util.lenient_isinstance(instance, cls.cls):
            raise ValueError(f"must be an instance of {cls.cls}, got {type(instance)}")

        return instance


if TYPE_CHECKING:
    _T = TypeVar("_T")
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedType
