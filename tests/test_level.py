import logging

import pytest

from ceres.level import Level


class TestLevelValues:
    def test_debug_value(self):
        assert Level.DEBUG == "debug"

    def test_info_value(self):
        assert Level.INFO == "info"

    def test_warning_value(self):
        assert Level.WARNING == "warning"

    def test_error_value(self):
        assert Level.ERROR == "error"

    def test_critical_value(self):
        assert Level.CRITICAL == "critical"


class TestLevelToInt:
    def test_debug_to_int(self):
        assert Level.DEBUG.to_int() == logging.DEBUG

    def test_info_to_int(self):
        assert Level.INFO.to_int() == logging.INFO

    def test_warning_to_int(self):
        assert Level.WARNING.to_int() == logging.WARNING

    def test_error_to_int(self):
        assert Level.ERROR.to_int() == logging.ERROR

    def test_critical_to_int(self):
        assert Level.CRITICAL.to_int() == logging.CRITICAL


class TestLevelFromInt:
    def test_round_trip_for_each_level(self):
        for level in Level:
            assert Level.from_int(level.to_int()) is level

    def test_from_int_debug(self):
        assert Level.from_int(logging.DEBUG) is Level.DEBUG

    def test_from_int_info(self):
        assert Level.from_int(logging.INFO) is Level.INFO

    def test_from_int_warning(self):
        assert Level.from_int(logging.WARNING) is Level.WARNING

    def test_from_int_error(self):
        assert Level.from_int(logging.ERROR) is Level.ERROR

    def test_from_int_critical(self):
        assert Level.from_int(logging.CRITICAL) is Level.CRITICAL

    def test_from_int_raises_type_error_for_string(self):
        with pytest.raises(TypeError):
            Level.from_int("10")  # type: ignore[reportArgumentType]

    def test_from_int_raises_type_error_for_float(self):
        with pytest.raises(TypeError):
            Level.from_int(10.0)  # type: ignore[reportArgumentType]

    def test_from_int_raises_value_error_for_unknown_int(self):
        with pytest.raises(ValueError):
            Level.from_int(999)


class TestLevelOrdering:
    def test_debug_less_than_info(self):
        assert Level.DEBUG < Level.INFO

    def test_info_less_than_warning(self):
        assert Level.INFO < Level.WARNING

    def test_warning_less_than_error(self):
        assert Level.WARNING < Level.ERROR

    def test_error_less_than_critical(self):
        assert Level.ERROR < Level.CRITICAL

    def test_critical_greater_than_error(self):
        assert Level.CRITICAL > Level.ERROR

    def test_warning_greater_than_or_equal_to_itself(self):
        assert Level.WARNING >= Level.WARNING

    def test_debug_less_than_or_equal_to_debug(self):
        assert Level.DEBUG <= Level.DEBUG

    def test_debug_is_minimum(self):
        for level in Level:
            assert Level.DEBUG <= level

    def test_critical_is_maximum(self):
        for level in Level:
            assert Level.CRITICAL >= level


class TestLevelIteration:
    def test_exactly_five_members(self):
        assert len(list(Level)) == 5

    def test_iteration_order(self):
        assert list(Level) == [Level.DEBUG, Level.INFO, Level.WARNING, Level.ERROR, Level.CRITICAL]
