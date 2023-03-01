from typing import TYPE_CHECKING, Annotated, Any, Generic, TypeVar

from pydantic import parse_obj_as
from typing_extensions import Self

from .internal.utilities import lenient_issubclass

if TYPE_CHECKING:
    from .component import Component
else:
    Component = "Component"

_ComponentT = TypeVar("_ComponentT", bound=Component)


class RefInfo(Generic[_ComponentT]):
    cls: type[_ComponentT]
    _cache: dict[type, "RefInfo[Component]"] = {}

    def __init__(self, cls: type[_ComponentT]) -> None:
        self.cls = cls

    def __class_getitem__(cls, item: type[_ComponentT]) -> Self:
        from .component import Component

        if not lenient_issubclass(item, Component):
            raise ValueError("references can only refer to components")

        if item in RefInfo._cache:
            return RefInfo._cache[item]  # type: ignore

        base: type = super().__class_getitem__(item)  # type: ignore

        class RefInfoSpec(base):  # type: ignore
            cls = item

        RefInfoSpec.__name__ = f"RefInfo[{item.__name__}]"
        RefInfoSpec.__qualname__ = RefInfo.__qualname__.replace("RefInfoSpec", RefInfoSpec.__name__)

        RefInfo._cache[item] = RefInfoSpec
        return RefInfoSpec

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> _ComponentT | str:
        if isinstance(value, str):
            return value

        return parse_obj_as(cls.cls, value)


if TYPE_CHECKING:
    Ref = Annotated[_ComponentT, ()]  # type: ignore
else:
    Ref = RefInfo
    Ref.__name__ = "Ref"
    Ref.__qualname__ = Ref.__qualname__.replace("_Ref", "Ref")
