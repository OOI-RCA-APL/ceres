"""Replay a component's stored messages through its stored sieves."""

from asyncio import Task, create_task
from bisect import bisect_right
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import Field

from ceres.__internal__.manager import BaseComponentManager
from ceres.__internal__.particles import _resolve_particle_members, _sieve_config_function
from ceres.concurrency import cancel, sleep
from ceres.data import DataObject, DateTime, replace
from ceres.entity import EntityType
from ceres.error import AlreadyExistsError, trace
from ceres.event import (
    ParticleEvent,
    PlaybackCompletedEvent,
    PlaybackFailedEvent,
    PlaybackProgressEvent,
    PlaybackStartedEvent,
)
from ceres.exporter import ExportConflict, ExportPlan, ExportRangeMode, ExportSpan, span_files
from ceres.level import Level
from ceres.logs import LogEntry, capture_logs
from ceres.particle import Particle, ParticleFilter, _get_cls_particle_type
from ceres.timing import set_fake_now

if TYPE_CHECKING:
    from ceres.__internal__.protocols import ComponentSource
    from ceres.component import Component
    from ceres.config import SieveConfig
    from ceres.message import Message

__all__ = [
    "PlaybackLevel",
    "PlaybackManager",
    "PlaybackPlan",
    "PlaybackRangeError",
    "PlaybackRecord",
    "PlaybackSievePlan",
    "PlaybackState",
    "feed",
]

_RUN_RING_SIZE = 20
_PROGRESS_SECONDS = 1.0
_ORDER = ["timestamp:asc", "id:asc"]

_LOG_LIMIT = 100
"""Log entries a dry run keeps of those its sieves write, beside its count of all of them."""


class PlaybackRangeError(ValueError):
    """A playback refused for its range, as opposed to the component it would replay."""


class PlaybackLevel(StrEnum):
    """What a playback does with each particle it parses."""

    PARTICLES = "particles"
    """Store the particle and emit nothing."""

    FULL = "full"
    """Store the particle and emit its `ParticleEvent`, so every listener runs as if live."""


class PlaybackState(StrEnum):
    """Where a playback stands."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PlaybackRecord(DataObject):
    """One playback over `[after, before)`, kept in its manager's ring of recent playbacks."""

    id: UUID
    """Playback ID, returned when the playback starts."""

    requested_after: DateTime
    """Inclusive start of the range the request named."""

    requested_before: DateTime
    """Exclusive end of the range the request named, capped at the time the playback started."""

    after: DateTime
    """Inclusive start of the replayed range."""

    before: DateTime
    """Exclusive end of the replayed range, capped at the time the playback started."""

    level: PlaybackLevel
    """What the playback does with each particle it parses."""

    export: bool
    """Whether the playback writes the files of the exporters whose particles it replaced."""

    on_export_conflict: ExportConflict
    """What the playback's export runs do with a file that already exists."""

    export_range_mode: ExportRangeMode
    """How the playback aligns its range with its exporters' files."""

    state: PlaybackState = PlaybackState.RUNNING
    """Where the playback stands."""

    started: DateTime
    """When the playback started."""

    ended: DateTime | None = None
    """When the playback completed or failed, `None` while it runs."""

    deleted: int = 0
    """Stored particles the playback deleted before replaying."""

    messages: int = 0
    """Stored messages replayed so far."""

    particles: int = 0
    """Particles stored so far."""

    sieves: int
    """Stored sieves the playback replays, one after another."""

    sieves_done: int = 0
    """Sieves replayed so far."""

    sieve: str | None = None
    """Name of the sieve replaying now, `None` before the first starts."""

    position: DateTime | None = None
    """Timestamp of the last message the current sieve took, `None` before it takes one."""

    progress: float = 0.0
    """Fraction of the replay done, from 0 to 1, counting each sieve equally.

    The exports that follow a replay report their own progress, so a playback reads 1 while
    it still runs them.
    """

    export_runs: list[UUID] = Field(default_factory=list)
    """IDs of the export runs the playback started, one per exporter it rewrote."""

    exception: str | None = None
    """Why the playback failed, `None` unless it failed."""


