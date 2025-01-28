from __future__ import annotations

from asyncio import CancelledError
from threading import Lock

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres.config import PrunerConfig
from ceres.data import Name
from ceres.entity import EntityType
from ceres.event import (
    PruneCancelledEvent,
    PruneCompletedEvent,
    PruneEndedEvent,
    PruneExceptionEvent,
    PrunerAddedEvent,
    PrunerRemovedEvent,
    PruneStartedEvent,
)

with lazy_imports(__name__):
    from apscheduler.job import Job as InternalJob
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ceres.component import ComponentSystem
    from ceres.manager.job import _get_trigger_adapter_class


class PrunerManager:
    __slots__ = (
        "_system",
        "_scheduler",
        "_pruners",
        "_lock",
    )

    def __init__(self, source: ComponentSystem, /) -> None:
        self._system = source
        self._scheduler = AsyncIOScheduler()
        self._pruners: dict[Name, PrunerConfig] = {}
        self._lock = Lock()

    @property
    def count(self) -> int:
        return len(self._pruners)

    async def __run__(self) -> None:
        try:
            with self._lock:
                self.__sync_pruners()
            self._scheduler.start()
            await util.sleep_forever()
        finally:
            if self._scheduler.running:
                self._scheduler.shutdown()

    def add(self, pruner: PrunerConfig) -> None:
        """
        Register a pruner to be executed according to its defined schedule.
        """
        with self._lock:
            self._pruners[pruner.name] = pruner
            self._system.events.emit(PrunerAddedEvent, pruner=pruner.name)
            self.__sync_pruners()

    def get(self, name: Name) -> PrunerConfig | None:
        return self._pruners.get(name)

    def get_all(self) -> list[PrunerConfig]:
        return list(self._pruners.values())

    def remove(self, name: Name) -> PrunerConfig | None:
        from apscheduler.jobstores.base import JobLookupError

        with self._lock:
            try:
                self._scheduler.remove_job(name)
            except JobLookupError:
                pass

            pruner = self._pruners.pop(name, None)

        if pruner is not None:
            self._system.events.emit(PrunerRemovedEvent, pruner=pruner.name)

        return pruner

    def clear(self) -> None:
        with self._lock:
            self._pruners.clear()
            for job in self._scheduler.get_jobs():
                job: InternalJob = job
                self._scheduler.remove_job(job.id)

    def __sync_pruners(self) -> None:
        for name, job in self._pruners.items():
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

    async def __run(self, pruner: PrunerConfig) -> None:
        self._system.events.emit(PruneStartedEvent, pruner=pruner.name)

        match pruner.prunes:
            case EntityType.MESSAGE:
                manager = self._system.messages
            case EntityType.PARTICLE:
                manager = self._system.particles
            case EntityType.ALERT:
                manager = self._system.alerts
            case EntityType.LOG_ENTRY:
                manager = self._system.log

        try:
            deleted = await manager.delete_all(
                filter=pruner.filter,  # type: ignore
            )

            self._system.events.emit(
                PruneCompletedEvent,
                pruner=pruner.name,
                deleted=deleted,
            )
        except CancelledError:
            self._system.events.emit(PruneCancelledEvent, pruner=pruner.name)
            raise
        except Exception as exception:
            self._system.events.emit(
                PruneExceptionEvent,
                pruner=pruner.name,
                traceback=util.get_traceback(exception),
            )
        finally:
            self._system.events.emit(PruneEndedEvent, pruner=pruner.name)
