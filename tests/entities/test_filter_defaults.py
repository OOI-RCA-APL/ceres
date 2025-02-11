from ceres import Address, Component
from ceres.engine import Engine


async def test_filter_defaults():
    engine = Engine()
    database = engine.database
    root = Component("root", __with_container__=engine)
    child = Component("child", __with_container__=root)

    assert database.__get_filter_defaults__() == {}
    assert engine.__get_filter_defaults__() == {
        "root": Address.ENGINE,
        "address": Address.ENGINE.all(),
    }
    assert root.__get_filter_defaults__() == {
        "root": Address.ROOT,
        "address": Address.ROOT.all(),
    }
    assert child.__get_filter_defaults__() == {
        "root": Address("@child"),
        "address": Address("@child").all(),
    }
