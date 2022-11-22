from typing import Any, Callable, final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import AndTrigger, OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .schedule import AndSchedule, CronSchedule, IntervalSchedule, OrSchedule, Schedule


@final
class Scheduler:
    def __init__(self) -> None:
        self._inner = AsyncIOScheduler()

    def start(self) -> None:
        if not self._inner.running:
            self._inner.start()

    def stop(self, wait: bool = False) -> None:
        if self._inner.running:
            self._inner.shutdown(wait)

    def add_job(
        self,
        function: Callable[[], Any],
        schedule: Schedule,
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

    def _create_trigger(self, schedule: Schedule) -> BaseTrigger:
        match schedule:
            case CronSchedule():
                return CronTrigger.from_crontab(schedule.crontab)
            case IntervalSchedule():
                return IntervalTrigger(seconds=int(schedule.interval.total_seconds()))
            case AndSchedule():
                return AndTrigger(
                    [self._create_trigger(schedule) for schedule in schedule.schedules]
                )
            case OrSchedule():
                return OrTrigger(
                    [self._create_trigger(schedule) for schedule in schedule.schedules]
                )
