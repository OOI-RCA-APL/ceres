import datetime as dt
from datetime import datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from ceres.schedule import (
    CronSchedule,
    CronTrigger,
    IntervalSchedule,
    IntervalTrigger,
    OrSchedule,
    OrTrigger,
    ScheduleExpr,
    _compute_fire_time_delay,
    _compute_iterations_and_fire_time_delay,
    _compute_runtime,
)


def _utc(*args: int) -> datetime:
    """Build a timezone-aware UTC datetime from positional arguments."""
    return datetime(*args, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ["schedule", "expected"],
    [
        [
            IntervalSchedule(
                interval=timedelta(seconds=5),
            ),
            [timedelta(seconds=5)] * 10,
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=1),
                multiplier=2,
            ),
            [
                timedelta(seconds=1),
                timedelta(seconds=2),
                timedelta(seconds=4),
                timedelta(seconds=8),
                timedelta(seconds=16),
                timedelta(seconds=32),
                timedelta(seconds=64),
            ],
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=1),
                multiplier=2,
                max=timedelta(seconds=30),
            ),
            [
                timedelta(seconds=1),
                timedelta(seconds=2),
                timedelta(seconds=4),
                timedelta(seconds=8),
                timedelta(seconds=16),
                timedelta(seconds=30),
                timedelta(seconds=30),
            ],
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=16),
                multiplier=0.5,
            ),
            [
                timedelta(seconds=16),
                timedelta(seconds=8),
                timedelta(seconds=4),
                timedelta(seconds=2),
                timedelta(seconds=1),
                timedelta(seconds=0.5),
            ],
        ],
        [
            IntervalSchedule(
                interval=timedelta(seconds=16),
                multiplier=0.5,
                min=timedelta(seconds=3),
            ),
            [
                timedelta(seconds=16),
                timedelta(seconds=8),
                timedelta(seconds=4),
                timedelta(seconds=3),
                timedelta(seconds=3),
            ],
        ],
    ],
)
def test_interval_schedule(schedule: IntervalSchedule, expected: list[timedelta]) -> None:
    trigger = schedule.create_trigger()
    start = trigger.start
    now = start - timedelta(seconds=1)
    assert trigger.get_next_fire_time(now=now) == start

    now = start

    for delay in expected:
        next = trigger.get_next_fire_time(now=now + timedelta(milliseconds=1))
        assert next is not None
        assert next == now + delay
        now = next


class TestCronScheduleConstruction:
    def test_from_valid_crontab_string(self) -> None:
        schedule = CronSchedule(crontab="*/5 * * * *")
        assert schedule.crontab == "*/5 * * * *"

    def test_from_invalid_crontab_string_raises(self) -> None:
        with pytest.raises(ValidationError, match="invalid crontab expression"):
            CronSchedule(crontab="not-a-crontab")

    def test_model_validator_coerces_crontab_via_schedule_expr(self) -> None:
        """The `ScheduleExpr` before-validator coerces a bare crontab string."""
        adapter = TypeAdapter(ScheduleExpr)
        schedule = adapter.validate_python("0 12 * * *")
        assert isinstance(schedule, CronSchedule)
        assert schedule.crontab == "0 12 * * *"

    def test_model_validator_passes_through_non_crontab_string(self) -> None:
        """A string that is not a valid crontab or interval expression fails validation."""
        adapter = TypeAdapter(ScheduleExpr)
        with pytest.raises(ValidationError):
            adapter.validate_python("not-valid")


class TestCronTrigger:
    def test_create_trigger_returns_cron_trigger(self) -> None:
        schedule = CronSchedule(crontab="0 * * * *")
        trigger = schedule.create_trigger()
        assert isinstance(trigger, CronTrigger)
        assert trigger.schedule is schedule

    def test_get_next_fire_time_returns_next_hour(self) -> None:
        schedule = CronSchedule(crontab="0 * * * *")
        trigger = schedule.create_trigger()
        now = _utc(2025, 6, 1, 10, 30, 0)
        result = trigger.get_next_fire_time(now=now)
        assert result == _utc(2025, 6, 1, 11, 0, 0)

    def test_get_next_fire_time_defaults_now_to_utc(self) -> None:
        schedule = CronSchedule(crontab="0 0 1 1 *")
        trigger = schedule.create_trigger()
        result = trigger.get_next_fire_time()
        assert result is not None

    def test_get_next_fire_time_with_previous(self) -> None:
        schedule = CronSchedule(crontab="0 * * * *")
        trigger = schedule.create_trigger()
        now = _utc(2025, 6, 1, 10, 30, 0)
        previous = _utc(2025, 6, 1, 10, 0, 0)
        result = trigger.get_next_fire_time(previous=previous, now=now)
        assert result == _utc(2025, 6, 1, 11, 0, 0)


