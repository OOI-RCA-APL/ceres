"""Filter validation from raw query pairs, the API's text edge."""

from ceres.__internal__.app.operations import _filter
from ceres.variable import VariableFilter


def test_yaml_filter_keys_parse_at_the_edge():
    """A YAML-valued query parameter parses before validation, so the filter compares
    typed values while the model itself takes arguments as passed."""
    parsed = _filter(VariableFilter, {"query": [("value", "5")]})
    assert parsed.value == 5

    quoted = _filter(VariableFilter, {"query": [("value", '"5"')]})
    assert quoted.value == "5"

    repeated = _filter(VariableFilter, {"query": [("value", "1"), ("value", "2")]})
    assert repeated.value == [1, 2]


def test_other_keys_validate_from_their_text():
    parsed = _filter(VariableFilter, {"query": [("name", "x"), ("limit", "3")]})
    assert parsed.name == "x"
    assert parsed.limit == 3
