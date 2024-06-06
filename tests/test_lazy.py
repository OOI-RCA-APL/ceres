from ceres._internal.lazy import LazyProxy, lazy_imports, unwrap

with lazy_imports(__name__):
    from tests.lazy_module import Something


def test_isinstance():
    something = Something()
    assert isinstance(something, Something)
    assert isinstance(Something, LazyProxy)
    assert not isinstance(unwrap(Something), LazyProxy)
    assert unwrap(Something).__name__ == "Something"
