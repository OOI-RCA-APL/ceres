import warnings
from datetime import timezone
from typing import Any, Callable, final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import AndTrigger, OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..schedule import AndSchedule, CronSchedule, IntervalSchedule, OrSchedule, Schedule

warnings.filterwarnings(
    action="ignore",
    module="apscheduler",
    message=r".*localize method is no longer necessary.*",
)


@final
class Scheduler:
    def __init__(self) -> None:
        self.__inner = AsyncIOScheduler(timezone=timezone.utc)

    def start(self) -> None:
        if not self.__inner.running:
            self.__inner.start()

    def stop(self, wait: bool = False) -> None:
        if self.__inner.running:
            self.__inner.shutdown(wait)

    def add_job(
        self,
        function: Callable[[], Any],
        schedule: Schedule,
        name: str | None = None,
    ) -> None:
        name = name or function.__name__
        self.__inner.add_job(
            function,
            trigger=self.__create_trigger(schedule),
            name=name,
            id=name,
        )

    def remove_job(self, name: str | Callable[[], Any]) -> None:
        if not isinstance(name, str):
            name = name.__name__

        self.__inner.remove_job(name)

    def __create_trigger(self, schedule: Schedule) -> BaseTrigger:
        match schedule:
            case CronSchedule():
                return CronTrigger.from_crontab(schedule.crontab)
            case IntervalSchedule():
                return IntervalTrigger(seconds=int(schedule.interval.total_seconds()))
            case AndSchedule():
                return AndTrigger(
                    [self.__create_trigger(schedule) for schedule in schedule.schedules]
                )
            case OrSchedule():
                return OrTrigger(
                    [self.__create_trigger(schedule) for schedule in schedule.schedules]
                )
