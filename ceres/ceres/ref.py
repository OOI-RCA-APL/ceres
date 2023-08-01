import operator
import sys
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    NoReturn,
    TypeVar,
    Union,
    cast,
    final,
)

from pydantic import parse_obj_as
from typing_extensions import Self

from ceres.address import Address, DynamicAddress
from ceres.component import Component
from ceres.internal.utilities import lenient_isinstance, strify

_reference_cls_l1_generic_cache: dict[type, type["Reference"]] = {}
_reference_cls_l2_generic_cache: dict[tuple[type, type], type["Reference"]] = {}

ReferenceTarget = Union[Component, "Reference", DynamicAddress]
ReferenceRoot = Union[Component, "Reference"]


@final
class Reference:
    __slots__ = (
        "__reference_target__",
        "__reference_root__",
    )

    __reference_cls__: type = Component
    __reference_target__: ReferenceTarget
    __reference_root__: ReferenceRoot | None

    @property
    def __class__(self) -> type:
        component = self.__reference_component__
        if component is None:
            return type(None)

        key = (self.__reference_cls__, type(component))
        if key in _reference_cls_l2_generic_cache:
            return _reference_cls_l2_generic_cache[key]

        class SpecializedReference(type(self)):  # type: ignore
            __slots__ = ()

        attributes = set(dir(type(component)))

        for name in dir(type(self)):
            if name in Reference.__dict__ or name == "_wrapped":
                continue
            if name not in attributes:
                setattr(SpecializedReference, name, None)

        SpecializedReference.__name__ = type(self).__name__
        SpecializedReference.__qualname__ = type(self).__qualname__

        _reference_cls_l2_generic_cache[key] = SpecializedReference
        Component.register(SpecializedReference)

        return SpecializedReference

    @__class__.setter
    def __class__(self, cls: Any) -> None:
        self.__wrapped__.__class__ = cls

    def __class_getitem__(cls, component_cls: type, /) -> type[Self]:
        if component_cls is Component:
            return cls

        if not isinstance(component_cls, type):
            raise ValueError(
                f"reference type must be an instance of {type}, got '{strify(component_cls)}'"
            )

        if component_cls in _reference_cls_l1_generic_cache:
            return _reference_cls_l1_generic_cache[component_cls]

        class TypedReference(Reference):  # type: ignore
            __slots__ = ()

        TypedReference.__reference_cls__ = component_cls
        TypedReference.__name__ = f"{Reference.__name__}[{component_cls.__name__}]"
        TypedReference.__qualname__ = Reference.__qualname__.replace(
            Reference.__name__,
            TypedReference.__name__,
        )

        _reference_cls_l1_generic_cache[component_cls] = TypedReference
        return TypedReference

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

    def __init__(
        self,
        target: ReferenceTarget | str | None = None,
        root: ReferenceRoot | None = None,
    ) -> None:  # type: ignore
        if not lenient_isinstance(target, (Component, Reference, Address, str)):
            raise ValueError(
                f"first argument must be a component, another reference, an address or string, got "
                f"{strify(type(target))}"
            )

        if lenient_isinstance(target, str):
            target = DynamicAddress(target)
        else:
            if not lenient_isinstance(target, type(self).__reference_cls__):
                raise ValueError(
                    f"expected component of type {strify(type(self).__reference_cls__)}, "
                    f"got {strify(type(target))}"
                )

        self.__reference_target__ = target
        self.__reference_root__ = root
        # self.__reference_component_type_id__: int | None = None

    @property
    def __reference_component__(self) -> Component | None:
        if isinstance(self.__reference_target__, Component):
            return self.__reference_target__.unref()

        if self.__reference_root__ is not None and lenient_isinstance(
            self.__reference_target__,
            DynamicAddress,
        ):
            root = cast(Component, self.__reference_root__)
            return root.get_component(self.__reference_target__)

        return None

    def unref(self) -> Component | None:
        return self.__reference_component__

    @property
    def __wrapped__(self) -> Any:
        return self.__reference_component__

    def __dir__(self) -> list[str]:
        return dir(self.__wrapped__)

    def __str__(self) -> str:
        return str(self.__wrapped__)

    def __bytes__(self) -> bytes:
        return bytes(self.__wrapped__)

    def __repr__(self) -> str:
        argument = self.__reference_component__
        if argument is None:
            argument = self.__reference_target__

        return f"{self.__class__.__name__}({repr(argument)})"

    def __reversed__(self) -> Any:
        return reversed(self.__wrapped__)

    def __round__(self) -> Any:
        return round(self.__wrapped__)

    if sys.hexversion >= 0x03070000:

        def __mro_entries__(self, bases: Any) -> Any:
            return (self.__wrapped__,)

    def __lt__(self, other: Any) -> Any:
        return self.__wrapped__ < other

    def __le__(self, other: Any) -> Any:
        return self.__wrapped__ <= other

    def __eq__(self, other: Any) -> Any:
        return self.__wrapped__ == other

    def __ne__(self, other: Any) -> Any:
        return self.__wrapped__ != other

    def __gt__(self, other: Any) -> Any:
        return self.__wrapped__ > other

    def __ge__(self, other: Any):
        return self.__wrapped__ >= other

    def __hash__(self) -> Any:
        return hash(self.__wrapped__)

    def __nonzero__(self) -> Any:
        return bool(self.__wrapped__)

    def __bool__(self) -> Any:
        return bool(self.__wrapped__)

    def __setattr__(self, name: str, value: Any) -> Any:
        if hasattr(type(self), name):
            object.__setattr__(self, name, value)
        else:
            setattr(self.__wrapped__, name, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__wrapped__, name)

    def __add__(self, other: Any) -> Any:
        return self.__wrapped__ + other

    def __sub__(self, other: Any) -> Any:
        return self.__wrapped__ - other

    def __mul__(self, other: Any) -> Any:
        return self.__wrapped__ * other

    def __truediv__(self, other: Any) -> Any:
        return operator.truediv(self.__wrapped__, other)

    def __floordiv__(self, other: Any) -> Any:
        return self.__wrapped__ // other

    def __mod__(self, other: Any) -> Any:
        return self.__wrapped__ % other

    def __divmod__(self, other: Any) -> Any:
        return divmod(self.__wrapped__, other)

    def __pow__(self, other: Any, *args: Any) -> Any:
        return pow(self.__wrapped__, other, *args)

    def __lshift__(self, other: Any) -> Any:
        return self.__wrapped__ << other

    def __rshift__(self, other: Any) -> Any:
        return self.__wrapped__ >> other

    def __and__(self, other: Any) -> Any:
        return self.__wrapped__ & other

    def __xor__(self, other: Any) -> Any:
        return self.__wrapped__ ^ other

    def __or__(self, other: Any) -> Any:
        return self.__wrapped__ | other

    def __radd__(self, other: Any) -> Any:
        return other + self.__wrapped__

    def __rsub__(self, other: Any) -> Any:
        return other - self.__wrapped__

    def __rmul__(self, other: Any) -> Any:
        return other * self.__wrapped__

    def __rtruediv__(self, other: Any) -> Any:
        return other / self.__wrapped__

    def __rfloordiv__(self, other: Any) -> Any:
        return other // self.__wrapped__

    def __rmod__(self, other: Any) -> Any:
        return other % self.__wrapped__

    def __rdivmod__(self, other: Any) -> Any:
        return divmod(other, self.__wrapped__)

    def __rpow__(self, other: Any, *args: Any) -> Any:
        return pow(other, self.__wrapped__, *args)

    def __rlshift__(self, other: Any) -> Any:
        return other << self.__wrapped__

    def __rrshift__(self, other: Any) -> Any:
        return other >> self.__wrapped__

    def __rand__(self, other: Any) -> Any:
        return other & self.__wrapped__

    def __rxor__(self, other: Any) -> Any:
        return other ^ self.__wrapped__

    def __ror__(self, other: Any) -> Any:
        return other | self.__wrapped__

    def __iadd__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped += other
        return self

    def __isub__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped -= other
        return self

    def __imul__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped *= other
        return self

    def __itruediv__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped = wrapped / other
        return self

    def __ifloordiv__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped //= other
        return self

    def __imod__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped %= other
        return self

    def __ipow__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped **= other
        return self

    def __ilshift__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped <<= other
        return self

    def __irshift__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped >>= other
        return self

    def __iand__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped &= other
        return self

    def __ixor__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped ^= other
        return self

    def __ior__(self, other: Any) -> Any:
        wrapped = self.__wrapped__
        wrapped |= other
        return self

    def __neg__(self) -> Any:
        return -self.__wrapped__

    def __pos__(self) -> Any:
        return +self.__wrapped__

    def __abs__(self) -> Any:
        return abs(self.__wrapped__)

    def __invert__(self) -> Any:
        return ~self.__wrapped__

    def __int__(self) -> Any:
        return int(self.__wrapped__)

    def __float__(self) -> Any:
        return float(self.__wrapped__)

    def __complex__(self) -> Any:
        return complex(self.__wrapped__)

    def __oct__(self) -> Any:
        return oct(self.__wrapped__)

    def __hex__(self) -> Any:
        return hex(self.__wrapped__)

    def __index__(self) -> Any:
        return operator.index(self.__wrapped__)

    def __len__(self) -> Any:
        return len(self.__wrapped__)

    def __contains__(self, value: Any) -> Any:
        return value in self.__wrapped__

    def __getitem__(self, key: Any) -> Any:
        return self.__wrapped__[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self.__wrapped__[key] = value

    def __delitem__(self, key: Any) -> None:
        del self.__wrapped__[key]

    def __getslice__(self, i: Any, j: Any) -> Any:
        return self.__wrapped__[i:j]

    def __setslice__(self, i: Any, j: Any, value: Any) -> None:
        self.__wrapped__[i:j] = value

    def __delslice__(self, i: Any, j: Any) -> None:
        del self.__wrapped__[i:j]

    def __enter__(self) -> Any:
        return self.__wrapped__.__enter__()

    def __exit__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__wrapped__.__exit__(*args, **kwargs)

    def __iter__(self) -> Any:
        return iter(self.__wrapped__)

    def __copy__(self) -> NoReturn:
        raise NotImplementedError()

    def __deepcopy__(self, memo: Any) -> NoReturn:
        raise NotImplementedError()

    def __reduce__(self) -> NoReturn:
        raise NotImplementedError()

    def __reduce_ex__(self, protocol: Any) -> NoReturn:
        raise NotImplementedError()


_T = TypeVar("_T")

if TYPE_CHECKING:
    Ref = Annotated[_T, ()]  # type: ignore
else:
    Ref = Reference
