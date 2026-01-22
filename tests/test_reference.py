from collections.abc import Iterable, Sized
from types import NoneType
from typing import cast

from ceres import Component, Reference
from ceres.address import Address
from ceres.reference import Ref, ref, unref


def test_runtime_type_checks():
    component = Component()

    class IterableComponent(Component):
        def __iter__(self):
            yield 1

    iterable = IterableComponent()

    assert not isinstance(component, Iterable)
    assert not isinstance(Reference(component), Iterable)
    assert not issubclass(Component, Iterable)
    assert not issubclass(Reference, Iterable)
    assert not issubclass(Reference[Component], Iterable)
    assert not issubclass(Reference[Component], Sized)

    assert isinstance(iterable, Iterable)
    assert isinstance(Reference(iterable), Iterable)
    assert issubclass(IterableComponent, Iterable)
    assert issubclass(IterableComponent, Iterable)
    assert issubclass(Reference[IterableComponent], Iterable)
    assert not issubclass(Reference[IterableComponent], Sized)


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
