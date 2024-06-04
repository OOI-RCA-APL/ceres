from __future__ import annotations

import asyncio
from asyncio import CancelledError
from datetime import datetime
from functools import lru_cache

from ceres._internal.lazy import lazy_imports
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
from ceres.job import Job

with lazy_imports(__name__):
    from threading import Lock

    from apscheduler.job import Job as InternalJob
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ceres._internal import util
    from ceres.component import ComponentSystem, get_component_method_binding
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


class JobManager:
    def __init__(self, source: ComponentSystem) -> None:
        self._system = source
        self._scheduler = AsyncIOScheduler()
        self._jobs: dict[Name, Job] = {}
        self._lock = Lock()

    @property
    def count(self) -> int:
        return len(self._jobs)

    async def process(self) -> None:
        try:
            with self._lock:
                self.__sync()
            self._scheduler.start()
            await util.sleep_forever()
        finally:
            if self._scheduler.running:
                self._scheduler.shutdown()

    def add(self, job: Job) -> None:
        """
        Register a job to be executed according to its defined schedule.
        """
        from ceres.component import ActionBinding

        binding = (
            self._system.get_action_binding(job.action)
            if isinstance(job.action, str)
            else get_component_method_binding(job.action, ActionBinding)
        )
        if binding is None:
            raise ValueError(
                f"action '{job.action}' does not exist on {util.strify(type(self._system.component))}"
            )

        with self._lock:
            self._jobs[job.name] = job
            self._system.events.emit(JobAddedEvent, job=job.name)
            self.__sync()

    def get(self, name: Name) -> Job | None:
        return self._jobs.get(name)

    def get_all(self) -> list[Job]:
        return list(self._jobs.values())

    def remove(self, name: Name) -> Job | None:
        from apscheduler.jobstores.base import JobLookupError

        with self._lock:
            try:
                self._scheduler.remove_job(name)
            except JobLookupError:
                pass

            job = self._jobs.pop(name, None)

        if job is not None:
            self._system.events.emit(JobRemovedEvent, job=job.name)

        return job

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
            for job in self._scheduler.get_jobs():
                job: InternalJob = job
                self._scheduler.remove_job(job.id)

    def __sync(self) -> None:
        for name, job in self._jobs.items():
            internal: InternalJob | None = self._scheduler.get_job(name)
            if internal is not None:
                continue

            TriggerAdapter = _get_trigger_adapter_class()
            trigger = job.schedule.as_trigger()
            internal = self._scheduler.add_job(
                self.__run,
                args=[job],
                trigger=TriggerAdapter(trigger),
                name=name,
                id=name,
            )

    async def __run(self, job: Job) -> None:
        self._system.events.emit(JobStartedEvent, job=job.name)
        retry = 0

        while True:
            try:
                await self._system.call(job.action, job.arguments)
                self._system.events.emit(JobCompletedEvent, job=job.name)
                break
            except CancelledError:
                self._system.events.emit(JobCancelledEvent, job=job.name)
                break
            except Exception as exception:
                self._system.events.emit(
                    JobExceptionEvent,
                    job=job.name,
                    traceback=util.get_traceback(exception),
                )
                if retry >= job.retries:
                    break

                self._system.events.emit(JobRetryPendingEvent, job=job.name, delay=job.retry_delay)
                retry += 1
                await asyncio.sleep(job.retry_delay.total_seconds())
                self._system.events.emit(JobRetryEvent, job=job.name)

        self._system.events.emit(JobEndedEvent, job=job.name)
