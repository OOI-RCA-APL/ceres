import datetime as dt
from abc import abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Literal, Sequence

from apscheduler.triggers.cron import CronTrigger as InternalCronTrigger
from apscheduler.triggers.interval import IntervalTrigger as BaseInternalIntervalTrigger
from apscheduler.util import normalize
from pydantic import validator

from ceres.data import DateTime, ImmutableDataObject, PositiveTimeDelta
from ceres.internal.utilities import CacheDict


class ScheduleKind(str, Enum):
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
    kind: Literal[ScheduleKind.CRON] = ScheduleKind.CRON
    crontab: str

    @validator("crontab")
    def _validate_crontab(cls, value: str) -> str:
        try:
            InternalCronTrigger.from_crontab(value)
        except Exception:
            raise ValueError("invalid crontab expression")

        return value

    def as_trigger(self) -> "CronTrigger":
        return CronTrigger(self)


class IntervalSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL
    interval: PositiveTimeDelta
    start: DateTime | None = None
    end: DateTime | None = None
    multiplier: float = 1
    min: timedelta | None = None
    max: timedelta | None = None

    @validator("interval")
    def _validate_interval(cls, value: timedelta) -> timedelta:
        if value.microseconds != 0:
            raise ValueError("sub-second interval resolution is not allowed")

        return value

    def as_trigger(self) -> "IntervalTrigger":
        return IntervalTrigger(self)


class OrSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.OR] = ScheduleKind.OR
    schedules: Sequence["Schedule"]

    def __or__(self, other: "Schedule") -> "OrSchedule":
        if isinstance(other, OrSchedule):
            return OrSchedule(schedules=[*self.schedules, *other.schedules])

        return OrSchedule(schedules=[*self.schedules, other])

    def as_trigger(self) -> "OrTrigger":
        return OrTrigger(self)


Schedule = CronSchedule | IntervalSchedule | OrSchedule  # type: ignore

OrSchedule.update_forward_refs()


class Trigger:
    __slots__ = ()

    @abstractmethod
    def next(self, previous: datetime | None, now: datetime) -> datetime | None:
        ...

    def iterate(self, start: datetime, end: datetime) -> Iterable[datetime]:
        current = start

        while current < end:
            current = self.next(None, start)
            if current is None:
                break

            yield current


class CronTrigger(Trigger):
    def __init__(self, schedule: CronSchedule) -> None:
        super().__init__()
        self.__schedule = schedule
        self.__inner = InternalCronTrigger.from_crontab(schedule.crontab, timezone=dt.timezone.utc)

    def get_next_fire_time(
        self,
        previous_fire_time: datetime | None,
        now: datetime,
    ) -> datetime | None:
        return self.__inner.get_next_fire_time(previous_fire_time, now)

    @property
    def schedule(self) -> CronSchedule:
        return self.__schedule

    def next(self, previous: datetime | None, now: datetime) -> datetime | None:
        return self.__inner.get_next_fire_time(previous, now)


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
        self.__cache: CacheDict[datetime, int] = CacheDict()

    def get_next_fire_time(
        self,
        previous_fire_time: datetime | None,
        now: datetime,
    ) -> datetime | None:
        if self.end_date is not None and now > self.end_date:
            return None

        next_fire_time: datetime | None = None

        if now < self.start_date:
            next_fire_time = self.start_date
        else:
            start = self.start_date.timestamp()
            end = now.timestamp()
            base = self.interval.total_seconds()
            min = self.min.total_seconds() if self.min is not None else None
            max = self.max.total_seconds() if self.max is not None else None

            iteration = 0
            current = start
            for previous_now, previous_iteration in self.__cache.items():
                if now >= previous_now and previous_iteration > iteration:
                    iteration = previous_iteration

            while current < end:
                interval = base * self.multiplier**iteration
                if min is not None and interval < min:
                    interval = min
                if max is not None and interval > max:
                    interval = max

                if current + interval >= end:
                    current = current + interval
                    self.__cache[now] = iteration
                    break

                current += interval
                iteration += 1

            next_fire_time = datetime.fromtimestamp(current, dt.timezone.utc)

        if self.jitter is not None:
            next_fire_time = self._apply_jitter(next_fire_time, self.jitter, now)

        if self.end_date is not None and next_fire_time > self.end_date:
            return None

        return normalize(next_fire_time)


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

    @property
    def schedule(self) -> IntervalSchedule:
        return self.__schedule

    def next(self, previous: datetime | None, now: datetime) -> datetime | None:
        return self.__inner.get_next_fire_time(previous, now)


class OrTrigger(Trigger):
    def __init__(self, schedule: OrSchedule) -> None:
        super().__init__()
        self.__schedule = schedule
        self.__triggers = [schedule.as_trigger() for schedule in self.__schedule.schedules]

    @property
    def schedule(self) -> OrSchedule:
        return self.__schedule

    def next(self, previous: datetime | None, now: datetime) -> datetime | None:
        minimum: datetime | None = None
        for trigger in self.__triggers:
            current = trigger.next(previous, now)
            if current is None:
                continue
            if current >= now and current < minimum:
                minimum = current

        return minimum