class TestIntervalScheduleValidation:
    def test_sub_second_interval_raises(self) -> None:
        with pytest.raises(ValidationError, match="sub-second interval"):
            IntervalSchedule(interval=timedelta(milliseconds=500))

    def test_min_greater_than_interval_raises(self) -> None:
        with pytest.raises(ValidationError, match="min must be <= interval"):
            IntervalSchedule(
                interval=timedelta(seconds=5),
                min=timedelta(seconds=10),
            )

    def test_max_less_than_interval_raises(self) -> None:
        with pytest.raises(ValidationError, match="max must be >= interval"):
            IntervalSchedule(
                interval=timedelta(seconds=10),
                max=timedelta(seconds=5),
            )

    def test_min_equal_to_interval_is_valid(self) -> None:
        schedule = IntervalSchedule(
            interval=timedelta(seconds=5),
            min=timedelta(seconds=5),
        )
        assert schedule.min == timedelta(seconds=5)

    def test_max_equal_to_interval_is_valid(self) -> None:
        schedule = IntervalSchedule(
            interval=timedelta(seconds=5),
            max=timedelta(seconds=5),
        )
        assert schedule.max == timedelta(seconds=5)

    def test_create_trigger_returns_interval_trigger(self) -> None:
        schedule = IntervalSchedule(interval=timedelta(seconds=10))
        trigger = schedule.create_trigger()
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.schedule is schedule


class TestIntervalTrigger:
    def test_with_explicit_start(self) -> None:
        start = _utc(2025, 1, 1, 0, 0, 0)
        schedule = IntervalSchedule(interval=timedelta(seconds=60), start=start)
        trigger = schedule.create_trigger()
        assert trigger.start == start

    def test_with_end_date_returns_none_after_end(self) -> None:
        start = _utc(2025, 1, 1, 0, 0, 0)
        end = _utc(2025, 1, 1, 0, 1, 0)
        schedule = IntervalSchedule(interval=timedelta(seconds=30), start=start, end=end)
        trigger = schedule.create_trigger()
        # Asking for next fire time well past the end should return None.
        result = trigger.get_next_fire_time(now=_utc(2025, 1, 1, 0, 2, 0))
        assert result is None

    def test_get_next_fire_time_defaults_now_to_utc(self) -> None:
        schedule = IntervalSchedule(interval=timedelta(seconds=60))
        trigger = schedule.create_trigger()
        result = trigger.get_next_fire_time()
        assert result is not None


class TestOrScheduleConstruction:
    def test_or_operator_on_two_schedules(self) -> None:
        cron = CronSchedule(crontab="0 * * * *")
        interval = IntervalSchedule(interval=timedelta(seconds=60))
        combined = cron | interval
        assert isinstance(combined, OrSchedule)
        assert len(combined.schedules) == 2

    def test_or_operator_flattens_or_schedules(self) -> None:
        cron1 = CronSchedule(crontab="0 * * * *")
        cron2 = CronSchedule(crontab="30 * * * *")
        interval = IntervalSchedule(interval=timedelta(seconds=60))
        combined = (cron1 | cron2) | interval
        assert isinstance(combined, OrSchedule)
        assert len(combined.schedules) == 3

    def test_or_operator_flattens_both_sides(self) -> None:
        cron1 = CronSchedule(crontab="0 * * * *")
        cron2 = CronSchedule(crontab="30 * * * *")
        cron3 = CronSchedule(crontab="15 * * * *")
        cron4 = CronSchedule(crontab="45 * * * *")
        left = cron1 | cron2
        right = cron3 | cron4
        combined = left | right
        assert isinstance(combined, OrSchedule)
        assert len(combined.schedules) == 4

    def test_or_with_non_or_schedule(self) -> None:
        cron1 = CronSchedule(crontab="0 * * * *")
        cron2 = CronSchedule(crontab="30 * * * *")
        or_schedule = cron1 | cron2
        interval = IntervalSchedule(interval=timedelta(seconds=60))
        combined = or_schedule | interval
        assert isinstance(combined, OrSchedule)
        assert len(combined.schedules) == 3


