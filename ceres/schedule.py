import datetime as dt
import math
from abc import abstractmethod
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, TypeAlias, override

from apscheduler.triggers.cron import CronTrigger as InternalCronTrigger
from apscheduler.triggers.interval import IntervalTrigger as BaseInternalIntervalTrigger
from apscheduler.util import normalize
from pydantic import (
    BeforeValidator,
    Field,
    PositiveFloat,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ceres.data import DataObject, DateTime, PositiveTimeDelta, StrEnum
from ceres.timing import delta, utc

__all__ = [
    "Schedule",
    "ScheduleExpr",
    "CronSchedule",
    "IntervalSchedule",
    "OrSchedule",
    "Trigger",
    "CronTrigger",
    "IntervalTrigger",
    "OrTrigger",
]


class ScheduleType(StrEnum):
    """Discriminator identifying which concrete `Schedule` variant a value represents."""

    CRON = "cron"
    """Crontab-driven schedule."""
    INTERVAL = "interval"
    """Fixed or backoff-based interval schedule."""
    OR = "or"
    """Composite schedule that fires when any of its child schedules fires."""


class _BaseSchedule(DataObject.Frozen):
    def __or__(self, other: Schedule) -> OrSchedule:
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return OrSchedule(schedules=[self, other])

    @abstractmethod
    def create_trigger(self) -> Trigger:
        """Build a concrete `Trigger` that produces fire times matching this schedule."""
        ...


class CronSchedule(_BaseSchedule):
    """Schedule defined by a standard crontab expression."""

    type: Literal[ScheduleType.CRON] = ScheduleType.CRON
    """Schedule type discriminator, always `ScheduleType.CRON`."""
    crontab: str
    """Crontab expression controlling when the schedule fires."""

    @model_validator(mode="before")
    @classmethod
    def _validate_before(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                InternalCronTrigger.from_crontab(value)
                return cls(crontab=value)
            except Exception:
                pass

        return value

    @field_validator("crontab")
    def _validate_crontab(cls, value: str) -> str:
        try:
            InternalCronTrigger.from_crontab(value)
        except Exception:
            raise ValueError("invalid crontab expression")

        return value

    @override
    def create_trigger(self) -> CronTrigger:
        return CronTrigger(self)


class IntervalSchedule(_BaseSchedule):
    """Schedule that fires on a fixed interval with optional exponential backoff and bounds."""

    type: Literal[ScheduleType.INTERVAL] = ScheduleType.INTERVAL
    """Schedule type discriminator, always `ScheduleType.INTERVAL`."""
    interval: PositiveTimeDelta
    """Base delay between fires, with sub-second resolution disallowed."""
    start: DateTime | None = None
    """Earliest time the schedule is allowed to fire, defaults to the current time."""
    end: DateTime | None = None
    """Latest time the schedule is allowed to fire, unbounded when `None`."""
    multiplier: PositiveFloat = 1
    """Multiplicative growth factor applied to successive intervals, `1` leaves them unchanged."""
    min: PositiveTimeDelta | None = None
    """Lower bound on the effective interval after scaling, must be `<= interval`."""
    max: PositiveTimeDelta | None = None
    """Upper bound on the effective interval after scaling, must be `>= interval`."""

    @model_validator(mode="before")
    @classmethod
    def _validate_before(cls, value: Any) -> Any:
        try:
            interval = delta(value)
            cls(interval=interval)
        except Exception:
            pass

        return value

    @field_validator("interval")
    def _validate_interval(cls, value: timedelta) -> timedelta:
        if value.microseconds != 0:
            raise ValueError("sub-second interval resolution is not allowed")

        return value

    @field_validator("min")
    def _validate_min(
        cls,
        min: float | None,
        info: ValidationInfo,
    ) -> float | None:
        interval = info.data.get("interval")
        if min is None or interval is None:
            return None
        if min > interval:
            raise ValueError("min must be <= interval")

        return min

    @field_validator("max")
    def _validate_max(
        cls,
        max: float | None,
        info: ValidationInfo,
    ) -> float | None:
        interval = info.data.get("interval")
        if max is None or interval is None:
            return None
        if max < interval:
            raise ValueError("max must be >= interval")

        return max

    @override
    def create_trigger(self) -> IntervalTrigger:
        return IntervalTrigger(self)


class OrSchedule(_BaseSchedule):
    """Composite schedule that fires whenever any of its child schedules fires."""

    type: Literal[ScheduleType.OR] = ScheduleType.OR
    """Schedule type discriminator, always `ScheduleType.OR`."""
    schedules: list[Schedule]
    """Child schedules whose fire times are unioned together."""

    @override
    def __or__(self, other: Schedule) -> OrSchedule:
        if isinstance(other, OrSchedule):
            return OrSchedule(schedules=[*self.schedules, *other.schedules])

        return OrSchedule(schedules=[*self.schedules, other])

    @override
    def create_trigger(self) -> OrTrigger:
        return OrTrigger(self)


Schedule: TypeAlias = CronSchedule | IntervalSchedule | OrSchedule
"""Union of all concrete schedule variants, discriminated by `type`."""


def _pre_validate_schedule_expression(value: Any) -> Any:
    if isinstance(value, str | int | float):
        try:
            InternalCronTrigger.from_crontab(value)
            return CronSchedule(crontab=str(value))
        except Exception:
            pass

        try:
            interval = delta(value)
            return IntervalSchedule(interval=interval)
        except Exception:
            pass

    return value


ScheduleExpr: TypeAlias = Annotated[
    Schedule,
    Field(discriminator="type"),
    BeforeValidator(_pre_validate_schedule_expression),
]
"""Pydantic-annotated `Schedule` accepting crontab strings or interval expressions as shorthand."""


class Trigger:
    """Base class for objects that produce a stream of fire times from a `Schedule`."""

    __slots__ = ()

    @abstractmethod
    def get_next_fire_time(self, previous: datetime | None, now: datetime) -> datetime | None:
        """Return the next fire time at or after `now`, or `None` if the trigger is exhausted.

        Args:
            previous: The most recent fire time produced by this trigger, if any.
            now: Reference time used as the lower bound for the next fire time.
        """
        ...

    def get_fire_times(
        self,
        start: datetime | None = None,
        *,
        end: datetime | None = None,
        count: int | None = None,
    ) -> Iterable[datetime]:
        """Yield successive fire times produced by the trigger.

        Args:
            start: Time to begin iteration from, defaults to the current UTC time.
            end: Upper bound on fire times, iteration stops at the first fire time at or past this.
            count: Maximum number of fire times to yield, unbounded when `None`.

        Yields:
            Fire times in chronological order.
        """
        if start is None:
            start = utc()

        current = start
        current_count = 0

        while True:
            if end is not None:
                if current >= end:
                    break
            if count is not None:
                if current_count > count:
                    break

            current = self.get_next_fire_time(None, start)
            if current is None:
                break

            yield current
            current_count += 1


class CronTrigger(Trigger):
    """Trigger backed by a `CronSchedule` evaluated in UTC."""

    __slots__ = (
        "_schedule",
        "_inner",
    )

    def __init__(self, schedule: CronSchedule) -> None:
        super().__init__()
        self._schedule = schedule
        self._inner = InternalCronTrigger.from_crontab(schedule.crontab, timezone=dt.UTC)

    @property
    def schedule(self) -> CronSchedule:
        """The `CronSchedule` backing this trigger."""
        return self._schedule

    @override
    def get_next_fire_time(
        self,
        previous: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        return self._inner.get_next_fire_time(previous, now)


class IntervalTrigger(Trigger):
    """Trigger backed by an `IntervalSchedule` with optional scaling and bounds."""

    __slots__ = (
        "_schedule",
        "_inner",
        "_start",
    )

    def __init__(self, schedule: IntervalSchedule) -> None:
        super().__init__()
        self._schedule = schedule
        self._inner = _InternalIntervalTrigger(
            seconds=int(schedule.interval.total_seconds()),
            start_date=self._schedule.start,
            end_date=self._schedule.end,
            multiplier=self._schedule.multiplier,
            min=self._schedule.min,
            max=self._schedule.max,
        )

        self._start: datetime = self._inner.start_date

    @property
    def schedule(self) -> IntervalSchedule:
        """The `IntervalSchedule` backing this trigger."""
        return self._schedule

    @property
    def start(self) -> datetime:
        """The effective start time used as the origin for interval calculations."""
        return self._start

    @override
    def get_next_fire_time(
        self,
        previous: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        return self._inner.get_next_fire_time(previous, now)


class OrTrigger(Trigger):
    """Trigger that fires at the earliest next time produced by any of its child triggers."""

    __slots__ = (
        "_schedule",
        "_triggers",
    )

    def __init__(self, schedule: OrSchedule) -> None:
        super().__init__()
        self._schedule = schedule
        self._triggers = [schedule.create_trigger() for schedule in self._schedule.schedules]

    @property
    def schedule(self) -> OrSchedule:
        """The `OrSchedule` backing this trigger."""
        return self._schedule

    @override
    def get_next_fire_time(
        self,
        previous: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        minimum: datetime | None = None
        for trigger in self._triggers:
            current = trigger.get_next_fire_time(previous, now)
            if current is None:
                continue
            if current >= now and (minimum is None or current < minimum):
                minimum = current

        return minimum


class _InternalIntervalTrigger(BaseInternalIntervalTrigger):
    __slots__ = (
        "multiplier",
        "min",
        "max",
    )

    def __init__(
        self,
        weeks: int = 0,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: int = 0,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        jitter: float | None = None,
        multiplier: float = 1,
        min: timedelta | None = None,
        max: timedelta | None = None,
    ):
        super().__init__(
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
            start_date=start_date,
            end_date=end_date,
            timezone=dt.UTC,
            jitter=jitter,
        )
        self.multiplier = multiplier
        self.min = min
        self.max = max
        self.start_date = start_date or utc() - timedelta(microseconds=1)

    @override
    def get_next_fire_time(
        self,
        previous_fire_time: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        if self.end_date is not None and now > self.end_date:
            return None

        if now < self.start_date:
            next_fire_time = self.start_date
        else:
            runtime = now - self.start_date
            delay = _compute_fire_time_delay(
                runtime=runtime,
                interval=self.interval,
                multiplier=self.multiplier,
                min=self.min,
                max=self.max,
            )
            if delay is None:
                return None

            next_fire_time = self.start_date + delay

        if self.jitter is not None:
            next_fire_time = self._apply_jitter(next_fire_time, self.jitter, now)

        if self.end_date is not None and next_fire_time > self.end_date:
            return None

        return normalize(next_fire_time)


def _compute_runtime(
    interval: timedelta,
    multiplier: float,
    iterations: int,
) -> timedelta:
    if multiplier == 1:
        return interval * iterations

    # https://www.wolframalpha.com/input?i2d=true&i=simplify+d+%3DSum%5Bv*Power%5Bm%2Ck%5D%2C%7Bk%2C0%2Cn+-+1%7D%5D
    return (interval * ((multiplier**iterations) - 1)) / (multiplier - 1)


def _compute_fire_time_delay(
    *,
    runtime: timedelta,
    interval: timedelta,
    multiplier: float,
    min: timedelta | None = None,
    max: timedelta | None = None,
) -> timedelta | None:
    result = _compute_iterations_and_fire_time_delay(
        runtime=runtime,
        interval=interval,
        multiplier=multiplier,
        min=min,
        max=max,
    )

    if result is None:
        return None

    _, next_fire_time = result
    return next_fire_time


def _compute_iterations_and_fire_time_delay(
    *,
    runtime: timedelta,
    interval: timedelta,
    multiplier: float,
    min: timedelta | None = None,
    max: timedelta | None = None,
) -> tuple[int, timedelta] | None:  # iterations, next_fire_time
    if runtime <= interval:
        return 1, interval
    if multiplier < 1:
        limit = min
    elif multiplier > 1:
        limit = max
    else:
        iterations = math.ceil(runtime / interval)
        return iterations, interval * iterations

    if limit is None:
        # Compute the number of iterations before the desired runtime is reached.
        # https://www.symbolab.com/solver/step-by-step/solve%20for%20n%2C%20d%20%3D%20%5Cleft(v%20%5Cleft(m%5E%7B%5Cleft(n%20%2B%201%5Cright)%7D%20-%201%5Cright)%5Cright)%2F%5Cleft(m%20-%201%5Cright)?or=input
        try:
            iterations = math.ceil(
                math.log(((runtime * (multiplier - 1)) / interval) + 1) / math.log(multiplier)
            )
        except ValueError:
            return None

        return iterations, _compute_runtime(interval, multiplier, iterations)

    # Compute the number of iterations before the min/max limit is reached.
    # https://www.symbolab.com/solver/step-by-step/solve%20for%20k%2C%20t%3Dv%20%5Ccdot%20m%5E%7Bk%7D?or=input
    try:
        pre_limit_iterations = math.ceil(math.log(limit / interval) / math.log(multiplier))
    except ValueError:
        return None

    pre_limit_runtime = _compute_runtime(interval, multiplier, pre_limit_iterations)

    # If the min/max limit is not reached before the desired runtime, then just run the function
    # again without it.
    if runtime < pre_limit_runtime:
        return _compute_iterations_and_fire_time_delay(
            runtime=runtime,
            interval=interval,
            multiplier=multiplier,
        )

    remaining_runtime = runtime - pre_limit_runtime
    post_limit_result = _compute_iterations_and_fire_time_delay(
        runtime=remaining_runtime,
        interval=limit,
        multiplier=1,
    )
    if post_limit_result is None:
        return None

    post_limit_iterations, post_limit_runtime = post_limit_result
    iterations = pre_limit_iterations + post_limit_iterations
    next_fire_time_delay = pre_limit_runtime + post_limit_runtime

    return iterations, next_fire_time_delay
