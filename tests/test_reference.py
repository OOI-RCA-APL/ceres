from types import NoneType
from typing import Iterable, Sized, cast

from ceres import Component, Reference, Stream
from ceres.system import System


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
    reference = cast(Component, Reference(component))
    assert reference.system == component.system
    assert isinstance(reference.system.events, Stream)


def test_reference_unref():
    component = Component()
    reference = Reference(component)
    assert reference is not component
    assert reference.unref() is component


def test_unresolved_reference_is_not_instance_of_none():
    unresolved = Reference("none")
    assert not isinstance(unresolved, NoneType)
    assert unresolved == None  # noqa
    assert unresolved is not None  #


def test_reference_repr():
    root = System(name="root", component=Component)
    child = System(name="child", component=Component)

    assert repr(Reference("address")) == "Reference('address')"
    assert repr(Reference("address")) == "Reference('address')"
    assert repr(Reference(root.component)) == f"Reference({repr(root)})"
    assert repr(Reference("child", root.component)) == f"Reference({repr(child.component)})"
