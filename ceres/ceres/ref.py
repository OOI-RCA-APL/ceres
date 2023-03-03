from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Collection,
    Mapping,
    TypeVar,
    cast,
)

from pydantic import parse_obj_as
from pydantic.utils import get_model
from typing_extensions import Self, get_origin

from .errors import ComponentReferenceInvalidError
from .internal.utilities import (
    is_optional,
    lenient_isinstance,
    lenient_issubclass,
    strify,
)

_T = TypeVar("_T")


class RefType:
    cls: type = object
    _cache: dict[type, type[Self]] = {}

    def __class_getitem__(cls, target_cls: type, /) -> type[Self]:
        if not isinstance(target_cls, type):
            raise ValueError(
                f"reference type must be an instance of {type}, got '{strify(target_cls)}'"
            )

        if target_cls in RefType._cache:
            return RefType._cache[target_cls]  # type: ignore

        class RefTypeSpec(RefType):  # type: ignore
            cls = target_cls

        RefTypeSpec.__name__ = f"{RefType.__name__}[{target_cls.__name__}]"
        RefTypeSpec.__qualname__ = RefType.__qualname__.replace(
            RefType.__name__,
            RefTypeSpec.__name__,
        )

        RefType._cache[target_cls] = RefTypeSpec
        return RefTypeSpec

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value
        if lenient_isinstance(value, cls.cls):
            return value

        return parse_obj_as(cls.cls, value)


if TYPE_CHECKING:
    Ref = Annotated[_T, ()]  # type: ignore
else:
    Ref = RefType