class PlaybackSievePlan(DataObject):
    """What one sieve parses from the stored messages of a dry run."""

    name: str
    """Name of the sieve."""

    types: list[str]
    """Particle types the sieve declares, whose stored particles the playback replaces."""

    messages: int
    """Stored messages the sieve took."""

    particles: int
    """Particles the sieve parsed from them."""

    exception: str | None = None
    """Why the sieve stopped before the end of its messages, `None` unless it did, in which
    case the counts cover only the messages before."""


class PlaybackPlan(DataObject):
    """What a playback would do, from a dry run that parses stored messages and writes nothing."""

    requested_after: DateTime
    """Inclusive start of the range the request named."""

    requested_before: DateTime
    """Exclusive end of the range the request named, capped at now."""

    after: DateTime
    """Inclusive start of the range the playback would replay."""

    before: DateTime
    """Exclusive end of the range the playback would replay."""

    export: bool
    """Whether the playback would write its exporters' files."""

    on_export_conflict: ExportConflict
    """What the playback's export runs would do with a file that already exists."""

    export_range_mode: ExportRangeMode
    """How the playback aligns its range with its exporters' files."""

    deleted: int
    """Stored particles the playback would delete before replaying."""

    sieves: list[PlaybackSievePlan]
    """Each sieve the playback would replay, in order."""

    exports: list[ExportPlan]
    """Each export run the playback would start. A file's `records` counts the stored
    records the replay keeps and the particles the dry run parsed for it."""

    logs: list[LogEntry]
    """Log entries the sieves wrote, the first `_LOG_LIMIT` of them."""

    log_counts: dict[Level, int]
    """Log entries the sieves wrote by level, all of them counted."""

    logs_truncated: bool
    """Whether the sieves wrote more log entries than `logs` holds."""

    complete: bool
    """Whether every sieve parsed all of its messages, so the counts cover the whole range."""


def _progress(run: PlaybackRecord) -> float:
    sieve = 0.0
    if run.position is not None:
        sieve = (run.position - run.after) / (run.before - run.after)

    return (run.sieves_done + min(max(sieve, 0.0), 1.0)) / run.sieves


async def feed(
    component: Component,
    config: SieveConfig,
    messages: AsyncIterable[Message],
    *,
    replay: bool,
) -> AsyncIterator[Particle]:
    """Run the sieve `config` describes over `messages` and yield what it parses.

    A particle without a connection takes the sieve's sole connection, when it has one.

    Args:
        component: The component the sieve belongs to.
        config: The sieve's configuration.
        messages: The messages to parse.
        replay: Whether the messages are stored ones, in which case `utc()` reads the time of
            the newest message the sieve has taken, so a particle built with the current time
            takes its message's time.

    Yields:
        Each particle the sieve parses.
    """
    from ceres.sieves import _sole_connection

    source = _sole_connection(config)
    sieve = config.create(component)
    async for particle in sieve.process(_clocked(messages) if replay else messages):
        if source is not None and particle.connection is None:
            particle.connection = source

        yield particle


async def _clocked(messages: AsyncIterable[Message]) -> AsyncIterator[Message]:
    # Sets the time in the consuming task's context, which a playback owns alone. Fetching the
    # next message takes the real time, so only the sieve's own code sees a message's time.
    iterator = aiter(messages)
    while True:
        set_fake_now(None)
        message = await anext(iterator, None)
        if message is None:
            return

        set_fake_now(message.timestamp)
        yield message


