from __future__ import annotations

import asyncio
from asyncio import CancelledError
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseComponentManager
from ceres._internal.protocols import ComponentSource
from ceres.data import Name
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

with lazy_imports(__name__):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


if TYPE_CHECKING:
    from apscheduler.job import Job as InternalJob

    from ceres.config import JobConfig
    from ceres.schedule import Trigger


@lru_cache(maxsize=1)
def _get_trigger_adapter_class():
    from apscheduler.job import BaseTrigger

    class TriggerAdapter(BaseTrigger):
        def __init__(self, inner: Trigger) -> None:
            super().__init__()
            self.__inner = inner

        def get_next_fire_time(  # type: ignore
            self,
            previous_fire_time: datetime | None,
            now: datetime,
        ) -> datetime | None:
            return self.__inner.get_next_fire_time(previous_fire_time, now)

    return TriggerAdapter


class ComponentJobManager(BaseComponentManager):
    __slots__ = (
        "__scheduler",
        "__jobs",
        "__lock",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__scheduler = self.__create_scheduler()
        self.__jobs: dict[Name, JobConfig] = {}
        self.__lock = Lock()

    @classmethod
    def __create_scheduler(cls) -> AsyncIOScheduler:
        return AsyncIOScheduler(timezone=timezone.utc)

    @property
    def count(self) -> int:
        return len(self.__jobs)

    async def __run__(self) -> None:
        try:
            with self.__lock:
                self.__sync_jobs()
            self.__scheduler.start()
            await util.sleep_forever()
        finally:
            if self.__scheduler.running:
                self.__scheduler.shutdown()

            with self.__lock:
                self.__scheduler.remove_all_jobs()
                self.__scheduler = self.__create_scheduler()

    def add(self, job: JobConfig) -> None:
        """
        Register a job to be executed according to its defined schedule.
        """
        binding = self.__system__.get_action_binding(job.action)
        if binding is None:
            registered = list(self.__system__.get_action_bindings().keys())
            raise AssertionError(
                f"action {job.action!r} does not exist on {util.strify(type(self.__system__.component))}, registered actions: {registered!r}"
            )

        with self.__lock:
            self.__jobs[job.name] = job
            self.__system__.events.emit(JobAddedEvent, job=job.name)
            self.__sync_jobs()

    def get(self, name: Name) -> JobConfig | None:
        return self.__jobs.get(name)

    def get_all(self) -> list[JobConfig]:
        return list(self.__jobs.values())

    def remove(self, name: Name) -> JobConfig | None:
        from apscheduler.jobstores.base import JobLookupError

        with self.__lock:
            try:
                self.__scheduler.remove_job(name)
            except JobLookupError:
                pass

            job = self.__jobs.pop(name, None)

        if job is not None:
            self.__system__.events.emit(JobRemovedEvent, job=job.name)

        return job

    def clear(self) -> None:
        with self.__lock:
            self.__jobs.clear()
            for job in self.__scheduler.get_jobs():
                job: InternalJob = job
                self.__scheduler.remove_job(job.id)

    def __sync_jobs(self) -> None:
        for name, job in self.__jobs.items():
            internal: InternalJob | None = self.__scheduler.get_job(name)
            if internal is not None:
                continue

            TriggerAdapter = _get_trigger_adapter_class()
            trigger = job.schedule.as_trigger()
            internal = self.__scheduler.add_job(
                self.__run,
                args=[job],
                trigger=TriggerAdapter(trigger),
                name=name,
                id=name,
            )

    async def __run(self, job: JobConfig) -> None:
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
                        traceback=util.get_traceback(exception),
                    )
                    if retry >= job.retries:
                        break

                    self.__system__.events.emit(
                        JobRetryPendingEvent, job=job.name, delay=job.retry_delay
                    )
                    retry += 1
                    await asyncio.sleep(job.retry_delay.total_seconds())
                    self.__system__.events.emit(JobRetryEvent, job=job.name)
        finally:
            self.__system__.events.emit(JobEndedEvent, job=job.name)
