from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Sequence,
    TypeVar,
    Union,
    final,
)

from wrapt import ObjectProxy
from pydantic import parse_obj_as
from typing_extensions import Self
from zope.proxy import PyProxyBase

from ceres.address import Address, DynamicAddress
from ceres.component import Component
from ceres.data import Name
from ceres.internal.utilities import (
    lenient_isinstance,
    strify,
    traverse,
)

_reference_cls_l1_generic_cache: dict[type, type["Reference"]] = {}
_reference_cls_l2_generic_cache: dict[tuple[type, type], type["Reference"]] = {}

ReferenceTarget = Union[Component, "Reference", DynamicAddress, str]
ReferenceRoot = Union[Component, "Reference"]


@final
class Reference(ObjectProxy):
    __slots__ = (
        "__reference_target__",
        "__reference_root__",
    )

    __reference_cls__: type = Component
    __reference_target__: ReferenceTarget | None
    __reference_root__: ReferenceRoot | None

    def __class_getitem__(cls, component_cls: type, /) -> type[Self]:
        if component_cls is Component:
            return cls

        if not isinstance(component_cls, type):
            raise ValueError(
                f"reference type must be an instance of {type}, got '{strify(component_cls)}'"
            )

        if component_cls in _reference_cls_l1_generic_cache:
            return _reference_cls_l1_generic_cache[component_cls]

        class ReferenceSpec(Reference):  # type: ignore
            __slots__ = ()

        ReferenceSpec.__reference_cls__ = component_cls
        ReferenceSpec.__name__ = f"{Reference.__name__}[{component_cls.__name__}]"
        ReferenceSpec.__qualname__ = Reference.__qualname__.replace(
            Reference.__name__,
            ReferenceSpec.__name__,
        )

        _reference_cls_l1_generic_cache[component_cls] = ReferenceSpec
        return ReferenceSpec

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, value: Any) -> Self | None:
        if value is None:
            return value
        if lenient_isinstance(value, (Component, Reference, DynamicAddress, str)):
            return cls(value)

        return cls(parse_obj_as(cls.__reference_cls__, value))

    def __new__(
        cls,
        target: ReferenceTarget | None = None,
        root: ReferenceRoot | None = None,
    ):  # type: ignore
        if not lenient_isinstance(target, (Component, Reference, Address, str)):
            raise ValueError(
                f"first argument must be a component, another reference, an address or string, got "
                f"{strify(type(target))}"
            )

        if lenient_isinstance(target, str):
            target = DynamicAddress(target)
        else:
            if target is not None and not lenient_isinstance(
                target,
                cls.__reference_cls__,
            ):
                raise ValueError(
                    f"expected component of type {strify(type(cls.__reference_cls__))}, "
                    f"got {strify(type(target))}"
                )

        instance = super().__new__(cls, target)
        instance.__reference_target__ = target
        instance.__reference_root__ = root

        return instance

    def __init__(
        self,
        target: ReferenceTarget | None = None,
        root: ReferenceRoot | None = None,
    ):
        pass

    def __repr__(self) -> str:
        if self.__reference_component__ is None:
            argument = self.__reference_target__
        else:
            argument = self.__reference_component__

        return f"Reference({repr(argument)})"

    def __str__(self) -> str:
        return repr(self)

    @property
    def name(self) -> Name:
        return self.__reference_component__.name

    @property
    def __reference_component__(self) -> Component | None:
        return self._wrapped  # type: ignore

    @__reference_component__.setter
    def __reference_component__(self, value: Component | None) -> None:
        def get_class():
            key = (self.__reference_cls__, type(value))
            if key in _reference_cls_l2_generic_cache:
                return _reference_cls_l2_generic_cache[key]

            class ReferenceSpec(type(self)):  # type: ignore
                __slots__ = ()

            attributes = set(dir(type(value)))

            for name in dir(type(self)):
                if name in Reference.__dict__ or name == "_wrapped":
                    continue
                if name not in attributes:
                    setattr(ReferenceSpec, name, None)

            ReferenceSpec.__name__ = type(self).__name__
            ReferenceSpec.__qualname__ = type(self).__qualname__

            _reference_cls_l2_generic_cache[key] = ReferenceSpec
            return ReferenceSpec

        self._wrapped = value
        self.__class__ = get_class()

    def unref(self) -> Component | None:
        return self.__reference_component__


def get_references(root: Any) -> Sequence[Reference]:
    if isinstance(root, Reference):
        root = root.unref()

    references: list[Reference] = []

    def visit(obj: Any) -> bool:
        if isinstance(obj, Reference):
            references.append(obj)
            return False

        return True

    traverse(root, visit)
    return references


_T = TypeVar("_T")

if TYPE_CHECKING:
    Ref = Annotated[_T, ()]  # type: ignore
else:
    Ref = Reference
