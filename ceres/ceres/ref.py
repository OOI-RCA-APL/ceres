from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Sequence,
    TypeVar,
    final,
)

from pydantic import parse_obj_as
from typing_extensions import Self
from zope.proxy import PyProxyBase

from ceres.component import Component
from ceres.data import Name
from ceres.internal.utilities import (
    lenient_isinstance,
    strify,
    traverse,
)

_reference_cls_l1_generic_cache: dict[type, type["Reference"]] = {}
_reference_cls_l2_generic_cache: dict[tuple[type, type], type["Reference"]] = {}


@final
class Reference(PyProxyBase):
    __slots__ = ("__component_name__",)
    __component_cls__: type = Component

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

        ReferenceSpec.__component_cls__ = component_cls
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
        if lenient_isinstance(value, (Component, Reference, str)):
            return cls(value)

        return cls(parse_obj_as(cls.__component_cls__, value))

    def __new__(cls, component: Component | Self | str):  # type: ignore
        if not lenient_isinstance(component, (Component, Reference, str)):
            raise ValueError(
                f"first argument must be a component, another reference or a string, got "
                f"{strify(type(component))}"
            )

        if lenient_isinstance(component, str):
            component_instance = None
            component_name = component
        elif lenient_isinstance(component, Reference):
            component_instance = component.__component_instance__
            component_name = component.__component_name__
        else:
            component_instance = component
            component_name = component.name

        if component_instance is not None and not lenient_isinstance(
            component_instance,
            cls.__component_cls__,
        ):
            raise ValueError(
                f"expected component of type {strify(type(cls.__component_cls__))}, got "
                f"{strify(type(component_instance))}"
            )

        instance = super().__new__(cls, component_instance)
        instance.__component_name__ = component_name
        instance.__component_instance__ = component_instance

        return instance

    def __init__(self, component: Component | Self | str):
        pass

    def __repr__(self) -> str:
        if self.__component_instance__ is None:
            argument = self.__component_name__
        else:
            argument = self.__component_instance__

        return f"Reference({repr(argument)})"

    def __str__(self) -> str:
        return repr(self)

    @property
    def name(self) -> Name:
        return self.__component_name__

    @property
    def __component_instance__(self) -> Component | None:
        return self._wrapped  # type: ignore

    @__component_instance__.setter
    def __component_instance__(self, value: Component | None) -> None:
        def get_class():
            key = (self.__component_cls__, type(value))
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
        return self.__component_instance__


def get_references(obj: Any) -> Sequence[Reference]:
    references: list[Reference] = []

    def visit(obj: Any) -> bool:
        if isinstance(obj, Reference):
            references.append(obj)
            return False

        return True

    traverse(obj, visit)
    return references


_T = TypeVar("_T")

if TYPE_CHECKING:
    Ref = Annotated[_T, ()]  # type: ignore
else:
    Ref = Reference