class PlaybackManager(BaseComponentManager):
    """Component-level manager that runs one playback at a time and keeps the recent ones."""

    __slots__ = ("__busy", "__runs", "__task")

    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__busy = False
        self.__runs: deque[PlaybackRecord] = deque(maxlen=_RUN_RING_SIZE)
        self.__task: Task[None] | None = None

    async def __run__(self) -> None:
        try:
            await sleep(...)
        finally:
            task, self.__task = self.__task, None
            if task is not None:
                await cancel(task)

    def get_runs(self) -> list[PlaybackRecord]:
        """Return the recent playbacks, newest first."""
        return list(reversed(self.__runs))

    async def start(
        self,
        after: datetime,
        before: datetime | None = None,
        *,
        level: PlaybackLevel = PlaybackLevel.PARTICLES,
        export: bool = False,
        on_export_conflict: ExportConflict = ExportConflict.OVERWRITE,
        export_range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
    ) -> PlaybackRecord:
        """Start replaying the stored messages in `[after, before)` and return its record.

        The playback deletes the component's stored particles of every type its stored sieves
        declare in the range, then runs every stored sieve over its stored messages in the
        range. Particles of those types that something other than a sieve stored are lost.

        With `export` the range first widens or narrows to the files of the particle exporters
        the playback affects, as `export_range_mode` says, and once the replay completes each
        of those exporters runs over the range with `on_export_conflict`. An exporter covering
        all time leaves the range alone.

        The range then starts no earlier than the oldest message every replaying sieve has
        stored, so a particle no stored message can rebuild survives. A sieve with no stored
        messages sits the playback out, and a playback left with nothing to replay completes
        at once.

        Args:
            after: Inclusive start of the range.
            before: Exclusive end of the range, defaulting to now and capped at now.
            level: What to do with each particle parsed.
            export: Whether to write, from the database alone, the files of every particle
                exporter whose type the playback replaces or that exports every type.
            on_export_conflict: What the export runs do with a file that already exists.
            export_range_mode: How to align the range with the exporters' files.

        Raises:
            PlaybackRangeError: If `after` does not precede `before`.
            ValueError: If the component has no stored sieve or a stored sieve declares no
                particle type.
            ExportConflictError: If `export` is set, `on_export_conflict` is `error`, and
                files the export runs would write already exist.
            AlreadyExistsError: If a playback of the component already runs.
        """
        if self.__busy:
            raise AlreadyExistsError(field="playback", value=str(self.__system__.address))

        self.__busy = True
        try:
            now = datetime.now(UTC)
            range = await self.__range(after, before, now, export, export_range_mode)
            if export and on_export_conflict == ExportConflict.ERROR:
                for name in range.exporters:
                    self.__system__.exporters.check_conflicts(
                        name, range.after, range.before, export_range_mode
                    )

            run = PlaybackRecord(
                id=uuid4(),
                requested_after=range.requested_after,
                requested_before=range.requested_before,
                after=range.after,
                before=range.before,
                level=level,
                export=export,
                on_export_conflict=on_export_conflict,
                export_range_mode=export_range_mode,
                started=now,
                sieves=len(range.sieves),
            )
            if range.after >= range.before:
                run = replace(run, state=PlaybackState.COMPLETED, ended=now, progress=1.0)
                self.__runs.append(run)
                self.__busy = False
                return run

            self.__runs.append(run)
            self.__task = create_task(self.__play(run, range))
        except BaseException:
            self.__busy = False
            raise

        def finish(_: Task[None]) -> None:
            self.__busy = False
            if self.__task is task:
                self.__task = None

        task = self.__task
        task.add_done_callback(finish)
        return run

    async def run(
        self,
        after: datetime,
        before: datetime | None = None,
        *,
        level: PlaybackLevel = PlaybackLevel.PARTICLES,
        export: bool = False,
        on_export_conflict: ExportConflict = ExportConflict.OVERWRITE,
        export_range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
    ) -> PlaybackRecord:
        """Run like `start` and return the playback's record once it completes or fails."""
        run = await self.start(
            after,
            before,
            level=level,
            export=export,
            on_export_conflict=on_export_conflict,
            export_range_mode=export_range_mode,
        )
        task = self.__task
        if task is not None:
            await task

        return next(current for current in self.__runs if current.id == run.id)

    async def plan(
        self,
        after: datetime,
        before: datetime | None = None,
        *,
        export: bool = False,
        on_export_conflict: ExportConflict = ExportConflict.OVERWRITE,
        export_range_mode: ExportRangeMode = ExportRangeMode.EXPAND,
    ) -> PlaybackPlan:
        """Return what a playback like `start` would do, from a dry run that writes nothing.

        Fresh instances of the stored sieves parse the stored messages in the range, so the
        counts are the particles they parse now. The dry run stores no particle, deletes
        nothing, writes no file and emits no event. The log entries the sieves write go into
        the plan instead of the log. A sieve that keeps state outside itself may parse
        otherwise in a later playback.

        Raises:
            PlaybackRangeError: If `after` does not precede `before`.
            ValueError: If the component has no stored sieve or a stored sieve declares no
                particle type.
            ExportConflictError: If `export` is set, `on_export_conflict` is `error`, and
                files the export runs would write already exist.
        """
        now = datetime.now(UTC)
        range = await self.__range(after, before, now, export, export_range_mode)
        system = self.__system__
        types = sorted({name for _, names in range.sieves for name in names})
        replaying = range.after < range.before
        deleted = 0
        if replaying:
            deleted = await system.particles.where(
                ParticleFilter(type=types, after=range.after, before=range.before),
                address=system.address,
            ).count()

        exporters = system.exporters
        # One count per exporter and file, so the state grows with the files and not with
        # the particles parsed.
        files: dict[str, list[ExportSpan]] = {}
        parsed: dict[str, list[int]] = {}
        if export and replaying:
            for name in range.exporters:
                span = exporters.span(name, range.after, range.before, export_range_mode)
                period = exporters.get(name).period  # type: ignore[union-attr]
                files[name] = [] if span is None else [s for _, s in span_files(period, span)]
                parsed[name] = [0] * len(files[name])

        sieves: list[PlaybackSievePlan] = []
        with capture_logs(_LOG_LIMIT) as logs:
            for config, names in range.sieves:
                sieves.append(await self.__dry_run(config, names, range, files, parsed))

        plans: list[ExportPlan] = []
        if export and replaying:
            replayed = ParticleFilter(type=types, address=system.address)
            for name in range.exporters:

                async def adjust(selected: ExportSpan, count: int, name: str = name) -> int:
                    start = max(selected.after or range.after, range.after)
                    end = min(selected.before or range.before, range.before)
                    if start >= end:
                        return count

                    lost = await exporters.count_records(name, start, end, replayed)
                    index = _file_index(files[name], start)
                    return count - lost + (parsed[name][index] if index is not None else 0)

                plans.append(
                    await exporters.plan(
                        name,
                        range.after,
                        range.before,
                        on_conflict=on_export_conflict,
                        range_mode=export_range_mode,
                        adjust=adjust,
                    )
                )

        return PlaybackPlan(
            requested_after=range.requested_after,
            requested_before=range.requested_before,
            after=range.after,
            before=range.before,
            export=export,
            on_export_conflict=on_export_conflict,
            export_range_mode=export_range_mode,
            deleted=deleted,
            sieves=sieves,
            exports=plans,
            logs=logs.entries,
            log_counts=logs.counts,
            logs_truncated=logs.truncated,
            complete=all(sieve.exception is None for sieve in sieves),
        )

    async def __dry_run(
        self,
        config: SieveConfig,
        types: list[str],
        range: _PlaybackRange,
        files: dict[str, list[ExportSpan]],
        parsed: dict[str, list[int]],
    ) -> PlaybackSievePlan:
        exporters = self.__system__.exporters
        messages = particles = 0
        exception: str | None = None
        if range.after >= range.before:
            return PlaybackSievePlan(name=config.name, types=types, messages=0, particles=0)

        async def counted(records: AsyncIterable[Message]) -> AsyncIterator[Message]:
            nonlocal messages
            async for message in records:
                messages += 1
                yield message

        try:
            async with self.__messages(config, after=range.after, before=range.before) as stored:
                async for particle in feed(
                    self.__component__, config, counted(stored), replay=True
                ):
                    particles += 1
                    for name, spans in files.items():
                        index = _file_index(spans, particle.timestamp)
                        if index is not None and exporters.selects(name, particle):
                            parsed[name][index] += 1
        except Exception as error:
            exception = str(error) or type(error).__name__
        finally:
            set_fake_now(None)

        return PlaybackSievePlan(
            name=config.name,
            types=types,
            messages=messages,
            particles=particles,
            exception=exception,
        )

    def __stored_sieves(self) -> list[tuple[SieveConfig, list[str]]]:
        component = self.__component__
        sieves: list[tuple[SieveConfig, list[str]]] = []
        for config in self.__system__.sieves.all():
            if not config.stored:
                continue

            function = _sieve_config_function(component, config)
            members = _resolve_particle_members(function) if function is not None else ()
            types = sorted(
                {
                    discriminator
                    for member in members
                    if (discriminator := _get_cls_particle_type(member)) is not None
                }
            )
            if not types:
                raise ValueError(
                    f"Sieve '{config.name}' declares no particle type, so a playback cannot "
                    "tell which stored particles it replaces. Annotate the type it yields."
                )

            sieves.append((config, types))

        if not sieves:
            raise ValueError("The component has no sieve that stores particles")

        return sieves

    def __messages(self, config: SieveConfig, order: Sequence[Any] = _ORDER, **bounds: Any) -> Any:
        from ceres.__internal__.models.messages import MessageFilter

        # Range keywords would override the sieve filter's own bounds, so the range is a filter
        # of its own, joined with `&`.
        range: Any = MessageFilter(order=order, **bounds)
        filter: Any = range if config.filter is None else range & config.filter
        return self.__system__.messages.where(filter, address=self.__system__.address)

    async def __range(
        self,
        after: datetime,
        before: datetime | None,
        now: datetime,
        export: bool,
        range_mode: ExportRangeMode,
    ) -> _PlaybackRange:
        # Aligns the range with the exporters' files, then clamps it to the stored messages.
        requested_after = after.astimezone(UTC)
        requested_before = min((before or now).astimezone(UTC), now)
        if requested_after >= requested_before:
            raise PlaybackRangeError("`after` must precede `before`")

        stored = self.__stored_sieves()
        types = {name for _, names in stored for name in names}
        exporters = self.__exporters(types) if export else []
        after, before = requested_after, requested_before
        if range_mode == ExportRangeMode.EXPAND:
            manager = self.__system__.exporters
            for name in exporters:
                span = manager.span(name, requested_after, requested_before, range_mode)
                if span is not None and span.after is not None and span.before is not None:
                    after, before = min(after, span.after), max(before, span.before)

        before = min(before, now)
        sieves: list[tuple[SieveConfig, list[str]]] = []
        for config, names in stored:
            oldest = await self.__messages(config).first()
            if oldest is None:
                continue

            # A sieve with no message inside the range has nothing to rebuild there, so it
            # deletes nothing either.
            start = max(after, oldest.timestamp.astimezone(UTC))
            if await self.__messages(config, after=start, before=before).first() is None:
                continue

            # The latest start among the sieves, so no sieve deletes what it cannot rebuild.
            sieves.append((config, names))
            after = start

        if not sieves or after > before:
            after = before

        return _PlaybackRange(requested_after, requested_before, after, before, sieves, exporters)

    def __exporters(self, types: set[str]) -> list[str]:
        # The particle exporters whose files hold particles of the replayed types.
        names: list[str] = []
        for exporter in self.__system__.exporters.get_all():
            if exporter.exports != EntityType.PARTICLE:
                continue

            particle = exporter.particle_class()
            if particle is not None and _get_cls_particle_type(particle) not in types:
                continue

            names.append(exporter.name)

        return names

    def __update(self, run: PlaybackRecord, **changes: Any) -> PlaybackRecord:
        # Starts from the ring's copy, which holds every earlier update.
        for index, current in enumerate(self.__runs):
            if current.id == run.id:
                updated = replace(current, **changes)
                run = self.__runs[index] = replace(updated, progress=_progress(updated))

        return run

    async def __play(self, run: PlaybackRecord, range: _PlaybackRange) -> None:
        system = self.__system__
        sieves = range.sieves
        events = system.events
        events.emit(
            PlaybackStartedEvent,
            playback=run.id,
            after=run.after,
            before=run.before,
            playback_level=run.level,
            export=run.export,
        )
        types = sorted({name for _, names in sieves for name in names})
        try:
            # Every live write for the range commits before the delete, so none outlives it.
            await system.flush()
            deleted = await system.particles.where(
                ParticleFilter(type=types, after=run.after, before=run.before),
                address=system.address,
            ).delete()
            run = self.__update(run, deleted=deleted)
            for config, _ in sieves:
                run = await self.__replay(run, config)

            await system.flush()
            if run.export:
                run = await self.__export(run, range.exporters)
        except BaseException as exception:
            # A stopping component cancels the playback, which fails it like an error does.
            set_fake_now(None)
            cause = exception
            # A flush raises through a task group, whose own message names no cause.
            while isinstance(cause, BaseExceptionGroup) and len(cause.exceptions) == 1:
                cause = cause.exceptions[0]

            self.__update(
                run,
                state=PlaybackState.FAILED,
                ended=datetime.now(UTC),
                exception=str(cause) or type(cause).__name__,
            )
            events.emit(PlaybackFailedEvent, playback=run.id, exception=trace(exception))
            if not isinstance(exception, Exception):
                raise

            return

        run = self.__update(run, state=PlaybackState.COMPLETED, ended=datetime.now(UTC))
        events.emit(
            PlaybackCompletedEvent,
            playback=run.id,
            deleted=run.deleted,
            messages=run.messages,
            particles=run.particles,
            export_runs=run.export_runs,
        )
        system.log.info(
            f"Playback from {run.after.isoformat()} to {run.before.isoformat()} replayed "
            f"{run.messages} messages into {run.particles} particles, replacing {run.deleted}"
        )

    async def __replay(self, run: PlaybackRecord, config: SieveConfig) -> PlaybackRecord:
        system = self.__system__
        full = run.level == PlaybackLevel.FULL
        messages, particles = run.messages, run.particles
        position: datetime | None = None
        run = self.__update(run, sieve=config.name, position=None)
        reported = monotonic()

        def report() -> None:
            nonlocal run
            run = self.__update(run, messages=messages, particles=particles, position=position)
            system.events.emit(
                PlaybackProgressEvent,
                playback=run.id,
                sieve=config.name,
                messages=messages,
                particles=particles,
                sieves=run.sieves,
                sieves_done=run.sieves_done,
                position=position,
                progress=run.progress,
            )

        async def counted(records: AsyncIterable[Message]) -> AsyncIterator[Message]:
            nonlocal messages, position, reported
            async for message in records:
                messages += 1
                position = message.timestamp
                # A time throttle, since a sieve may parse a million messages into nothing.
                if (now := monotonic()) - reported >= _PROGRESS_SECONDS:
                    reported = now
                    report()

                yield message

        try:
            async with self.__messages(config, after=run.after, before=run.before) as stored:
                async for particle in feed(
                    self.__component__, config, counted(stored), replay=True
                ):
                    system.store(particle)
                    particles += 1
                    if full:
                        system.events.emit(ParticleEvent, particle=particle)
        finally:
            # Events, log lines and tasks after the replay take the real time.
            set_fake_now(None)
            # A failed replay keeps its counts, which say how far it got.
            run = self.__update(run, messages=messages, particles=particles, position=position)

        position = None
        run = self.__update(run, sieves_done=run.sieves_done + 1)
        report()
        return run

    async def __export(self, run: PlaybackRecord, names: list[str]) -> PlaybackRecord:
        exporters = self.__system__.exporters
        for name in names:
            try:
                finished = await exporters.run(
                    name,
                    run.after,
                    run.before,
                    on_conflict=run.on_export_conflict,
                    range_mode=run.export_range_mode,
                )
            except AlreadyExistsError as error:
                raise RuntimeError(
                    f"Exporter '{name}' already has a run waiting, so write its files with "
                    "`ceres export` once it finishes"
                ) from error

            run = self.__update(run, export_runs=[*run.export_runs, finished.id])
            if finished.exception is not None:
                raise RuntimeError(
                    f"Exporter '{name}' failed to write its files: {finished.exception}"
                )

        return run


@dataclass(frozen=True, slots=True)
class _PlaybackRange:
    """A playback's requested range, the range it replays, and what replays it."""

    requested_after: datetime
    requested_before: datetime
    after: datetime
    before: datetime
    sieves: list[tuple[SieveConfig, list[str]]]
    exporters: list[str]


def _file_index(spans: list[ExportSpan], moment: datetime) -> int | None:
    # Spans are sorted and disjoint, so a bisection finds the one holding `moment`.
    index = (
        bisect_right(spans, moment, key=lambda span: span.after or datetime.min.replace(tzinfo=UTC))
        - 1
    )
    if index < 0:
        return None

    span = spans[index]
    return index if span.before is None or moment < span.before else None
