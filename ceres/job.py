from asyncio import CancelledError
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING

from ceres.__internal__.manager import BaseComponentManager
from ceres.concurrency import sleep
from ceres.error import trace
from ceres.event import (
    JobAddedEvent,
    JobCancelledEvent,
    JobCompletedEvent,
    JobEndedEvent,
    JobExceptionEvent,
    JobRemovedEvent,
    JobRetryEvent,
    JobRetryPendingEvent,
    JobStartedEvent,
)

if TYPE_CHECKING:
    from apscheduler.job import Job as InternalJob
    from apscheduler.schedulers.base import BaseScheduler

    from ceres.__internal__.protocols import ComponentSource
    from ceres.config import JobConfig
    from ceres.schedule import Trigger

__all__ = [
    "JobManager",
]


@lru_cache(maxsize=1)
def _get_trigger_adapter_class():
    from apscheduler.job import BaseTrigger

    class TriggerAdapter(BaseTrigger):
        __slots__ = ("_inner",)

        def __init__(self, inner: Trigger) -> None:
            super().__init__()
            self._inner = inner

        def get_next_fire_time(  # type: ignore
            self,
            previous_fire_time: datetime | None,
            now: datetime,
        ) -> datetime | None:
            return self._inner.get_next_fire_time(previous_fire_time, now)

    return TriggerAdapter


class JobManager(BaseComponentManager):
    __slots__ = (
        "_scheduler",
        "_jobs",
        "_lock",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self._scheduler = self._create_scheduler()
        self._jobs: dict[str, JobConfig] = {}
        self._lock = Lock()

    @classmethod
    def _create_scheduler(cls) -> BaseScheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        return AsyncIOScheduler(timezone=UTC)

    @property
    def count(self) -> int:
        return len(self._jobs)

    async def __run__(self) -> None:
        try:
            with self._lock:
                self._sync_jobs()
            self._scheduler.start()
            await sleep(...)
        finally:
            if self._scheduler.running:
                self._scheduler.shutdown()

            with self._lock:
                self._scheduler.remove_all_jobs()
                self._scheduler = self._create_scheduler()

    def add(self, job: JobConfig) -> None:
        """
        Register a job to be executed according to its defined schedule.
        """
        binding = self.__system__.get_action_bindings().get(job.action)
        if binding is None:
            registered = list(self.__system__.get_action_bindings().keys())
            raise ValueError(
                f"action {job.action!r} does not exist on {type(self.__system__.component)}, registered actions: {registered!r}"
            )

        with self._lock:
            self._jobs[job.name] = job
            self.__system__.events.emit(JobAddedEvent, job=job.name)
            self._sync_jobs()

    def get(self, name: str) -> JobConfig | None:
        return self._jobs.get(name)

    def get_all(self) -> list[JobConfig]:
        return list(self._jobs.values())

    def remove(self, name: str) -> JobConfig | None:
        from apscheduler.jobstores.base import JobLookupError

        with self._lock:
            try:
                self._scheduler.remove_job(name)
            except JobLookupError:
                pass

            job = self._jobs.pop(name, None)

        if job is not None:
            self.__system__.events.emit(JobRemovedEvent, job=job.name)

        return job

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
            for job in self._scheduler.get_jobs():
                job: InternalJob = job
                self._scheduler.remove_job(job.id)

    def _sync_jobs(self) -> None:
        for name, job in self._jobs.items():
            internal: InternalJob | None = self._scheduler.get_job(name)
            if internal is not None:
                continue

            TriggerAdapter = _get_trigger_adapter_class()
            trigger = job.schedule.create_trigger()
            internal = self._scheduler.add_job(
                self._run_job,
                args=[job],
                trigger=TriggerAdapter(trigger),
                name=name,
                id=name,
            )

    async def _run_job(self, job: JobConfig) -> None:
        self.__system__.events.emit(JobStartedEvent, job=job.name)
        retry = 0

        try:
            while True:
                try:
                    await self.__system__.call(job.action, job.arguments)
                    self.__system__.events.emit(JobCompletedEvent, job=job.name)
                    break
                except CancelledError:
                    self.__system__.events.emit(JobCancelledEvent, job=job.name)
                    raise
                except Exception as exception:
                    self.__system__.events.emit(
                        JobExceptionEvent,
                        job=job.name,
                        exception=trace(exception),
                    )
                    if retry >= job.retries:
                        break

                    self.__system__.events.emit(
                        JobRetryPendingEvent, job=job.name, delay=job.retry_delay
                    )
                    retry += 1
                    await sleep(job.retry_delay)
                    self.__system__.events.emit(JobRetryEvent, job=job.name)
        finally:
            self.__system__.events.emit(JobEndedEvent, job=job.name)
