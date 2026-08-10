from asyncio import Event as AsyncEvent
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ceres.__internal__.utilities.collections import group_by

if TYPE_CHECKING:
    from ceres.database import Database
    from ceres.entity import Entity


def write_failures() -> tuple[type[BaseException], ...]:
    """What a flush can fail with, and therefore what it puts its entities back for.

    A flush that raises anything here still has entities nobody has written so they go
    back on the queue and go out with the next one. Anything outside this set is not a
    write that failed, and letting it through unhandled is how it stays visible.

    Every wording the store recognizes translates into one of the first four, and a
    wording it does not recognize stays a plain `ValueError`, which is why that type is
    listed too. A write conflict under Turso's MVCC journaling ("Write-write conflict")
    is that case, and it makes a concurrent transaction safe to ask for.

    Imported lazily and built once because `ceres.error` is not a cheap import and a
    flush is a hot path.
    """
    global _WRITE_FAILURES

    if _WRITE_FAILURES is None:
        from ceres.error import (
            AlreadyExistsError,
            DatabaseUnexpectedError,
            DatabaseUnreachableError,
            IntegrityError,
        )

        _WRITE_FAILURES = (
            AlreadyExistsError,
            DatabaseUnexpectedError,
            DatabaseUnreachableError,
            IntegrityError,
            ValueError,
        )

    return _WRITE_FAILURES


_WRITE_FAILURES: tuple[type[BaseException], ...] | None = None
"""Cached by `write_failures`, which fills it."""


@dataclass(slots=True)
class Flush:
    """Represent a single flush operation containing entities to write and a completion signal."""

    entities: list[Entity]
    """The entities to write in this flush."""

    event: AsyncEvent = field(default_factory=AsyncEvent)
    """Event that is set when this flush completes, allowing waiters to proceed."""


class Writer:
    """Buffer entity writes and flush them to the database in ordered batches.

    Maintain an internal buffer of entities. When flushed, move the buffered entities into a
    sequential flush queue so that writes happen in order. On failure, prepend unwritten entities
    back into the next flush or the buffer so no data is lost.
    """

    __slots__ = (
        "_database",
        "_buffer",
        "_flushes",
        "_settled",
    )

    def __init__(self, database: Callable[[], Database], /) -> None:
        """Initialize the writer with a factory that provides a database connection.

        Args:
            database: A callable that returns the `Database` instance to write to.
        """
        self._database = database
        self._buffer: list[Entity] = []
        self._flushes: deque[Flush] = deque()
        self._settled = AsyncEvent()
        self._settled.set()

    @property
    def empty(self) -> bool:
        """Return True if there are no buffered entities and no pending flush operations."""
        return not self._buffer and not any(flush.entities for flush in self._flushes)

    @property
    def size(self) -> int:
        """Return the total number of entities across the buffer and all pending flushes."""
        return len(self._buffer) + sum(len(flush.entities) for flush in self._flushes)

    @property
    def flushing(self) -> bool:
        """Return True if there are any flush operations in progress."""
        return len(self._flushes) > 0

    @property
    def settled(self) -> bool:
        """Return True if the writer has no buffered entities and no pending flushes."""
        return self._settled.is_set()

    def add(self, entity: Entity) -> None:
        """Add an entity to the write buffer.

        Args:
            entity: The entity to buffer for the next flush.
        """
        # Add the record to the flush buffer and clear the flushed event.
        self._buffer.append(entity)
        self._settled.clear()

    async def flush(self) -> None:
        """Flush buffered entities to the database.

        Move the current buffer into a flush queue entry and write the entities within a database
        transaction. Wait for any prior flush to complete before writing. On database error,
        prepend the unwritten entities to the next pending flush or back into the buffer.

        Raises:
            DatabaseError: If the database write fails, after requeuing the entities.
        """
        # Get the previous flush object if there is one.
        previous = self._flushes[-1] if self._flushes else None

        # If there's no records in the buffer, wait for the latest flush to complete.
        if not self._buffer:
            if previous:
                await previous.event.wait()

            # Otherwise return, there's nothing to wait for.
            return

        # Register the flush request.
        flush = Flush(entities=self._buffer)
        # Clear the buffer.
        self._buffer = []
        self._flushes.append(flush)

        try:
            # Wait for the previous flush to complete.
            if previous:
                await previous.event.wait()

            database = self._database()
            if not await self._write_natively(database, flush.entities):
                await self._write_entities(database, flush.entities)
        except write_failures():
            if len(self._flushes) > 1:
                next = self._flushes[1].entities
            else:
                next = self._buffer

            next[0:0] = flush.entities
            raise
        finally:
            # Notify the flush attempt is over.
            flush.event.set()
            # Remove it from the queue.
            self._flushes.popleft()
            # If there are records no records remaining in the buffer and no pending flushes, set
            # the "flushed" event.
            if not self._buffer and not self._flushes:
                self._settled.set()

    async def settle(self) -> None:
        """Wait until all buffered and in-flight entities have been flushed.

        Return immediately if the writer is already settled.
        """
        if self.settled:
            return

        await self._settled.wait()

    async def _write_natively(self, database: Database, entities: list[Entity]) -> bool:
        """Write a whole flush through the native engine, or report that it cannot.

        A flush is atomic so it only goes native when every entity in it is an exact
        record type the native engine holds. Anything else sends the entire flush down
        the query layer path instead. A native execution failure raises because the
        parity suites hold the two engines to identical semantics and a silent fallback
        would hide exactly the drift they exist to catch.
        """
        from ceres.__internal__.core import RecordTable
        from ceres.alert import Alert
        from ceres.logs import LogEntry
        from ceres.message import Message
        from ceres.particle import Particle, ParticleData

        tables: dict[type, RecordTable] = {
            Message: RecordTable.MESSAGES,
            Particle: RecordTable.PARTICLES,
            Alert: RecordTable.ALERTS,
            LogEntry: RecordTable.LOGS,
        }

        groups: defaultdict[RecordTable, list[Entity]] = defaultdict(list)
        for entity in entities:
            table = tables.get(type(entity))
            if table is None:
                return False

            # A typed payload serializes through Pydantic, which only the query layer runs.
            if isinstance(entity, Particle) and isinstance(entity.data, ParticleData):
                return False

            groups[table].append(entity)

        await database._record_writer().write(list(groups.items()))
        return True

    async def _write_entities(self, database: Database, entities: Iterable[Entity]) -> None:
        """Upsert every entity in a flush, grouped so each type writes together.

        This serves the entities the record writer does not hold, a typed particle payload
        or a non-record type reaching the buffer. Each write is an upsert on the row's own
        primary key so a flush that fails part way and comes back rewrites what it already
        wrote rather than colliding with it.

        Args:
            database: The database the entities belong to.
            entities: The entities to write.
        """
        for cls, group in group_by(entities, type):
            manager = cls.Manager(database)
            for entity in group:
                await manager._insert(entity, upsert=True)
