from types import NoneType
from typing import Iterable, Sized, cast

from ceres import Component, Reference, Stream


def test_runtime_type_checks():
    component = Component(name="test")

    class IterableComponent(Component):
        def __iter__(self):
            yield 1

    iterable_component = IterableComponent(name="iterable")

    assert not isinstance(component, Iterable)
    assert not isinstance(Reference(component), Iterable)
    assert not issubclass(Component, Iterable)
    assert not issubclass(Reference, Iterable)
    assert not issubclass(Reference[Component], Iterable)
    assert not issubclass(Reference[Component], Sized)

    assert isinstance(iterable_component, Iterable)
    assert isinstance(Reference(iterable_component), Iterable)
    assert issubclass(IterableComponent, Iterable)
    assert issubclass(IterableComponent, Iterable)
    assert issubclass(Reference[IterableComponent], Iterable)
    assert not issubclass(Reference[IterableComponent], Sized)


def test_property_proxying():
    component = Component(name="test")
    reference = cast(Component, Reference(component))
    assert reference.name == component.name
    assert reference.address == component.address
    assert reference.running == component.running
    assert reference.get_component() is component
    assert isinstance(reference.events, Stream)


def test_reference_unref():
    component = Component(name="test")
    reference = Reference(component)
    assert component.unref() is component
    assert reference is not component
    assert reference.unref() is component


def test_unresolved_reference_is_not_instance_of_none():
    unresolved = Reference("none")
    assert not isinstance(unresolved, NoneType)
    assert unresolved == None  # noqa
    assert unresolved is not None  #


def test_reference_repr():
    root = Component(name="root")
    child = Component(name="child")

    root.add_component(child)

    assert repr(Reference("address")) == "Reference('address')"
    assert repr(Reference("address")) == "Reference('address')"
    assert repr(Reference(root)) == f"Reference({repr(root)})"
    assert repr(Reference("child", root)) == f"Reference({repr(child)})"
