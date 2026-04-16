from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Self

import pydantic
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    ImportString,
    model_validator,
    validate_call,
)
from pydantic_core.core_schema import no_info_after_validator_function

from ceres.__internal__.utilities.typing import is_mapping, lenient_isinstance, lenient_issubclass
from ceres.data import DataObject, validate

if TYPE_CHECKING:
    from pydantic_core import CoreSchema

__all__ = [
    "Loaded",
    "Loader",
]


_loaded_type_cache: dict[type, type[_LoadedType]] = {}


class _LoadedType:
    cls: type = object

    def __class_getitem__(cls, target_cls: type, /) -> type[_LoadedType]:
        if target_cls in _loaded_type_cache:
            return _loaded_type_cache[target_cls]

        class Specialized(_LoadedType):
            cls = target_cls

        Specialized.__name__ = f"{_LoadedType.__name__}[{target_cls.__name__}]"
        Specialized.__qualname__ = _LoadedType.__qualname__.replace(
            _LoadedType.__name__,
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
        if lenient_isinstance(value, cls.cls):
            return value

        if lenient_isinstance(value, Loader):
            loader = value
        else:
            loader = validate(Loader, value)

        instance = loader.create()
        if not lenient_isinstance(instance, cls.cls):
            raise ValueError(f"must be an instance of {cls.cls}, got {type(instance)}")

        return instance


if TYPE_CHECKING:
    type Loaded[T] = T
else:
    Loaded = _LoadedType
"""Annotation marking a field as a value that can be instantiated from a `Loader` spec.

A field annotated as `Loaded[T]` accepts either an instance of `T` or a `Loader` (or its
serialized form), in the latter case Pydantic validation runs the loader to produce the
instance before storing it on the model.
"""


class Loader[T](DataObject):
    """Declarative specification for constructing an instance of a class by import path.

    A `Loader` names a target class via its fully qualified import string and collects the
    arguments used to construct it. Calling `create()` imports the class and instantiates
    it, the validator also performs a dry-run construction so misconfiguration is caught
    at load time rather than at first use.
    """

    cls: ImportString[type[T]] = Field(validation_alias="class", serialization_alias="class")
    """Fully qualified import path of the target class."""
    arguments: Mapping[str, Any] = Field(default_factory=dict)
    """Keyword arguments passed when constructing the target class."""

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
        """Instantiate the target class and return the resulting object.

        Args:
            arguments: Additional keyword arguments that override any overlapping entries
                from `arguments` and the loader's extra kwargs.

        Returns:
            A new instance of the loader's target class.
        """
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

        if lenient_issubclass(target, BaseModel) or pydantic.dataclasses.is_pydantic_dataclass(
            target
        ):
            if is_mapping(arguments):
                instance = target(**arguments)
            else:
                instance = target(*arguments)
        else:
            instance = object.__new__(target)
            if target.__init__ is not object.__init__:
                init = validate_call(config=ConfigDict(arbitrary_types_allowed=True))(
                    target.__init__
                )
                if is_mapping(arguments):
                    init(instance, **arguments)
                else:
                    init(instance, *arguments)

        return instance  # type: ignore
