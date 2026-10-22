"""Replay a component's stored messages through its stored sieves."""

from asyncio import Task, create_task
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from datetime import UTC, datetime
from enum import StrEnum
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
    "PlaybackRecord",
    "PlaybackState",
    "feed",
]

_RUN_RING_SIZE = 20
_PROGRESS_PARTICLES = 1000
_ORDER = ["timestamp:asc", "id:asc"]


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

    after: DateTime
    """Inclusive start of the replayed range."""

    before: DateTime
    """Exclusive end of the replayed range, capped at the time the playback started."""

    level: PlaybackLevel
    """What the playback does with each particle it parses."""

    export: bool
    """Whether the playback rewrites the files of the exporters whose particles it replaced."""

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

    export_runs: list[UUID] = Field(default_factory=list)
    """IDs of the export runs the playback started, one per exporter it rewrote."""

    exception: str | None = None
    """Why the playback failed, `None` unless it failed."""


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
    # Sets the time in the consuming task's context, which a playback owns alone.
    async for message in messages:
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
        export: bool = True,
    ) -> PlaybackRecord:
        """Start replaying the stored messages in `[after, before)` and return its record.

        The playback deletes the component's stored particles of every type its stored sieves
        declare in the range, then runs every stored sieve over its stored messages in the
        range. Particles of those types that something other than a sieve stored are lost.

        Args:
            after: Inclusive start of the range.
            before: Exclusive end of the range, defaulting to now and capped at now.
            level: What to do with each particle parsed.
            export: Whether to rewrite, from the database alone, the files of every particle
                exporter whose type the playback replaced or that exports every type.

        Raises:
            ValueError: If `after` does not precede `before`, a stored sieve declares no
                particle type, or the stored messages do not reach back to `after`.
            AlreadyExistsError: If a playback of the component already runs.
        """
        if self.__busy:
            raise AlreadyExistsError(field="playback", value=str(self.__system__.address))

        self.__busy = True
        try:
            now = datetime.now(UTC)
            after = after.astimezone(UTC)
            before = min((before or now).astimezone(UTC), now)
            if after >= before:
                raise ValueError("`after` must precede `before`")

            sieves = self.__stored_sieves()
            for config, _ in sieves:
                await self.__check_retention(config, after)

            run = PlaybackRecord(
                id=uuid4(),
                after=after,
                before=before,
                level=level,
                export=export,
                started=now,
            )
            self.__runs.append(run)
            self.__task = create_task(self.__play(run, sieves))
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
        export: bool = True,
    ) -> PlaybackRecord:
        """Run like `start` and return the playback's record once it completes or fails."""
        run = await self.start(after, before, level=level, export=export)
        task = self.__task
        if task is not None:
            await task

        return next(current for current in self.__runs if current.id == run.id)

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

    async def __check_retention(self, config: SieveConfig, after: datetime) -> None:
        oldest = await self.__messages(config).first()
        if oldest is None:
            raise ValueError(f"Sieve '{config.name}' has no stored messages to replay")

        if after < oldest.timestamp:
            newest = await self.__messages(config, ["timestamp:desc", "id:desc"]).first()
            raise ValueError(
                f"Sieve '{config.name}' has stored messages only from "
                f"{oldest.timestamp.isoformat()} to {newest.timestamp.isoformat()}"
            )

    def __update(self, run: PlaybackRecord, **changes: Any) -> PlaybackRecord:
        # Starts from the ring's copy, which holds every earlier update.
        for index, current in enumerate(self.__runs):
            if current.id == run.id:
                run = self.__runs[index] = replace(current, **changes)

        return run

    async def __play(
        self, run: PlaybackRecord, sieves: list[tuple[SieveConfig, list[str]]]
    ) -> None:
        system = self.__system__
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
                run = await self.__export(run, types)
        except BaseException as exception:
            # A stopping component cancels the playback, which fails it like an error does.
            set_fake_now(None)
            self.__update(
                run,
                state=PlaybackState.FAILED,
                ended=datetime.now(UTC),
                exception=str(exception) or type(exception).__name__,
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

        async def counted(records: AsyncIterable[Message]) -> AsyncIterator[Message]:
            nonlocal messages
            async for message in records:
                messages += 1
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

                    if particles % _PROGRESS_PARTICLES == 0:
                        run = self.__update(run, messages=messages, particles=particles)
        finally:
            # Events, log lines and tasks after the replay take the real time.
            set_fake_now(None)

        run = self.__update(run, messages=messages, particles=particles)
        system.events.emit(
            PlaybackProgressEvent,
            playback=run.id,
            sieve=config.name,
            messages=messages,
            particles=particles,
        )
        return run

    async def __export(self, run: PlaybackRecord, types: list[str]) -> PlaybackRecord:
        exporters = self.__system__.exporters
        for exporter in exporters.get_all():
            if exporter.exports != EntityType.PARTICLE:
                continue

            particle = exporter.particle_class()
            if particle is not None and _get_cls_particle_type(particle) not in types:
                continue

            try:
                finished = await exporters.run(exporter.name, run.after, run.before, replace=True)
            except AlreadyExistsError as error:
                raise RuntimeError(
                    f"Exporter '{exporter.name}' already has a run waiting, so rebuild its "
                    "files by hand"
                ) from error

            run = self.__update(run, export_runs=[*run.export_runs, finished.id])
            if finished.exception is not None:
                raise RuntimeError(
                    f"Exporter '{exporter.name}' failed to rewrite its files: {finished.exception}"
                )

        return run
