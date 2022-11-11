from datetime import timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import Field, validator

from .internal.utilities import (
    frozenlist,
    validate_crontab,
    validate_positive_timedelta,
)
from .utilities import vdc


class ScheduleKind(str, Enum):
    CRON = "cron"
    INTERVAL = "interval"
    AND = "and"
    OR = "or"


class BaseSchedule:
    def __and__(self, other: "Schedule") -> "AndSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return AndSchedule(schedules=frozenlist([self, other]))

    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        return OrSchedule(schedules=frozenlist([self, other]))


@vdc(kw_only=False, frozen=True)
class CronSchedule(BaseSchedule):
    crontab: str
    kind: Literal[ScheduleKind.CRON] = Field(default=ScheduleKind.CRON, init=False)

    @validator("crontab")
    def _validate_crontab(cls, crontab: str) -> str:
        return validate_crontab(crontab)


@vdc(kw_only=False, frozen=True)
class IntervalSchedule(BaseSchedule):
    interval: timedelta
    kind: Literal[ScheduleKind.INTERVAL] = Field(default=ScheduleKind.INTERVAL, init=False)

    @validator("interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


@vdc(kw_only=False, frozen=True)
class AndSchedule(BaseSchedule):
    schedules: frozenlist["Schedule"]
    kind: Literal[ScheduleKind.AND] = Field(default=ScheduleKind.AND, init=False)

    def __and__(self, other: "Schedule") -> "AndSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        if isinstance(other, AndSchedule):
            return AndSchedule(schedules=frozenlist([*self.schedules, *other.schedules]))

        return AndSchedule(schedules=frozenlist([*self.schedules, other]))


@vdc(kw_only=False, frozen=True)
class OrSchedule(BaseSchedule):
    schedules: frozenlist["Schedule"]
    kind: Literal[ScheduleKind.OR] = Field(default=ScheduleKind.OR, init=False)

    def __or__(self, other: "Schedule") -> "OrSchedule":
        assert isinstance(self, Schedule)
        assert isinstance(other, Schedule)
        if isinstance(other, OrSchedule):
            return OrSchedule(schedules=frozenlist([*self.schedules, *other.schedules]))

        return OrSchedule(schedules=frozenlist([*self.schedules, other]))


Schedule = CronSchedule | IntervalSchedule | AndSchedule | OrSchedule

AndSchedule.__pydantic_model__.update_forward_refs()  # type: ignore
OrSchedule.__pydantic_model__.update_forward_refs()  # type: ignore
