import traceback
from asyncio import Event as AsyncEvent
from logging import Logger
from typing import Generic, TypeVar, final

from ...config import DatabaseKind
from ...database import Database
from ...database.entity import Entity

_EntityT = TypeVar("_EntityT", bound=Entity)


@final
class WriteBuffer(Generic[_EntityT]):
    def __init__(
        self,
        cls: type[_EntityT],
        database: Database,
        logger: Logger | None = None,  # TODO: Remove this.
    ) -> None:
        self.__cls = cls
        self.__database = database
        self.__entities: list[_EntityT] = []
        self.__flushing = False
        self.__empty_event = AsyncEvent()
        self.__empty_event.set()
        self.__logger = logger

    def __len__(self) -> int:
        return len(self.__entities)

    @property
    def cls(self) -> type[_EntityT]:
        return self.__cls

    @property
    def flushing(self) -> bool:
        return self.__flushing

    def add(self, entity: _EntityT) -> None:
        self.__entities.append(entity)
        self.__empty_event.clear()

    async def flush(self) -> None:
        if self.__flushing or not self.__entities:
            return
        if not self.__entities:
            return

        self.__flushing = True

        entities = self.__entities
        self.__entities = []

        try:
            async with self.__database.session() as session:
                match self.__database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert
                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert

                await session.execute(
                    insert(self.__cls)
                    .values([entity.values() for entity in entities])
                    .on_conflict_do_nothing()  # TODO: Warn when there is a conflict.
                )
                await session.commit()
        except Exception:
            self.__entities = [*entities, *self.__entities]
            if self.__logger:
                self.__logger.error(
                    f"An exception occurred when flushing: {traceback.format_exc()}"
                )
        finally:
            self.__flushing = False
            if not self.__entities:
                self.__empty_event.set()

    async def wait_until_empty(self) -> None:
        await self.__empty_event.wait()
