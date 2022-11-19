from datetime import timedelta
from enum import Enum
from typing import Any, Iterable, Literal

from pydantic import validator

from .data import FrozenDataObject
from .internal.utilities import (
    frozenlist,
    validate_crontab,
    validate_positive_timedelta,
)


class ScheduleKind(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    AND = "and"
    OR = "or"


class BaseSchedule(FrozenDataObject):
    def __and__(self, other: "Schedule") -> "AndSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return AndSchedule(schedules=frozenlist([self, other]))

    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return OrSchedule(schedules=frozenlist([self, other]))


class CronSchedule(BaseSchedule):
    crontab: str
    kind: Literal[ScheduleKind.CRON] = ScheduleKind.CRON

    def __init__(self, crontab: timedelta) -> None:
        super().__init__(crontab=crontab)  # type: ignore

    @validator("crontab")
    def _validate_crontab(cls, crontab: str) -> str:
        return validate_crontab(crontab)


class IntervalSchedule(BaseSchedule):
    interval: timedelta
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL

    def __init__(self, interval: timedelta) -> None:
        super().__init__(interval=interval)  # type: ignore

    @validator("interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class AndSchedule(BaseSchedule):
    schedules: frozenlist["Schedule"]
    kind: Literal[ScheduleKind.AND] = ScheduleKind.AND

    def __init__(self, schedules: Iterable["Schedule"]) -> None:
        super().__init__(schedules=frozenlist(schedules))  # type: ignore

    def __and__(self, other: "Schedule") -> "AndSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        if isinstance(other, AndSchedule):
            return AndSchedule(schedules=frozenlist([*self.schedules, *other.schedules]))

        return AndSchedule(schedules=frozenlist([*self.schedules, other]))


class OrSchedule(BaseSchedule):
    schedules: frozenlist["Schedule"]
    kind: Literal[ScheduleKind.OR] = ScheduleKind.OR

    def __init__(self, schedules: Iterable["Schedule"]) -> None:
        super().__init__(schedules=frozenlist(schedules))  # type: ignore

    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        if isinstance(other, OrSchedule):
            return OrSchedule(schedules=frozenlist([*self.schedules, *other.schedules]))

        return OrSchedule(schedules=frozenlist([*self.schedules, other]))


Schedule = CronSchedule | IntervalSchedule | AndSchedule | OrSchedule  # type: ignore

AndSchedule.update_forward_refs()
OrSchedule.update_forward_refs()
