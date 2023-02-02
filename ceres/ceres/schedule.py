from datetime import timedelta
from enum import Enum
from typing import Iterable, Literal, Sequence

from apscheduler.triggers.cron import CronTrigger
from pydantic import validator

from .data import ImmutableDataObject, PositiveTimeDelta


class ScheduleKind(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    AND = "and"
    OR = "or"


class BaseSchedule(ImmutableDataObject):
    def __and__(self, other: "Schedule") -> "AndSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return AndSchedule(schedules=[self, other])

    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return OrSchedule(schedules=[self, other])


class CronSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.CRON] = ScheduleKind.CRON
    crontab: str

    def __init__(self, crontab: timedelta, **kwargs: object) -> None:
        super().__init__(crontab=crontab)  # type: ignore

    @validator("crontab")
    def _validate_crontab(cls, value: str) -> str:
        try:
            CronTrigger.from_crontab(value)
        except Exception:
            raise ValueError("invalid crontab expression")

        return value


class IntervalSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL
    interval: PositiveTimeDelta

    def __init__(self, interval: timedelta, **kwargs: object) -> None:
        super().__init__(interval=interval)  # type: ignore

    @validator("interval")
    def _validate_interval(cls, value: timedelta) -> timedelta:
        if value.microseconds != 0:
            raise ValueError("sub-second interval resolution is not allowed")

        return value


class AndSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.AND] = ScheduleKind.AND
    schedules: Sequence["Schedule"]

    def __init__(self, schedules: Iterable["Schedule"], **kwargs: object) -> None:
        super().__init__(schedules=schedules)  # type: ignore

    def __and__(self, other: "Schedule") -> "AndSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        if isinstance(other, AndSchedule):
            return AndSchedule(schedules=[*self.schedules, *other.schedules])

        return AndSchedule(schedules=[*self.schedules, other])


class OrSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.OR] = ScheduleKind.OR
    schedules: Sequence["Schedule"]

    def __init__(self, schedules: Iterable["Schedule"], **kwargs: object) -> None:
        super().__init__(schedules=schedules)  # type: ignore

    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        if isinstance(other, OrSchedule):
            return OrSchedule(schedules=[*self.schedules, *other.schedules])

        return OrSchedule(schedules=[*self.schedules, other])


Schedule = CronSchedule | IntervalSchedule | AndSchedule | OrSchedule  # type: ignore

AndSchedule.update_forward_refs()
OrSchedule.update_forward_refs()
