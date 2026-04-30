from typing import override

from ceres.__internal__.utilities.text import reprify, strify


class _BrokenStr:
    @override
    def __str__(self) -> str:
        raise RuntimeError("broken")


class _BrokenRepr:
    @override
    def __repr__(self) -> str:
        raise RuntimeError("broken")


class TestStrify:
    def test_string(self):
        assert strify("hello") == "hello"

    def test_int(self):
        assert strify(42) == "42"

    def test_broken_str(self):
        result = strify(_BrokenStr())
        assert result == "<__str__() raised exception>"


class TestReprify:
    def test_string(self):
        assert reprify("hello") == "'hello'"

    def test_int(self):
        assert reprify(42) == "42"

    def test_broken_repr(self):
        result = reprify(_BrokenRepr())
        assert result == "<__repr__() raised exception>"
