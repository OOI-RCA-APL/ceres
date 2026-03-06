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
    entities: list[Entity]
    event: AsyncEvent = field(default_factory=AsyncEvent)


class Writer:
    __slots__ = (
        "_database",
        "_buffer",
        "_flushes",
        "_settled",
    )

    def __init__(self, database: Callable[[], Database], /) -> None:
        self._database = database
        self._buffer: list[Entity] = []
        self._flushes: deque[Flush] = deque()
        self._settled = AsyncEvent()
        self._settled.set()

    @property
    def empty(self) -> bool:
        return not self._buffer and not any(flush.entities for flush in self._flushes)

    @property
    def size(self) -> int:
        return len(self._buffer) + sum(len(flush.entities) for flush in self._flushes)

    @property
    def flushing(self) -> bool:
        return len(self._flushes) > 0

    @property
    def settled(self) -> bool:
        return self._settled.is_set()

    def add(self, entity: Entity) -> None:
        # Add the record to the flush buffer and clear the flushed event.
        self._buffer.append(entity)
        self._settled.clear()

    async def flush(self) -> None:
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
        if self.settled:
            return

        await self._settled.wait()

    async def _write_entities(
        self,
        database: Database,
        connection: AsyncConnection,
        entities: Iterable[Entity],
    ) -> None:
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
        if not entities:
            return

        from ceres.database import DatabaseType

        match database.type:
            case DatabaseType.SQLITE:
                from sqlalchemy.dialects.sqlite import insert

            case DatabaseType.POSTGRES:
                from sqlalchemy.dialects.postgresql import insert

        values: list[dict[str, Any]] = adapt(list[cls]).dump_python(entities)

        statement = insert(cls.Row)
        pk = cls.Row.get_primary_key_columns()
        upsert = {name: column for name, column in statement.excluded.items() if name not in pk}

        await connection.execute(
            statement.on_conflict_do_update(index_elements=pk.values(), set_=upsert),
            values,
        )
