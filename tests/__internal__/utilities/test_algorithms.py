from dataclasses import dataclass

from pydantic import BaseModel

from ceres.__internal__.utilities.algorithms import traverse


def test_traverse_simple_dict():
    visited: list[object] = []
    data = {"key": "value"}
    traverse(data, visit=lambda node: (visited.append(node), None)[1])
    assert data in visited
    assert "key" in visited
    assert "value" in visited


def test_traverse_nested_dict():
    visited: list[object] = []
    inner = {"inner_key": 1}
    outer = {"outer_key": inner}
    traverse(outer, visit=lambda node: (visited.append(node), None)[1])
    assert outer in visited
    assert "outer_key" in visited
    assert inner in visited
    assert "inner_key" in visited
    assert 1 in visited


def test_traverse_list():
    visited: list[object] = []
    items = [1, 2, 3]
    traverse(items, visit=lambda node: (visited.append(node), None)[1])
    assert items in visited
    assert 1 in visited
    assert 2 in visited
    assert 3 in visited


def test_traverse_pydantic_model():
    class SimpleModel(BaseModel):
        name: str
        count: int

    visited: list[object] = []
    model = SimpleModel(name="test", count=42)
    traverse(model, visit=lambda node: (visited.append(node), None)[1])
    assert model in visited
    assert "test" in visited
    assert 42 in visited


def test_traverse_dataclass():
    @dataclass
    class SimpleData:
        label: str
        value: int

    visited: list[object] = []
    instance = SimpleData(label="hello", value=99)
    traverse(instance, visit=lambda node: (visited.append(node), None)[1])
    assert instance in visited
    assert "hello" in visited
    assert 99 in visited


def test_traverse_visit_returning_false_stops_descent():
    visited: list[object] = []
    inner = {"inner_key": "inner_value"}
    outer = {"outer_key": inner}

    def visitor(node: object) -> bool | None:
        visited.append(node)
        if node is inner:
            return False
        return None

    traverse(outer, visit=visitor)
    assert outer in visited
    assert inner in visited
    assert "inner_key" not in visited
    assert "inner_value" not in visited


def test_traverse_handles_cycles():
    visited: list[object] = []
    cycle: dict[str, object] = {}
    cycle["self"] = cycle
    traverse(cycle, visit=lambda node: (visited.append(node), None)[1])
    assert cycle in visited
    assert visited.count(cycle) == 1


def test_traverse_with_none_value():
    visited: list[object] = []
    data = {"key": None}
    traverse(data, visit=lambda node: (visited.append(node), None)[1])
    assert data in visited
    assert "key" in visited
    assert None in visited


def test_traverse_with_prepopulated_seen_skips_objects():
    visited: list[object] = []
    skipped = {"should": "skip"}
    data = {"kept": "value", "skipped": skipped}
    seen = {id(skipped)}
    traverse(data, visit=lambda node: (visited.append(node), None)[1], seen=seen)
    assert data in visited
    assert "kept" in visited
    assert "value" in visited
    assert skipped not in visited
    assert "should" not in visited
    assert "skip" not in visited