class TestOrTrigger:
    def test_create_trigger_returns_or_trigger(self) -> None:
        cron = CronSchedule(crontab="0 * * * *")
        interval = IntervalSchedule(interval=timedelta(seconds=60))
        combined = cron | interval
        trigger = combined.create_trigger()
        assert isinstance(trigger, OrTrigger)
        assert trigger.schedule is combined

    def test_get_next_fire_time_returns_earliest(self) -> None:
        # Hourly cron (fires at :00) and every-30-minutes cron (fires at :00 and :30).
        cron_hourly = CronSchedule(crontab="0 * * * *")
        cron_half = CronSchedule(crontab="*/30 * * * *")
        combined = cron_hourly | cron_half
        trigger = combined.create_trigger()
        now = _utc(2025, 6, 1, 10, 15, 0)
        result = trigger.get_next_fire_time(now=now)
        # The half-hour cron fires next at 10:30, earlier than the hourly at 11:00.
        assert result == _utc(2025, 6, 1, 10, 30, 0)

    def test_get_next_fire_time_defaults_now_to_utc(self) -> None:
        cron = CronSchedule(crontab="0 * * * *")
        interval = IntervalSchedule(interval=timedelta(seconds=3600))
        combined = cron | interval
        trigger = combined.create_trigger()
        result = trigger.get_next_fire_time()
        assert result is not None

    def test_all_children_exhausted_returns_none(self) -> None:
        start = _utc(2025, 1, 1, 0, 0, 0)
        end = _utc(2025, 1, 1, 0, 0, 30)
        schedule1 = IntervalSchedule(interval=timedelta(seconds=10), start=start, end=end)
        schedule2 = IntervalSchedule(interval=timedelta(seconds=10), start=start, end=end)
        combined = OrSchedule(schedules=[schedule1, schedule2])
        trigger = combined.create_trigger()
        # Request well past the end of both schedules.
        result = trigger.get_next_fire_time(now=_utc(2025, 1, 1, 1, 0, 0))
        assert result is None


class TestScheduleExpr:
    def test_crontab_string_shorthand(self) -> None:
        adapter = TypeAdapter(ScheduleExpr)
        schedule = adapter.validate_python("*/5 * * * *")
        assert isinstance(schedule, CronSchedule)
        assert schedule.crontab == "*/5 * * * *"

    def test_interval_seconds_shorthand(self) -> None:
        adapter = TypeAdapter(ScheduleExpr)
        schedule = adapter.validate_python(60)
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.interval == timedelta(seconds=60)

    def test_interval_float_shorthand(self) -> None:
        adapter = TypeAdapter(ScheduleExpr)
        schedule = adapter.validate_python(30.0)
        assert isinstance(schedule, IntervalSchedule)
        assert schedule.interval == timedelta(seconds=30)

    def test_non_parseable_string_falls_through(self) -> None:
        adapter = TypeAdapter(ScheduleExpr)
        with pytest.raises(ValidationError):
            adapter.validate_python("not-a-schedule")

    def test_dict_passthrough_cron(self) -> None:
        adapter = TypeAdapter(ScheduleExpr)
        schedule = adapter.validate_python({"type": "cron", "crontab": "0 12 * * *"})
        assert isinstance(schedule, CronSchedule)

    def test_dict_passthrough_interval(self) -> None:
        adapter = TypeAdapter(ScheduleExpr)
        schedule = adapter.validate_python({"type": "interval", "interval": 120})
        assert isinstance(schedule, IntervalSchedule)


