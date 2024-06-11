import sys
from collections.abc import Iterable

from ceres._internal.lazy import LazyProxy, lazy_imports, unwrap

with lazy_imports(__name__):
    from tests.lazy_module import SomeIterable, SomeObject, imported_iterable

assert "tests.lazy_module" not in sys.modules


def test_isinstance():
    real_obj = SomeObject()
    real_iterable = SomeIterable()

    assert isinstance(real_obj, SomeObject)
    assert isinstance(SomeObject, LazyProxy)
    assert not isinstance(unwrap(SomeObject), LazyProxy)
    assert unwrap(SomeObject).__name__ == "SomeObject"

    assert isinstance(real_iterable, Iterable)
    assert not isinstance(real_iterable, LazyProxy)
    assert isinstance(imported_iterable, Iterable)
    assert isinstance(imported_iterable, LazyProxy)
