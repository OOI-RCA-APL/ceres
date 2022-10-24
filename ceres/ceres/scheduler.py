from __future__ import annotations

from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import AndTrigger, OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import (
    AndScheduleConfig,
    CronScheduleConfig,
    IntervalScheduleConfig,
    OrScheduleConfig,
    ScheduleConfig,
)


class Scheduler:
    def __init__(self) -> None:
        self._inner = AsyncIOScheduler()

    def start(self) -> None:
        self._inner.start()

    def stop(self, wait: bool = False) -> None:
        self._inner.shutdown(wait)

    def add_job(
        self,
        function: Callable[[], Any],
        schedule: ScheduleConfig,
        name: str | None = None,
    ) -> None:
        name = name or function.__name__
        self._inner.add_job(
            function,
            trigger=self._create_trigger(schedule),
            name=name,
            id=name,
        )

    def remove_job(self, name: str | Callable[[], None]) -> None:
        if not isinstance(name, str):
            name = name.__name__

        self._inner.remove_job(name)

    def _create_trigger(self, config: ScheduleConfig) -> BaseTrigger:
        match config:
            case CronScheduleConfig():
                return CronTrigger.from_crontab(config.crontab)
            case IntervalScheduleConfig():
                return IntervalTrigger(seconds=config.interval.total_seconds())
            case AndScheduleConfig():
                return AndTrigger([self._create_trigger(schedule) for schedule in config.schedules])
            case OrScheduleConfig():
                return OrTrigger([self._create_trigger(schedule) for schedule in config.schedules])
