from asyncio import Event as AsyncEvent
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ceres.__internal__.utilities.collections import group_by
from ceres.data import adapt

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from ceres.database import Database
    from ceres.entity import Entity


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
        """Initialize the writer with a factory that provide a database connection.

        Args:
            database: A callable that return the ``Database`` instance to write to.
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

        from sqlalchemy.exc import DatabaseError

        try:
            # Wait for the previous flush to complete.
            if previous:
                await previous.event.wait()

            database = self._database()
            # Records arrive from many components at once and each flush writes rows nothing else
            # is touching, which is exactly the shape a concurrent transaction suits. Backends
            # without one ignore this.
            with database.concurrent_transactions():
                async with await database.use() as connection:
                    await self._write_entities(database, connection, flush.entities)
                    await connection.commit()
        except DatabaseError:
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

    async def _write_entities(
        self,
        database: Database,
        connection: AsyncConnection,
        entities: Iterable[Entity],
    ) -> None:
        """Group entities by type and write each group to the database.

        Args:
            database: The database instance providing dialect information.
            connection: The active async connection to write through.
            entities: The entities to write.
        """
        by_type: defaultdict[type[Entity], list[Entity]] = defaultdict(list)
        for cls, group in group_by(entities, type):
            by_type[cls] = list(group)

        for cls, entities in by_type.items():
            await self._write_entities_of_cls(database, connection, cls, entities)

    async def _write_entities_of_cls(
        self,
        database: Database,
        connection: AsyncConnection,
        cls: type[Entity],
        entities: list[Entity],
    ) -> None:
        """Write a list of entities of the same type using an upsert statement.

        Build an INSERT ... ON CONFLICT DO UPDATE statement appropriate for the database dialect
        (SQLite or Postgres), then execute it with the serialized entity values.

        Args:
            database: The database instance providing dialect information.
            connection: The active async connection to write through.
            cls: The entity class for all entities in the list.
            entities: The entities to upsert. Do nothing if empty.
        """
        if not entities:
            return

        from ceres.database import DatabaseType

        match database.type:
            case DatabaseType.SQLITE | DatabaseType.TURSO:
                from sqlalchemy.dialects.sqlite import insert

            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        values: list[dict[str, Any]] = adapt(list[cls]).dump_python(
            entities, include={"__all__": set(cls.__entity_columns__)}
        )

        statement = insert(cls.Row)
        pk = cls.Row.__table__.primary_key.columns
        upsert = {name: column for name, column in statement.excluded.items() if name not in pk}

        await connection.execute(
            statement.on_conflict_do_update(index_elements=pk.values(), set_=upsert),
            values,
        )
