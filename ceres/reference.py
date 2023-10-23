import operator
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    NoReturn,
    TypeVar,
    Union,
    cast,
)

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema
from pydantic_core.core_schema import no_info_after_validator_function
from typing_extensions import Self

from ceres.address import Address, DynamicAddress
from ceres.component import Component
from ceres.internal.utilities import (
    get_type_adapter,
    lenient_isinstance,
    lenient_issubclass,
    strify,
)

_reference_static_cls_generic_cache: dict[type | None, type["Reference"]] = {}
_reference_dynamic_cls_generic_cache: dict[tuple[type | None, type], type["Reference"]] = {}


class ReferenceProxiedMethods:
    if TYPE_CHECKING:

        def __reference_access__(self) -> Any:
            ...

    def __dir__(self) -> list[str]:
        return dir(self.__reference_access__())

    def __str__(self) -> str:
        return str(self.__reference_access__)

    def __bytes__(self) -> bytes:
        return bytes(self.__reference_access__())

    def __reversed__(self) -> Any:
        return reversed(self.__reference_access__())

    def __round__(self) -> Any:
        return round(self.__reference_access__())

    def __ceil__(self) -> Any:
        return self.__reference_access__().__ceil__()

    def __floor__(self) -> Any:
        return self.__reference_access__().__floor__()

    def __format__(self, __format_spec: Any) -> Any:
        return format(self.__reference_access__(), __format_spec)

    def __trunc__(self) -> Any:
        return self.__reference_access__().__trunc__()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__reference_access__()(*args, **kwargs)

    def __mro_entries__(self, bases: Any) -> Any:
        return (self.__reference_access__(),)

    def __lt__(self, other: Any) -> Any:
        return self.__reference_access__() < other

    def __le__(self, other: Any) -> Any:
        return self.__reference_access__() <= other

    def __eq__(self, other: Any) -> Any:
        return self.__reference_access__() == other

    def __ne__(self, other: Any) -> Any:
        return self.__reference_access__() != other

    def __gt__(self, other: Any) -> Any:
        return self.__reference_access__() > other

    def __ge__(self, other: Any):
        return self.__reference_access__() >= other

    def __hash__(self) -> Any:
        return hash(self.__reference_access__())

    def __nonzero__(self) -> Any:
        return bool(self.__reference_access__())

    def __bool__(self) -> Any:
        return bool(self.__reference_access__())

    def __add__(self, other: Any) -> Any:
        return self.__reference_access__() + other

    def __sub__(self, other: Any) -> Any:
        return self.__reference_access__() - other

    def __mul__(self, other: Any) -> Any:
        return self.__reference_access__() * other

    def __truediv__(self, other: Any) -> Any:
        return self.__reference_access__() / other

    def __floordiv__(self, other: Any) -> Any:
        return self.__reference_access__() // other

    def __mod__(self, other: Any) -> Any:
        return self.__reference_access__() % other

    def __divmod__(self, other: Any) -> Any:
        return divmod(self.__reference_access__(), other)

    def __pow__(self, other: Any, *args: Any) -> Any:
        return pow(self.__reference_access__(), other, *args)

    def __lshift__(self, other: Any) -> Any:
        return self.__reference_access__() << other

    def __rshift__(self, other: Any) -> Any:
        return self.__reference_access__() >> other

    def __and__(self, other: Any) -> Any:
        return self.__reference_access__() & other

    def __xor__(self, other: Any) -> Any:
        return self.__reference_access__() ^ other

    def __or__(self, other: Any) -> Any:
        return self.__reference_access__() | other

    def __radd__(self, other: Any) -> Any:
        return other + self.__reference_access__()

    def __rsub__(self, other: Any) -> Any:
        return other - self.__reference_access__()

    def __rmul__(self, other: Any) -> Any:
        return other * self.__reference_access__()

    def __rtruediv__(self, other: Any) -> Any:
        return other / self.__reference_access__()

    def __rfloordiv__(self, other: Any) -> Any:
        return other // self.__reference_access__()

    def __rmod__(self, other: Any) -> Any:
        return other % self.__reference_access__()

    def __rdivmod__(self, other: Any) -> Any:
        return divmod(other, self.__reference_access__())

    def __rpow__(self, other: Any, *args: Any) -> Any:
        return pow(other, self.__reference_access__(), *args)

    def __rlshift__(self, other: Any) -> Any:
        return other << self.__reference_access__()

    def __rrshift__(self, other: Any) -> Any:
        return other >> self.__reference_access__()

    def __rand__(self, other: Any) -> Any:
        return other & self.__reference_access__()

    def __rxor__(self, other: Any) -> Any:
        return other ^ self.__reference_access__()

    def __ror__(self, other: Any) -> Any:
        return other | self.__reference_access__()

    def __iadd__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped += other
        return self

    def __isub__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped -= other
        return self

    def __imul__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped *= other
        return self

    def __itruediv__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped = wrapped / other
        return self

    def __ifloordiv__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped //= other
        return self

    def __imod__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped %= other
        return self

    def __ipow__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped **= other
        return self

    def __ilshift__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped <<= other
        return self

    def __irshift__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped >>= other
        return self

    def __iand__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped &= other
        return self

    def __ixor__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped ^= other
        return self

    def __ior__(self, other: Any) -> Any:
        wrapped = self.__reference_access__()
        wrapped |= other
        return self

    def __neg__(self) -> Any:
        return -self.__reference_access__()

    def __pos__(self) -> Any:
        return +self.__reference_access__()

    def __abs__(self) -> Any:
        return abs(self.__reference_access__())

    def __invert__(self) -> Any:
        return ~self.__reference_access__()

    def __int__(self) -> Any:
        return int(self.__reference_access__())

    def __float__(self) -> Any:
        return float(self.__reference_access__())

    def __complex__(self) -> Any:
        return complex(self.__reference_access__())

    def __oct__(self) -> Any:
        return oct(self.__reference_access__())

    def __hex__(self) -> Any:
        return hex(self.__reference_access__())

    def __index__(self) -> Any:
        return operator.index(self.__reference_access__())

    def __len__(self) -> Any:
        return len(self.__reference_access__())

    def __contains__(self, value: Any) -> Any:
        return value in self.__reference_access__()

    def __getitem__(self, key: Any) -> Any:
        return self.__reference_access__()[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        self.__reference_access__()[key] = value

    def __delitem__(self, key: Any) -> None:
        del self.__reference_access__()[key]

    def __getslice__(self, i: Any, j: Any) -> Any:
        return self.__reference_access__()[i:j]

    def __setslice__(self, i: Any, j: Any, value: Any) -> None:
        self.__reference_access__()[i:j] = value

    def __delslice__(self, i: Any, j: Any) -> None:
        del self.__reference_access__()[i:j]

    def __enter__(self) -> Any:
        return self.__reference_access__().__enter__()

    def __exit__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__reference_access__().__exit__(*args, **kwargs)

    def __iter__(self) -> Any:
        return iter(self.__reference_access__())

    def __copy__(self) -> NoReturn:
        raise NotImplementedError()

    def __deepcopy__(self, memo: Any) -> NoReturn:
        raise NotImplementedError()

    def __reduce__(self) -> NoReturn:
        raise NotImplementedError()

    def __reduce_ex__(self, protocol: Any) -> NoReturn:
        raise NotImplementedError()


class Reference:
    __reference_constraint__: type | None = None

    def __class_getitem__(cls, constraint: type, /) -> type[Self]:
        if not isinstance(constraint, type):
            raise ValueError(
                f"reference constraint must be an instance of {type}, got '{strify(constraint)}'"
            )

        if constraint in _reference_static_cls_generic_cache:
            return _reference_static_cls_generic_cache[constraint]

        class GenericReference(cls):  # type: ignore
            __reference_constraint__ = constraint

        component_names = set(dir(constraint))
        reference_names = Reference.__dict__.keys()

        for name in component_names:
            if name not in reference_names:
                proxy = ReferenceProxiedMethods.__dict__.get(name)
                if proxy is not None:
                    setattr(GenericReference, name, proxy)

        GenericReference.__reference_constraint__ = constraint
        GenericReference.__name__ = f"{Reference.__name__}[{constraint.__name__}]"
        GenericReference.__qualname__ = Reference.__qualname__.replace(
            Reference.__name__,
            GenericReference.__name__,
        )

        _reference_static_cls_generic_cache[constraint] = GenericReference
        return GenericReference

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return no_info_after_validator_function(cls.validate, handler(Any))

    @classmethod
    def validate(cls, value: Any) -> Self | None:
        if value is None:
            return value
        if lenient_isinstance(value, (Component, Reference, DynamicAddress, str)):
            return cls(value)

        return cls(
            get_type_adapter(cls.__reference_constraint__ or Component).validate_python(
                value,
            )  # type: ignore
        )

    def __init__(
        self,
        target: Union[Component, "Reference", DynamicAddress, str] | None = None,
        root: Union[Component, "Reference"] | None = None,
    ) -> None:  # type: ignore
        if not lenient_isinstance(target, (Component, Reference, Address, str)):
            raise ValueError(
                f"first argument must be a component, another reference, an address or string, got "
                f"{strify(type(target))}"
            )

        if lenient_isinstance(target, str):
            target = DynamicAddress(target)
        else:
            if not isinstance(target, (Component, Reference)):
                raise ValueError(f"expected component, got {strify(type(target))}")

            if self.__reference_constraint__ is not None:
                if not lenient_isinstance(target.unref(), self.__reference_constraint__):
                    raise ValueError(
                        f"expected component type {strify(type(self).__reference_constraint__)}, "
                        f"got {strify(type(target))}"
                    )

        if TYPE_CHECKING:
            self.__reference_target__ = target
            self.__reference_root__ = root
        else:
            object.__setattr__(self, "__reference_target__", target)
            object.__setattr__(self, "__reference_root__", root)

        self.__reference_sync_dynamic_class__()

    def __repr__(self) -> str:
        argument = self.__reference_get__()
        if argument is None:
            argument = str(self.__reference_target__)

        return f"{type(self).__name__}({repr(argument)})"

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__reference_get__(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(type(self), name) or hasattr(self, name):
            object.__setattr__(self, name, value)
        else:
            setattr(self.__reference_get__(), name, value)

    def __reference_sync_dynamic_class__(self) -> type["Reference"]:
        current = self.__reference_get_dynamic_class__()
        if self.__class__ is not current:
            self.__class__ = current

        return current

    def __reference_get_dynamic_class__(self) -> type["Reference"]:
        component = self.__reference_get__()
        key = (self.__reference_constraint__, type(component))

        if key in _reference_dynamic_cls_generic_cache:
            return _reference_dynamic_cls_generic_cache[key]

        class SpecializedReference(Reference):
            __reference_constraint__ = self.__reference_constraint__

        component_names = set(dir(type(component)))
        reference_names = Reference.__dict__.keys()

        for name in component_names:
            if name not in reference_names:
                proxy = ReferenceProxiedMethods.__dict__.get(name)
                if proxy is not None:
                    setattr(SpecializedReference, name, proxy)

        if self.__reference_constraint__ is not None:
            SpecializedReference.__name__ = (
                f"{Reference.__name__}[{self.__reference_constraint__.__name__}]"
            )
        else:
            SpecializedReference.__name__ = Reference.__name__

        SpecializedReference.__qualname__ = Reference.__qualname__.replace(
            Reference.__name__,
            SpecializedReference.__name__,
        )

        if component is not None:
            Component.register(SpecializedReference)
            if lenient_issubclass(type(component), Component):
                type(component).register(SpecializedReference)

        _reference_dynamic_cls_generic_cache[key] = SpecializedReference
        return SpecializedReference

    def __reference_get__(self) -> Component | None:
        target = self.__reference_target__
        root = self.__reference_root__

        if not lenient_isinstance(target, DynamicAddress):
            return target.unref()

        if root is not None and lenient_isinstance(target, DynamicAddress):
            root = cast(Component, root)
            return root.get_component(target)

        return None

    def __reference_access__(self) -> Any:
        return self.unref()

    def unref(self) -> Component | None:
        self.__reference_sync_dynamic_class__()
        return self.__reference_get__()


_T = TypeVar("_T")

if TYPE_CHECKING:
    Ref = Annotated[_T, ()]  # type: ignore
else:
    Ref = Reference
