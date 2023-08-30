import datetime as dt
import math
from abc import abstractmethod
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Iterable, Literal, Sequence

from apscheduler.triggers.cron import CronTrigger as InternalCronTrigger
from apscheduler.triggers.interval import IntervalTrigger as BaseInternalIntervalTrigger
from apscheduler.util import normalize
from pydantic import FieldValidationInfo, PositiveFloat, field_validator

from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.internal.utilities import StrEnum
from ceres.timing import utc


class ScheduleType(StrEnum):
    CRON = "cron"
    INTERVAL = "interval"
    OR = "or"


class BaseSchedule(ImmutableDataObject):
    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return OrSchedule(schedules=[self, other])

    @abstractmethod
    def as_trigger(self) -> "Trigger":
        ...


class CronSchedule(BaseSchedule):
    type: Literal[ScheduleType.CRON] = ScheduleType.CRON
    crontab: str

    @field_validator("crontab")
    def _validate_crontab(cls, value: str) -> str:
        try:
            InternalCronTrigger.from_crontab(value)
        except Exception:
            raise ValueError("invalid crontab expression")

        return value

    def as_trigger(self) -> "CronTrigger":
        return CronTrigger(self)


class IntervalSchedule(BaseSchedule):
    type: Literal[ScheduleType.INTERVAL] = ScheduleType.INTERVAL
    interval: PositiveTimeDelta
    start: DateTime | None = None
    end: DateTime | None = None
    multiplier: PositiveFloat = 1
    min: PositiveTimeDelta | None = None
    max: PositiveTimeDelta | None = None

    @field_validator("interval")
    def _validate_interval(cls, value: timedelta) -> timedelta:
        if value.microseconds != 0:
            raise ValueError("sub-second interval resolution is not allowed")

        return value

    @field_validator("min")
    def _validate_min(
        cls,
        min: float | None,
        info: FieldValidationInfo,
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
        info: FieldValidationInfo,
    ) -> float | None:
        interval = info.data.get("interval")
        if max is None or interval is None:
            return None
        if max < interval:
            raise ValueError("max must be >= interval")

        return max

    def as_trigger(self) -> "IntervalTrigger":
        return IntervalTrigger(self)


class OrSchedule(BaseSchedule):
    type: Literal[ScheduleType.OR] = ScheduleType.OR
    schedules: Sequence["Schedule"]

    def __or__(self, other: "Schedule") -> "OrSchedule":
        if isinstance(other, OrSchedule):
            return OrSchedule(schedules=[*self.schedules, *other.schedules])

        return OrSchedule(schedules=[*self.schedules, other])

    def as_trigger(self) -> "OrTrigger":
        return OrTrigger(self)


Schedule = CronSchedule | IntervalSchedule | OrSchedule  # type: ignore

OrSchedule.model_rebuild()


class Trigger:
    __slots__ = ()

    @abstractmethod
    def get_next_fire_time(self, previous: datetime | None, now: datetime) -> datetime | None:
        ...

    def get_fire_times(
        self,
        start: datetime | None = None,
        *,
        end: datetime | None = None,
        count: int | None = None,
    ) -> Iterable[datetime]:
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
    def __init__(self, schedule: CronSchedule) -> None:
        super().__init__()
        self.__schedule = schedule
        self.__inner = InternalCronTrigger.from_crontab(schedule.crontab, timezone=dt.timezone.utc)

    @property
    def schedule(self) -> CronSchedule:
        return self.__schedule

    def get_next_fire_time(
        self,
        previous: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        return self.__inner.get_next_fire_time(previous, now)


class IntervalTrigger(Trigger):
    def __init__(self, schedule: IntervalSchedule) -> None:
        super().__init__()
        self.__schedule = schedule
        self.__inner = InternalIntervalTrigger(
            seconds=int(schedule.interval.total_seconds()),
            start_date=self.__schedule.start,
            end_date=self.__schedule.end,
            multiplier=self.__schedule.multiplier,
            min=self.__schedule.min,
            max=self.__schedule.max,
        )

        self.start: datetime = self.__inner.start_date

    @property
    def schedule(self) -> IntervalSchedule:
        return self.__schedule

    def get_next_fire_time(
        self,
        previous: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        return self.__inner.get_next_fire_time(previous, now)


class OrTrigger(Trigger):
    def __init__(self, schedule: OrSchedule) -> None:
        super().__init__()
        self.__schedule = schedule
        self.__triggers = [schedule.as_trigger() for schedule in self.__schedule.schedules]

    @property
    def schedule(self) -> OrSchedule:
        return self.__schedule

    def get_next_fire_time(
        self,
        previous: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        minimum: datetime | None = None
        for trigger in self.__triggers:
            current = trigger.get_next_fire_time(previous, now)
            if current is None:
                continue
            if current >= now and current < minimum:
                minimum = current

        return minimum


class InternalIntervalTrigger(BaseInternalIntervalTrigger):
    if TYPE_CHECKING:
        start_date: datetime

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
            timezone=dt.timezone.utc,
            jitter=jitter,
        )
        self.multiplier = multiplier
        self.min = min
        self.max = max
        self.start_date = start_date or utc() - timedelta(microseconds=1)

    def get_next_fire_time(
        self,
        previous_fire_time: datetime | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = utc()

        if self.end_date is not None and now > self.end_date:
            return None

        next_fire_time: datetime | None = None

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
                (math.log(((runtime * (multiplier - 1)) / interval) + 1) / math.log(multiplier))
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
