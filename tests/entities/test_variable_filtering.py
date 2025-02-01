from ceres import Variable
from ceres.variable import VariableFilterArgs
from tests import testing
from tests.testing import FilterTestGroup, execute_filter_test


async def test_variable_address_filtering():
    await testing.execute_address_filter_test(Variable)


async def test_variable_name_filtering():
    await testing.execute_string_filter_test(Variable, "name")


async def test_variable_internal_filtering():
    group: FilterTestGroup[VariableFilterArgs] = {
        "order": "name",
        "entities": {
            "a": {"name": "__enabled__"},
            "b": {"name": "__other_internal__"},
            "c": {"name": "_underscore"},
            "d": {"name": "underscore_"},
            "e": {"name": "variable"},
        },
        "tests": [
            {"filter": {"internal": None}, "keys": None},
            {"filter": {"internal": True}, "keys": ["a", "b"]},
            {"filter": {"internal": False}, "keys": ["c", "d", "e"]},
        ],
    }

    await execute_filter_test(Variable, group)
