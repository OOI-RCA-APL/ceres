from datetime import timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import validator

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


@vdc(frozen=True)
class BaseSchedule:
    kind: ScheduleKind


@vdc(frozen=True)
class CronSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.CRON] = ScheduleKind.CRON
    crontab: str

    @validator("crontab")
    def _validate_crontab(cls, crontab: str) -> str:
        return validate_crontab(crontab)


@vdc(frozen=True)
class IntervalSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL
    interval: timedelta

    @validator("interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


@vdc(frozen=True)
class AndSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.AND] = ScheduleKind.AND
    schedules: frozenlist["Schedule"]


@vdc(frozen=True)
class OrSchedule(BaseSchedule):
    kind: Literal[ScheduleKind.OR] = ScheduleKind.OR
    schedules: frozenlist["Schedule"]


Schedule = CronSchedule | IntervalSchedule | AndSchedule | OrSchedule

AndSchedule.__pydantic_model__.update_forward_refs()  # type: ignore
OrSchedule.__pydantic_model__.update_forward_refs()  # type: ignore
