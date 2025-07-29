import sys
from collections.abc import Iterable

from ceres._internal.lazy import LazyImportProxy, lazy_imports, unlazy

with lazy_imports(__name__):
    from tests.lazy_module import SomeIterable, SomeObject, imported_iterable

assert "tests.lazy_module" not in sys.modules


def test_isinstance():
    real_obj = SomeObject()
    real_iterable = SomeIterable()

    assert isinstance(real_obj, SomeObject)
    assert isinstance(SomeObject, LazyImportProxy)
    assert not isinstance(unlazy(SomeObject), LazyImportProxy)
    assert unlazy(SomeObject).__name__ == "SomeObject"

    assert isinstance(real_iterable, Iterable)
    assert not isinstance(real_iterable, LazyImportProxy)
    assert isinstance(imported_iterable, Iterable)
    assert isinstance(imported_iterable, LazyImportProxy)
