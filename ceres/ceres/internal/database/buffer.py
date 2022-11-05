import traceback
from logging import Logger
from typing import Generic, TypeVar

from .entity import Entity
from .manager import DatabaseManager

EntityT = TypeVar("EntityT", bound=Entity)


class EntityBuffer(Generic[EntityT]):
    def __init__(
        self,
        max_size: int,
        database: DatabaseManager,
        logger: Logger | None = None,  # TODO: Remove this.
    ) -> None:
        self._max_size = max_size
        self._database = database
        self._entities: list[EntityT] = []
        self._flushing = False
        self._logger = logger

    @property
    def size(self) -> int:
        return len(self._entities)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def flushing(self) -> bool:
        return self._flushing

    async def add(self, entity: EntityT) -> None:
        self._entities.append(entity)
        if len(self._entities) >= self._max_size:
            await self.flush()

    async def flush(self) -> None:
        if self._flushing or not self._entities:
            return
        if not self._entities:
            return

        self._flushing = True

        entities = self._entities
        self._entities = []

        try:
            async with self._database.session() as session:
                session.add_all(entities)
                await session.commit()
        except Exception:
            # TODO: Handle foreign key conflicts so this doesn't cause an infinite loop.
            self._entities = [*entities, *self._entities]
            if self._logger:
                self._logger.error(f"An exception occurred when flushing: {traceback.format_exc()}")
        finally:
            self._flushing = False
