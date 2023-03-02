from typing import TYPE_CHECKING, Annotated, Any, Generic, TypeVar

from pydantic import parse_obj_as
from pydantic.utils import lenient_isinstance
from typing_extensions import Self

from .internal.utilities import strify

_T = TypeVar("_T")


class RefInfo(Generic[_T]):
    cls: type[_T]
    _cache: dict[type, "type[RefInfo[Any]]"] = {}

    def __init__(self, cls: type[_T]) -> None:
        self.cls = cls

    def __class_getitem__(cls, target_cls: type[_T]) -> type[Self]:
        if not isinstance(target_cls, type):
            raise ValueError(
                f"reference type must be an instance of {type}, got '{strify(target_cls)}'"
            )

        if target_cls in RefInfo._cache:
            return RefInfo._cache[target_cls]  # type: ignore

        class RefInfoSpec(cls):  # type: ignore
            cls = target_cls

        RefInfoSpec.__name__ = f"RefInfo[{target_cls.__name__}]"
        RefInfoSpec.__qualname__ = RefInfo.__qualname__.replace("RefInfoSpec", RefInfoSpec.__name__)

        RefInfo._cache[target_cls] = RefInfoSpec
        return RefInfoSpec

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> _T | str:
        if isinstance(value, str):
            return value
        if lenient_isinstance(value, cls.cls):
            return value

        return parse_obj_as(cls.cls, value)


if TYPE_CHECKING:
    Ref = Annotated[_T, ()]  # type: ignore
else:
    Ref = RefInfo
    Ref.__name__ = "Ref"
    Ref.__qualname__ = Ref.__qualname__.replace("_Ref", "Ref")
