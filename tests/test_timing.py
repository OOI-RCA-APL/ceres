from datetime import UTC, datetime, timedelta, timezone

import pytest

from ceres.timing import (
    _parse_sdelta,
    delta,
    get_fake_now,
    isodelta,
    sdelta,
    set_fake_now,
    utc,
)


class TestUtc:
    def test_returns_current_time_when_called_with_no_arguments(self) -> None:
        before = datetime.now(UTC)
        result = utc()
        after = datetime.now(UTC)
        assert before <= result <= after
        assert result.tzinfo is UTC

    def test_returns_utc_datetime_unchanged(self) -> None:
        value = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        result = utc(value)
        assert result is value

    def test_converts_non_utc_datetime_to_utc(self) -> None:
        eastern = timezone(timedelta(hours=-5))
        value = datetime(2024, 6, 15, 12, 0, 0, tzinfo=eastern)
        result = utc(value)
        assert result.tzinfo is UTC
        assert result.hour == 17

    def test_parses_iso_string(self) -> None:
        result = utc("2024-06-15T12:00:00Z")
        assert result == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)

    def test_honors_fake_now(self) -> None:
        fake_time = datetime(2000, 1, 1, 0, 0, 0, tzinfo=UTC)
        set_fake_now(fake_time)
        try:
            result = utc()
            assert result == fake_time
        finally:
            set_fake_now(None)


class TestDelta:
    def test_returns_timedelta_from_seconds(self) -> None:
        result = delta(60)
        assert result == timedelta(seconds=60)

    def test_returns_timedelta_from_iso_string(self) -> None:
        result = delta("PT1H30M")
        assert result == timedelta(hours=1, minutes=30)

    def test_returns_timedelta_from_timedelta(self) -> None:
        value = timedelta(hours=2)
        result = delta(value)
        assert result == value


class TestIsodelta:
    def test_formats_simple_duration(self) -> None:
        result = isodelta(timedelta(hours=1, minutes=30))
        assert result == "PT1H30M"

    def test_formats_zero_duration(self) -> None:
        result = isodelta(timedelta(0))
        assert result == "PT0S"

    def test_formats_days(self) -> None:
        result = isodelta(timedelta(days=2))
        assert result == "P2D"

    def test_raises_for_non_timedelta(self) -> None:
        with pytest.raises(ValueError, match="expected `timedelta`"):
            isodelta(42)  # type: ignore[arg-type]


class TestSdelta:
    def test_microseconds(self) -> None:
        result = sdelta(timedelta(microseconds=500))
        assert result == "500us"

    def test_milliseconds(self) -> None:
        result = sdelta(timedelta(milliseconds=250))
        assert result == "250ms"

    def test_seconds(self) -> None:
        result = sdelta(timedelta(seconds=5))
        assert result == "5s"

    def test_minutes(self) -> None:
        result = sdelta(timedelta(minutes=3))
        assert result == "3m"

    def test_hours(self) -> None:
        result = sdelta(timedelta(hours=2))
        assert result == "2h"

    def test_days(self) -> None:
        result = sdelta(timedelta(days=7))
        assert result == "7d"

    def test_fractional_seconds(self) -> None:
        result = sdelta(timedelta(seconds=1.5))
        assert result == "1.5s"

    def test_decimals_parameter(self) -> None:
        result = sdelta(timedelta(seconds=1), decimals=2)
        assert result == "1s"

    def test_decimals_with_fraction(self) -> None:
        result = sdelta(timedelta(seconds=1.5), decimals=3)
        assert result == "1.5s"

    def test_space_parameter(self) -> None:
        result = sdelta(timedelta(seconds=5), space=True)
        assert result == "5 s"

    def test_space_and_decimals(self) -> None:
        result = sdelta(timedelta(hours=2, minutes=30), space=True, decimals=1)
        assert result == "2.5 h"

    def test_raises_for_non_timedelta(self) -> None:
        with pytest.raises(ValueError, match="expected `timedelta`"):
            sdelta(42)  # type: ignore[arg-type]

    def test_boundary_exactly_one_millisecond(self) -> None:
        result = sdelta(timedelta(milliseconds=1))
        assert result == "1ms"

    def test_boundary_exactly_one_second(self) -> None:
        result = sdelta(timedelta(seconds=1))
        assert result == "1s"

    def test_boundary_exactly_one_minute(self) -> None:
        result = sdelta(timedelta(minutes=1))
        assert result == "1m"

    def test_boundary_exactly_one_hour(self) -> None:
        result = sdelta(timedelta(hours=1))
        assert result == "1h"

    def test_boundary_exactly_one_day(self) -> None:
        result = sdelta(timedelta(days=1))
        assert result == "1d"

    def test_just_below_one_millisecond(self) -> None:
        result = sdelta(timedelta(microseconds=999))
        assert result == "999us"

    def test_just_below_one_second(self) -> None:
        result = sdelta(timedelta(milliseconds=999))
        assert result == "999ms"


class TestParseSdelta:
    def test_parse_microseconds(self) -> None:
        assert _parse_sdelta("500us") == timedelta(microseconds=500)

    def test_parse_milliseconds(self) -> None:
        assert _parse_sdelta("250ms") == timedelta(milliseconds=250)

    def test_parse_seconds(self) -> None:
        assert _parse_sdelta("5s") == timedelta(seconds=5)

    def test_parse_minutes(self) -> None:
        assert _parse_sdelta("3m") == timedelta(minutes=3)

    def test_parse_hours(self) -> None:
        assert _parse_sdelta("2h") == timedelta(hours=2)

    def test_parse_days(self) -> None:
        assert _parse_sdelta("7d") == timedelta(days=7)

    def test_parse_with_spaces(self) -> None:
        assert _parse_sdelta("  5 s  ") == timedelta(seconds=5)

    def test_parse_uppercase(self) -> None:
        assert _parse_sdelta("5S") == timedelta(seconds=5)

    def test_parse_fractional(self) -> None:
        assert _parse_sdelta("1.5s") == timedelta(seconds=1.5)

    def test_invalid_suffix_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid suffixed time-delta"):
            _parse_sdelta("5x")

    def test_no_number_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid suffixed time-delta"):
            _parse_sdelta("ms")

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid suffixed time-delta"):
            _parse_sdelta(42)  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid suffixed time-delta"):
            _parse_sdelta("")


class TestFakeNow:
    def test_default_is_none(self) -> None:
        set_fake_now(None)
        assert get_fake_now() is None

    def test_set_and_get(self) -> None:
        fake_time = datetime(2000, 1, 1, tzinfo=UTC)
        set_fake_now(fake_time)
        try:
            assert get_fake_now() == fake_time
        finally:
            set_fake_now(None)

    def test_clear_with_none(self) -> None:
        fake_time = datetime(2000, 1, 1, tzinfo=UTC)
        set_fake_now(fake_time)
        set_fake_now(None)
        assert get_fake_now() is None

    def test_utc_uses_fake_now(self) -> None:
        fake_time = datetime(2025, 12, 25, 0, 0, 0, tzinfo=UTC)
        set_fake_now(fake_time)
        try:
            assert utc() == fake_time
        finally:
            set_fake_now(None)

    def test_utc_returns_real_time_when_cleared(self) -> None:
        set_fake_now(None)
        before = datetime.now(UTC)
        result = utc()
        after = datetime.now(UTC)
        assert before <= result <= after
