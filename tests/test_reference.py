import copy
from collections.abc import Sized
from dataclasses import field
from types import NoneType
from typing import cast, override

import pytest

from ceres import Component, Reference
from ceres.address import Address
from ceres.reference import Ref, ref, unref


def test_runtime_type_checks():
    component = Component()

    class SizedComponent(Component):
        def __len__(self) -> int:
            return 1

    iterable = SizedComponent()

    assert not isinstance(component, Sized)
    assert not isinstance(Reference(component), Sized)
    assert not issubclass(Component, Sized)
    assert not issubclass(Reference, Sized)
    assert not issubclass(Reference[Component], Sized)

    assert isinstance(iterable, Sized)
    assert isinstance(Reference(iterable), Sized)
    assert issubclass(SizedComponent, Sized)
    assert issubclass(SizedComponent, Sized)
    assert issubclass(Reference[SizedComponent], Sized)


def test_property_proxying():
    component = Component()
    reference = cast("Component", Reference(component))
    assert reference.system is component.system
    assert isinstance(reference.system.address, Address)


def test_reference_unref():
    component = Component()
    reference = Reference(component)
    assert reference is not component
    assert reference.__unref__() is component


def test_unresolved_reference_is_not_instance_of_none():
    unresolved = Reference("none")
    assert not isinstance(unresolved, NoneType)
    assert unresolved == None  # noqa
    assert unresolved is not None  #


def test_reference_repr():
    root = Component()
    child = Component(__with_name__="child")
    root.system.attach(child)

    assert repr(Reference("address")) == "Reference('address')"

    assert repr(Reference(root)) == "Reference(Component())"
    assert repr(Reference("child", root)) == "Reference(Component())"
    assert repr(Reference("other", root)) == "Reference('other')"


def test_direct_references():
    class A(Component):
        pass

    class B(Component):
        a: Ref[A]

    class C(Component):
        a: Ref[A]

    class D(Component):
        b: Ref[B]
        c: Ref[C]

    a = A()
    b = B(a=a)
    c = C(a=a)
    d = D(b=b, c=c)

    assert a.system.get_references() == []
    assert a.system.get_referenced_components() == []
    assert a.system.get_referencing_components() == [b, c]

    assert unref(b.a) is a
    assert isinstance(b.a, Reference)

    assert b.system.get_references() == [a]
    assert b.system.get_referenced_components() == [a]
    assert b.system.get_referencing_components() == [d]

    assert c.system.get_references() == [a]
    assert c.system.get_referenced_components() == [a]
    assert c.system.get_referencing_components() == [d]

    assert d.system.get_references() == [b, c]
    assert d.system.get_referenced_components() == [b, c]
    assert d.system.get_referencing_components() == []


def test_indirect_references():
    class A(Component):
        pass

    class B(Component):
        pass

    class C(Component):
        b: Ref[B]

    class D(Component):
        b: Ref[B]
        c: Ref[C]

    a = A("a")
    a.system.attach(b := B("b"))
    a.system.attach(c := C("c", b=ref(b.system.address, B)))
    a.system.attach(
        d := D(
            "d",
            b=ref(b.system.address, B),
            c=ref(c.system.address, C),
        )
    )

    assert len(a.system.children) == 3

    assert a.system.get_references() == []
    assert b.system.get_references() == []
    assert c.system.get_references() == [b]
    assert d.system.get_references() == [b, c]

    assert a.system.get_referenced_components() == []
    assert b.system.get_referenced_components() == []
    assert c.system.get_referenced_components() == [b]
    assert d.system.get_referenced_components() == [b, c]

    assert a.system.get_referencing_components() == []
    assert b.system.get_referencing_components() == [c, d]
    assert c.system.get_referencing_components() == [d]
    assert d.system.get_referencing_components() == []


def test_absolute_reference_into_foreign_tree_resolves_to_none_when_detached():
    class Referencer(Component):
        target: Ref[Component]

    # A detached tree has no engine to route absolute cross-tree addresses through, so a
    # reference into a foreign tree resolves to `None`.
    referencer = Referencer("alpha", target=ref("@beta.x", Component))
    referencer.system.sync_references()

    assert unref(referencer.target) is None


def test_init_with_invalid_target_type():
    with pytest.raises(ValueError, match="first argument must be"):
        Reference(42)  # type: ignore[arg-type]


def test_init_with_constraint_mismatch():
    class Alpha(Component):
        pass

    class Beta(Component):
        pass

    alpha = Alpha()
    with pytest.raises(ValueError, match="expected component type"):
        Reference[Beta](alpha)


def test_validate_with_none():
    result = Reference.validate(None)
    assert result is None


def test_validate_with_string_address():
    result = Reference.validate("some.address")
    assert isinstance(result, Reference)
    assert repr(result) == "Reference('some.address')"


def test_validate_with_reference():
    component = Component()
    original = Reference(component)
    validated = Reference.validate(original)
    assert isinstance(validated, Reference)
    assert validated.__unref__() is component


def test_validate_with_component():
    component = Component()
    result = Reference.validate(component)
    assert isinstance(result, Reference)
    assert result.__unref__() is component


