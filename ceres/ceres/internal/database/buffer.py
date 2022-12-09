import traceback
from logging import Logger
from typing import Generic, TypeVar, final

from ...config import DatabaseKind
from . import Database
from .entity import Entity

_EntityT = TypeVar("_EntityT", bound=Entity)


@final
class EntityWriteBuffer(Generic[_EntityT]):
    def __init__(
        self,
        cls: type[_EntityT],
        max_size: int,
        database: Database,
        logger: Logger | None = None,  # TODO: Remove this.
    ) -> None:
        self._cls = cls
        self._max_size = max_size
        self._database = database
        self._entities: list[_EntityT] = []
        self._flushing = False
        self._logger = logger

    @property
    def cls(self) -> type[_EntityT]:
        return self._cls

    @property
    def size(self) -> int:
        return len(self._entities)

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def flushing(self) -> bool:
        return self._flushing

    async def add(self, entity: _EntityT) -> None:
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
                match self._database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert
                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert

                await session.execute(
                    insert(self._cls)
                    .values([entity.values() for entity in entities])
                    .on_conflict_do_nothing()  # TODO: Warn when there is a conflict.
                )
                await session.commit()
        except Exception:
            self._entities = [*entities, *self._entities]
            if self._logger:
                self._logger.error(f"An exception occurred when flushing: {traceback.format_exc()}")
        finally:
            self._flushing = False
