from __future__ import annotations

from asyncio import CancelledError
from datetime import timezone
from threading import Lock
from typing import TYPE_CHECKING

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseComponentManager
from ceres._internal.protocols import ComponentSource
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

    from ceres.job import _get_trigger_adapter_class

if TYPE_CHECKING:
    from ceres.config import PrunerConfig


class ComponentPrunerManager(BaseComponentManager):
    __slots__ = (
        "__scheduler",
        "__pruners",
        "__lock",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__scheduler = self.__create_scheduler()
        self.__pruners: dict[Name, PrunerConfig] = {}
        self.__lock = Lock()

    @classmethod
    def __create_scheduler(cls) -> AsyncIOScheduler:
        return AsyncIOScheduler(timezone=timezone.utc)

    @property
    def count(self) -> int:
        return len(self.__pruners)

    async def __run__(self) -> None:
        try:
            with self.__lock:
                self.__sync_pruners()
            self.__scheduler.start()
            await util.sleep_forever()
        finally:
            if self.__scheduler.running:
                self.__scheduler.shutdown()

            with self.__lock:
                self.__scheduler.remove_all_jobs()
                self.__scheduler = self.__create_scheduler()

    def add(self, pruner: PrunerConfig) -> None:
        """
        Register a pruner to be executed according to its defined schedule.
        """
        with self.__lock:
            self.__pruners[pruner.name] = pruner
            self.__system__.events.emit(PrunerAddedEvent, pruner=pruner.name)
            self.__sync_pruners()

    def get(self, name: Name) -> PrunerConfig | None:
        return self.__pruners.get(name)

    def get_all(self) -> list[PrunerConfig]:
        return list(self.__pruners.values())

    def remove(self, name: Name) -> PrunerConfig | None:
        from apscheduler.jobstores.base import JobLookupError

        with self.__lock:
            try:
                self.__scheduler.remove_job(name)
            except JobLookupError:
                pass

            pruner = self.__pruners.pop(name, None)

        if pruner is not None:
            self.__system__.events.emit(PrunerRemovedEvent, pruner=pruner.name)

        return pruner

    def clear(self) -> None:
        with self.__lock:
            self.__pruners.clear()
            for job in self.__scheduler.get_jobs():
                job: InternalJob = job
                self.__scheduler.remove_job(job.id)

    def __sync_pruners(self) -> None:
        for name, job in self.__pruners.items():
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

    async def __run(self, pruner: PrunerConfig) -> None:
        self.__system__.events.emit(PruneStartedEvent, pruner=pruner.name)

        match pruner.prunes:
            case EntityType.MESSAGE:
                manager = self.__system__.messages
            case EntityType.PARTICLE:
                manager = self.__system__.particles
            case EntityType.ALERT:
                manager = self.__system__.alerts
            case EntityType.LOG_ENTRY:
                manager = self.__system__.log

        try:
            deleted = await manager.delete(
                filter=pruner.filter,  # type: ignore
            )

            self.__system__.events.emit(
                PruneCompletedEvent,
                pruner=pruner.name,
                deleted=deleted,
            )
        except CancelledError:
            self.__system__.events.emit(PruneCancelledEvent, pruner=pruner.name)
            raise
        except Exception as exception:
            self.__system__.events.emit(
                PruneExceptionEvent,
                pruner=pruner.name,
                traceback=util.get_traceback(exception),
            )
        finally:
            self.__system__.events.emit(PruneEndedEvent, pruner=pruner.name)
