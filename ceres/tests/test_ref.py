from types import NoneType
from typing import Iterable, cast

from ceres import Component, Reference, Stream


def test_reference_isinstance():
    component = Component(name="test")
    reference = Reference(component)
    assert isinstance(reference, Component)
    assert not isinstance(reference, int)
    assert not isinstance(reference, Iterable)


def test_reference_proxy_properties():
    component = Component(name="test")
    reference = cast(Component, Reference(component))
    assert reference.name == component.name
    assert reference.address == component.address
    assert reference.running == component.running
    assert isinstance(reference.events, Stream)


def test_reference_unref():
    component = Component(name="test")
    reference = Reference(component)
    assert component.unref() is component
    assert reference is not component
    assert reference.unref() is component


def test_unresolved_reference_is_none_like():
    unresolved = Reference("none")
    assert isinstance(unresolved, NoneType)
    assert unresolved == None  # noqa
    assert unresolved is not None  #