def test_ref_wrapping_component():
    component = Component()
    reference = ref(component, Component)
    assert isinstance(reference, Reference)
    assert unref(reference) is component


def test_ref_wrapping_string_address():
    reference = ref("some.address", Component)
    assert isinstance(reference, Reference)


def test_ref_wrapping_with_constraint():
    class Target(Component):
        pass

    target = Target()
    reference = ref(target, Target)
    assert isinstance(reference, Reference)
    assert unref(reference) is target


def test_ref_with_existing_reference_returns_as_is():
    component = Component()
    reference = Reference(component)
    result = ref(reference)
    assert result is reference


class NumberComponent(Component):
    value: int = 0

    def __add__(self, other: object) -> int:
        return self.value + cast("int", other)

    def __sub__(self, other: object) -> int:
        return self.value - cast("int", other)

    def __mul__(self, other: object) -> int:
        return self.value * cast("int", other)

    def __lt__(self, other: object) -> bool:
        return self.value < cast("int", other)

    def __gt__(self, other: object) -> bool:
        return self.value > cast("int", other)

    def __le__(self, other: object) -> bool:
        return self.value <= cast("int", other)

    def __ge__(self, other: object) -> bool:
        return self.value >= cast("int", other)

    def __bool__(self) -> bool:
        return self.value != 0

    def __int__(self) -> int:
        return self.value

    def __float__(self) -> float:
        return float(self.value)

    def __neg__(self) -> int:
        return -self.value

    def __abs__(self) -> int:
        return abs(self.value)


def test_proxy_arithmetic_operators():
    component = NumberComponent(value=10)
    reference = Reference(component)
    assert reference + 5 == 15  # type: ignore[operator]
    assert reference - 3 == 7  # type: ignore[operator]
    assert reference * 2 == 20  # type: ignore[operator]


def test_proxy_comparison_operators():
    component = NumberComponent(value=10)
    reference = Reference(component)
    assert reference < 20  # type: ignore[operator]
    assert reference > 5  # type: ignore[operator]
    assert reference <= 10  # type: ignore[operator]
    assert reference >= 10  # type: ignore[operator]
    assert not (reference < 5)  # type: ignore[operator]
    assert not (reference > 20)  # type: ignore[operator]


def test_proxy_bool():
    truthy = NumberComponent(value=42)
    falsy = NumberComponent(value=0)
    assert bool(Reference(truthy)) is True
    assert bool(Reference(falsy)) is False


def test_proxy_int():
    component = NumberComponent(value=7)
    reference = Reference(component)
    assert int(reference) == 7  # type: ignore[call-overload]


def test_proxy_float():
    component = NumberComponent(value=3)
    reference = Reference(component)
    assert float(reference) == 3.0  # type: ignore[call-overload]


def test_proxy_neg():
    component = NumberComponent(value=5)
    reference = Reference(component)
    assert -reference == -5  # type: ignore[operator]


def test_proxy_abs():
    component = NumberComponent(value=-8)
    reference = Reference(component)
    assert abs(reference) == 8  # type: ignore[call-overload]


class ContainerComponent(Component):
    items: list[int] = field(default_factory=lambda: [10, 20, 30])

    def __len__(self) -> int:
        return len(self.items)

    @override
    def __contains__(self, value: object) -> bool:
        return value in self.items

    def __getitem__(self, key: int) -> int:
        return self.items[key]


def test_proxy_len():
    component = ContainerComponent()
    reference = Reference(component)
    assert len(reference) == 3  # type: ignore[arg-type]


def test_proxy_contains():
    component = ContainerComponent()
    reference = Reference(component)
    assert 20 in reference  # type: ignore[operator]
    assert 99 not in reference  # type: ignore[operator]


def test_proxy_getitem():
    component = ContainerComponent()
    reference = Reference(component)
    assert reference[0] == 10  # type: ignore[index]
    assert reference[2] == 30  # type: ignore[index]


def test_copy_raises():
    component = Component()
    reference = Reference(component)
    with pytest.raises(NotImplementedError):
        copy.copy(reference)


def test_deepcopy_raises():
    component = Component()
    reference = Reference(component)
    with pytest.raises(NotImplementedError):
        copy.deepcopy(reference)


def test_reduce_raises():
    component = Component()
    reference = Reference(component)
    with pytest.raises(NotImplementedError):
        reference.__reduce__()


def test_reduce_ex_raises():
    component = Component()
    reference = Reference(component)
    with pytest.raises(NotImplementedError):
        reference.__reduce_ex__(2)


def test_setattr_on_reference_own_attributes():
    component = Component()
    reference = Reference(component)
    original_target = reference.__reference_target__
    assert original_target is component
    reference.__reference_root__ = component
    assert reference.__reference_root__ is component


def test_getattr_proxying():
    class Readable(Component):
        label: str = "hello"

    component = Readable()
    reference = Reference(component)
    assert reference.label == "hello"


def test_class_getitem_with_non_type_raises():
    with pytest.raises(ValueError, match="reference constraint must be"):
        Reference["not_a_type"]  # type: ignore[type-var]