class TestGetFireTimes:
    def test_get_fire_times_with_count(self) -> None:
        start = _utc(2025, 1, 1, 0, 0, 0)
        schedule = IntervalSchedule(interval=timedelta(seconds=10), start=start)
        trigger = schedule.create_trigger()
        times = list(trigger.get_fire_times(start, count=3))
        assert len(times) <= 4
        for time in times:
            assert time >= start

    def test_get_fire_times_with_end_before_first_fire(self) -> None:
        """When `end` is before or at `start`, `get_fire_times` yields nothing."""
        start = _utc(2025, 1, 1, 0, 0, 10)
        end = _utc(2025, 1, 1, 0, 0, 10)
        schedule = IntervalSchedule(interval=timedelta(seconds=60), start=start)
        trigger = schedule.create_trigger()
        times = list(trigger.get_fire_times(start, end=end))
        assert times == []

    def test_get_fire_times_defaults_start_to_utc(self) -> None:
        schedule = IntervalSchedule(interval=timedelta(seconds=3600))
        trigger = schedule.create_trigger()
        times = list(trigger.get_fire_times(count=2))
        assert len(times) <= 3

    def test_get_fire_times_with_exhausted_trigger(self) -> None:
        start = _utc(2025, 1, 1, 0, 0, 0)
        end = _utc(2025, 1, 1, 0, 0, 30)
        schedule = IntervalSchedule(interval=timedelta(seconds=10), start=start, end=end)
        trigger = schedule.create_trigger()
        # Start iteration after the end date so the trigger is immediately exhausted.
        times = list(trigger.get_fire_times(_utc(2025, 1, 1, 1, 0, 0)))
        assert times == []


class TestComputeRuntime:
    def test_multiplier_one_returns_linear(self) -> None:
        result = _compute_runtime(timedelta(seconds=10), 1.0, 5)
        assert result == timedelta(seconds=50)

    def test_multiplier_two_geometric(self) -> None:
        result = _compute_runtime(timedelta(seconds=1), 2.0, 3)
        # (1 * (2^3 - 1)) / (2 - 1) = 7
        assert result == timedelta(seconds=7)


class TestComputeFireTimeDelay:
    def test_returns_none_when_inner_returns_none(self) -> None:
        # Use a multiplier < 1 without min, and a runtime that causes a math domain error
        # by making the log argument negative.
        result = _compute_fire_time_delay(
            runtime=timedelta(seconds=1000000),
            interval=timedelta(seconds=1),
            multiplier=0.001,
        )
        assert result is None


class TestComputeIterationsAndFireTimeDelay:
    def test_runtime_less_than_interval(self) -> None:
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=3),
            interval=timedelta(seconds=10),
            multiplier=2.0,
        )
        assert result == (1, timedelta(seconds=10))

    def test_multiplier_one_linear(self) -> None:
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=25),
            interval=timedelta(seconds=10),
            multiplier=1.0,
        )
        assert result is not None
        iterations, delay = result
        assert iterations == 3
        assert delay == timedelta(seconds=30)

    def test_no_limit_with_multiplier_greater_than_one(self) -> None:
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=10),
            interval=timedelta(seconds=1),
            multiplier=2.0,
        )
        assert result is not None
        iterations, delay = result
        assert delay >= timedelta(seconds=10)

    def test_no_limit_with_multiplier_less_than_one(self) -> None:
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=20),
            interval=timedelta(seconds=16),
            multiplier=0.5,
        )
        assert result is not None
        _, delay = result
        assert delay >= timedelta(seconds=20)

    def test_value_error_in_no_limit_path_returns_none(self) -> None:
        # When multiplier < 1 and runtime is extremely large, the log argument becomes negative.
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=1000000),
            interval=timedelta(seconds=1),
            multiplier=0.001,
        )
        assert result is None

    def test_value_error_in_pre_limit_iterations_returns_none(self) -> None:
        # A multiplier below one with a min above the interval makes the log argument
        # negative, a pair `Schedule` validation forbids, so the internal function is
        # called directly.
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=100),
            interval=timedelta(seconds=-1),
            multiplier=0.5,
            min=timedelta(seconds=1),
        )
        assert result is None

    def test_with_limit_runtime_before_limit_reached(self) -> None:
        # multiplier > 1 with max, but runtime is short enough that max is never reached.
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=5),
            interval=timedelta(seconds=1),
            multiplier=2.0,
            max=timedelta(seconds=1000),
        )
        assert result is not None
        _, delay = result
        assert delay >= timedelta(seconds=5)

    def test_with_limit_runtime_past_limit(self) -> None:
        # multiplier > 1 with max, runtime exceeds the point where max kicks in.
        result = _compute_iterations_and_fire_time_delay(
            runtime=timedelta(seconds=100),
            interval=timedelta(seconds=1),
            multiplier=2.0,
            max=timedelta(seconds=8),
        )
        assert result is not None
        iterations, delay = result
        assert delay >= timedelta(seconds=100)
        assert iterations > 0
