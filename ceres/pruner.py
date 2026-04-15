from asyncio import CancelledError
from datetime import UTC
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

from ceres.__internal__.manager import BaseComponentManager
from ceres.concurrency import sleep
from ceres.entity import EntityType
from ceres.error import trace
from ceres.event import (
    PruneCancelledEvent,
    PruneCompletedEvent,
    PruneEndedEvent,
    PruneExceptionEvent,
    PrunerAddedEvent,
    PrunerRemovedEvent,
    PruneStartedEvent,
)

if TYPE_CHECKING:
    from apscheduler.job import Job as InternalJob
    from apscheduler.schedulers.base import BaseScheduler

    from ceres.__internal__.protocols import ComponentSource
    from ceres.config import PrunerConfig


class PrunerManager(BaseComponentManager):
    __slots__ = (
        "__scheduler",
        "__pruners",
        "__lock",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__scheduler = self.__create_scheduler()
        self.__pruners: dict[str, PrunerConfig] = {}
        self.__lock = Lock()

    @classmethod
    def __create_scheduler(cls) -> BaseScheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        return AsyncIOScheduler(timezone=UTC)

    @property
    def count(self) -> int:
        return len(self.__pruners)

    async def __run__(self) -> None:
        try:
            with self.__lock:
                self.__sync_pruners()
            self.__scheduler.start()
            await sleep(...)
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

    def get(self, name: str) -> PrunerConfig | None:
        return self.__pruners.get(name)

    def get_all(self) -> list[PrunerConfig]:
        return list(self.__pruners.values())

    def remove(self, name: str) -> PrunerConfig | None:
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

            from ceres.job import _get_trigger_adapter_class

            TriggerAdapter = _get_trigger_adapter_class()
            trigger = job.schedule.create_trigger()
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
            deleted = await manager.where(cast("Any", pruner.filter)).delete()

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
                exception=trace(exception),
            )
        finally:
            self.__system__.events.emit(PruneEndedEvent, pruner=pruner.name)
