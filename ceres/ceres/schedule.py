from abc import abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Literal, Sequence

from apscheduler.triggers.cron import CronTrigger as InternalCronTrigger
from apscheduler.triggers.interval import IntervalTrigger as InternalIntervalTrigger
from pydantic import validator

from .data import DateTime, ImmutableDataObject, PositiveTimeDelta


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

    def __init__(self, crontab: timedelta, **kwargs: object) -> None:
        super().__init__(crontab=crontab)  # type: ignore

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

    def __init__(self, interval: timedelta, **kwargs: object) -> None:
        super().__init__(interval=interval)  # type: ignore

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

    def __init__(self, schedules: Iterable["Schedule"], **kwargs: object) -> None:
        super().__init__(schedules=schedules)  # type: ignore

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
        self.__inner = InternalCronTrigger.from_crontab(schedule.crontab)

    @property
    def schedule(self) -> CronSchedule:
        return self.__schedule

    def next(self, previous: datetime | None, now: datetime) -> datetime | None:
        return self.__inner.get_next_fire_time(previous, now)


class IntervalTrigger(Trigger):
    def __init__(self, schedule: IntervalSchedule) -> None:
        super().__init__()
        self.__schedule = schedule
        self.__inner = InternalIntervalTrigger(
            seconds=int(schedule.interval.total_seconds()),
            start_date=self.__schedule.start,
            end_date=self.__schedule.end,
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
