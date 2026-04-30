import pytest

from ceres.__internal__.utilities.debugging import dbg


@pytest.mark.parametrize("value", [42, "hello", [1, 2, 3]])
def test_dbg_returns_same_value(value: object):
    assert dbg(value) == value


def test_dbg_returns_same_object():
    sentinel = object()
    assert dbg(sentinel) is sentinel
