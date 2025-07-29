from typing import TYPE_CHECKING

from ceres import Variable
from tests import testing
from tests.testing import FilterTestGroup, execute_filter_test

if TYPE_CHECKING:
    from ceres.variable import VariableFilterArgs


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


async def test_variable_value_filtering():
    group: FilterTestGroup[VariableFilterArgs] = {
        "order": "name",
        "entities": {
            "ab": {"name": "ab", "value": {"a": 1, "b": 2}},
            "complex": {
                "name": "complex",
                "value": {"a": {"inner": "value"}, "b": 2.0, "c": [[{}]]},
            },
            "decimal": {"name": "decimal", "value": 10.5},
            "false": {"name": "false", "value": False},
            "none": {"name": "none", "value": None},
            "one": {"name": "one", "value": 1},
            "one-also": {"name": "one-also", "value": 1},
            "true": {"name": "true", "value": True},
            "zero": {"name": "zero", "value": 0},
        },
        "tests": [
            {"filter": {}, "keys": None},
            {"filter": {"value": None}, "keys": ["none"]},
            {"filter": {"value": True}, "keys": ["true"]},
            {"filter": {"value": False}, "keys": ["false"]},
            {"filter": {"value": 0}, "keys": ["zero"]},
            {"filter": {"value": 1}, "keys": ["one", "one-also"]},
            {"filter": {"value": 10.5}, "keys": ["decimal"]},
            {"filter": {"value": {"a": 1, "b": 2}}, "keys": ["ab"]},
            {"filter": {"value": {"b": 2, "a": 1}}, "keys": []},
            {"filter": {"value": {"a": 1, "b": 2, "c": [[{}]]}}, "keys": []},
            {
                "filter": {"value": {"a": {"inner": "value"}, "b": 2.0, "c": [[{}]]}},
                "keys": ["complex"],
            },
        ],
    }

    await execute_filter_test(Variable, group)
