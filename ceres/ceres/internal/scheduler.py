import warnings
from datetime import datetime, timezone
from typing import Any, Callable, final

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger

from ..schedule import Schedule, Trigger

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
        return _TriggerAdapter(schedule.as_trigger())


class _TriggerAdapter(BaseTrigger):
    def __init__(self, inner: Trigger) -> None:
        super().__init__()
        self.__inner = inner

    def get_next_fire_time(  # type: ignore
        self,
        previous_fire_time: datetime | None,
        now: datetime,
    ) -> datetime | None:
        return self.__inner.next(previous_fire_time, now)
