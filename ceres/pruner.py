from asyncio import CancelledError
from datetime import UTC, datetime
from threading import Lock
from typing import TYPE_CHECKING, Any

from ceres.__internal__.manager import BaseComponentManager
from ceres.concurrency import sleep
from ceres.config import PrunerConfig  # noqa: TC001 (APScheduler reads `__run` annotations)
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

_PRUNE_PAGE = 1000
"""Records a pruner bounded by an exporter deletes per hold of the writer.

Flushes wait out each page, so the page bounds their stall. On PostgreSQL a page of 1000 holds
a flush under 30 ms.
"""

_KEY_ORDER = ["timestamp:asc", "id:asc"]
"""Order of a pruner's pages, oldest first.

Each page then deletes one contiguous range of the timestamp index, so no page scans for rows.
"""


class PrunerManager(BaseComponentManager):
    """Component-level manager that schedules and runs registered `PrunerConfig` jobs.

    Each pruner deletes entries of a configured entity type that match its filter, on a cron
    schedule. Lifecycle events (`PrunerAddedEvent`, `PruneStartedEvent`, `PruneCompletedEvent`,
    `PruneCancelledEvent`, `PruneExceptionEvent`, `PruneEndedEvent`, `PrunerRemovedEvent`) are
    emitted on the system event stream so listeners can track progress.
    """

    __slots__ = (
        "__scheduler",
        "__pruners",
        "__lock",
        "__held",
    )

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__scheduler = self.__create_scheduler()
        self.__pruners: dict[str, PrunerConfig] = {}
        self.__lock = Lock()
        # Each pruner's last export bound and whether it warned about it, by pruner name.
        self.__held: dict[str, tuple[datetime, bool]] = {}

    @classmethod
    def __create_scheduler(cls) -> BaseScheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        return AsyncIOScheduler(timezone=UTC)

    @property
    def count(self) -> int:
        """Number of registered pruners."""
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
        """Register a pruner to be executed according to its defined schedule.

        Registration is idempotent by `pruner.name`, re-adding a pruner under the same name
        replaces the stored configuration and emits a fresh `PrunerAddedEvent`.

        Args:
            pruner: Configuration describing what to prune and when.
        """
        with self.__lock:
            self.__pruners[pruner.name] = pruner
            self.__system__.events.emit(PrunerAddedEvent, pruner=pruner.name)
            self.__sync_pruners()

    def get(self, name: str) -> PrunerConfig | None:
        """Return the registered pruner with the given name, or `None` if not registered.

        Args:
            name: Name of the pruner to look up.

        Returns:
            The matching `PrunerConfig`, or `None` if no pruner is registered under `name`.
        """
        return self.__pruners.get(name)

    def get_all(self) -> list[PrunerConfig]:
        """Return a list of all currently registered pruners."""
        return list(self.__pruners.values())

    def remove(self, name: str) -> PrunerConfig | None:
        """Unregister a pruner and cancel its scheduled job.

        Args:
            name: Name of the pruner to remove.

        Returns:
            The removed `PrunerConfig`, or `None` if no pruner was registered under `name`.
        """
        from apscheduler.jobstores.base import JobLookupError

        with self.__lock:
            try:
                self.__scheduler.remove_job(name)
            except JobLookupError:
                pass

            pruner = self.__pruners.pop(name, None)
            self.__held.pop(name, None)

        if pruner is not None:
            self.__system__.events.emit(PrunerRemovedEvent, pruner=pruner.name)

        return pruner

    def clear(self) -> None:
        """Unregister every pruner and cancel all scheduled jobs."""
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

    def __held_by_exports(self, pruner: PrunerConfig) -> tuple[str, datetime] | None:
        # Returns the exporter bounding the pruner and the time before which it may delete.
        if not pruner.wait_for_exports:
            return None

        return self.__system__.exporters.get_written_through(pruner.prunes)

    def __note_held(self, pruner: PrunerConfig, held: tuple[str, datetime] | None) -> None:
        if held is None:
            self.__held.pop(pruner.name, None)
            return

        exporter, through = held
        previous = self.__held.get(pruner.name)
        if previous is None or previous[0] != through:
            self.__held[pruner.name] = (through, False)
        elif not previous[1]:
            # The bound stayed put across a whole schedule interval, so name what holds it.
            self.__held[pruner.name] = (through, True)
            self.__system__.log.warning(
                f"Pruner '{pruner.name}' keeps every record from {through.isoformat()} on "
                f"until exporter '{exporter}' writes it"
            )

    async def __delete(self, pruner: PrunerConfig, manager: Any) -> int:
        filter: Any = pruner.filter
        if self.__held_by_exports(pruner) is None:
            self.__note_held(pruner, None)
            return await manager.where(filter).delete()

        # A flush landing between the bound read and the delete's end could slip a late record
        # under the bound, so flushes wait out each page, and each page reads the bound again.
        deleted = 0
        noted = False
        while True:
            async with self.__system__.__hold_flushes__():
                held = self.__held_by_exports(pruner)
                if not noted:
                    self.__note_held(pruner, held)
                    noted = True

                if held is None:
                    break

                if held[1] == datetime.min.replace(tzinfo=UTC):
                    return deleted

                bounded = filter & type(filter)(before=held[1], order=_KEY_ORDER)
                page = await manager.where(bounded).limit(_PRUNE_PAGE).delete()
                deleted += page

            if page < _PRUNE_PAGE:
                return deleted

        # Every exporter went away during the prune, so nothing bounds the rest.
        return deleted + await manager.where(filter).delete()

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
            deleted = await self.__delete(pruner, manager)

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
