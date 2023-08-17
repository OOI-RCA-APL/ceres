from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Mapping,
    Sequence,
    TypeVar,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    model_validator,
)
from pydantic.validate_call import validate_call
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function
from typing_extensions import Self

from ceres.data import ClassPath, ImmutableDataObject
from ceres.internal.utilities import (
    is_mapping,
    is_pydantic_dataclass_type,
    lenient_isinstance,
    lenient_issubclass,
)

_T = TypeVar("_T")


class Loader(ImmutableDataObject):
    cls_path: ClassPath = Field(alias="class")
    args: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def cls(self) -> type:
        return self.cls_path.cls

    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}
        args = {**self.args, **extra}
        self._load_obj(self.cls_path.cls, args)
        return self

    def create(self, *, args: Mapping[str, Any] | None = None) -> Any:
        if args is None:
            args = {}

        extra = {name: getattr(self, name) for name in self._get_extra_kwarg_names()}
        args = {**self.args, **extra, **args}

        return self._load_obj(self.cls_path.cls, args)

    @classmethod
    def _load_obj(
        cls,
        target: type,
        args: Mapping[str, Any] | None = None,
    ) -> Any:
        if args is None:
            args = {}

        if lenient_issubclass(target, BaseModel) or is_pydantic_dataclass_type(target):
            if is_mapping(args):
                instance = target(**args)
            else:
                instance = target(*args)
        else:
            instance = object.__new__(target)
            if target.__init__ is not object.__init__:
                init = validate_call(config=ConfigDict(arbitrary_types_allowed=True))(
                    target.__init__
                )
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
            loader = Loader.model_validate(value)

        instance = loader.create()
        if not lenient_isinstance(instance, cls.cls):
            raise ValueError(f"must be an instance of {cls.cls}")

        return instance


if TYPE_CHECKING:
    Loaded = Annotated[_T, ()]
else:
    Loaded = LoadedType
