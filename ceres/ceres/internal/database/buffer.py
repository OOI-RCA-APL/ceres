import traceback
from abc import ABC
from asyncio import Event as AsyncEvent
from logging import Logger
from typing import TYPE_CHECKING, Any, Generic, Iterable, Mapping, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...address import Address
from ...alert import Alert
from ...config import DatabaseKind
from ...message import Message
from .entities import AlertEntity, ComponentEntity, MessageEntity

_ModelT = TypeVar("_ModelT", bound=Message | Alert)
_EntityT = TypeVar("_EntityT", bound=MessageEntity | AlertEntity)

if TYPE_CHECKING:
    from ...environment import Environment
else:
    Environment = "Environment"


class WriteBuffer(Generic[_ModelT, _EntityT], ABC):
    def __init__(
        self,
        model_cls: type[_ModelT],
        entity_cls: type[_EntityT],
        environment: Environment,
        logger: Logger | None = None,  # TODO: Remove this.
    ) -> None:
        self.__model_cls = model_cls
        self.__entity_cls = entity_cls
        self.__environment = environment
        self.__pending: list[_ModelT] = []
        self.__mapping: dict[Address, UUID] | None = None
        self.__flushing = False
        self.__empty_event = AsyncEvent()
        self.__empty_event.set()
        self.__logger = logger

    def __len__(self) -> int:
        return len(self.__pending)

    @property
    def model_cls(self) -> type[_ModelT]:
        return self.__model_cls

    @property
    def entity_cls(self) -> type[_EntityT]:
        return self.__entity_cls

    @property
    def flushing(self) -> bool:
        return self.__flushing

    def add(self, model: _ModelT) -> None:
        self.__pending.append(model)
        self.__empty_event.clear()

    async def flush(self) -> None:
        if self.__flushing or not self.__pending:
            return
        if not self.__pending:
            return

        self.__flushing = True

        pending = self.__pending
        self.__pending = []

        try:
            async with self.__environment.database.session() as session:
                match self.__environment.database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert
                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert

                mapping = await self.__get_updated_mapping(session, pending)
                values: list[dict[str, Any]] = []

                for model in pending:
                    data = model.dict()
                    data.pop("source", None)
                    data["source_id"] = mapping[model.source]
                    values.append(data)

                # TODO: Don't discard all buffered entities when a single entity insert fails.
                await session.execute(
                    insert(self.__entity_cls).values(values).on_conflict_do_nothing()
                )
                await session.commit()
        except Exception:
            if self.__logger:
                self.__logger.error(
                    f"An exception occurred when flushing: {traceback.format_exc()}"
                )
        finally:
            self.__flushing = False
            if not self.__pending:
                self.__empty_event.set()

    async def wait_until_empty(self) -> None:
        await self.__empty_event.wait()

    async def __generate_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        return {
            address: id
            for address, id in await session.execute(
                select(ComponentEntity.address, ComponentEntity.id)
            )
        }

    async def __get_updated_mapping(
        self,
        session: AsyncSession,
        models: Iterable[_ModelT] = (),
    ) -> Mapping[Address, UUID]:
        if self.__mapping is None:
            self.__mapping = await self.__generate_mapping(session)

        for model in models:
            if model.source not in self.__mapping:
                self.__mapping[model.source] = await self.__environment.assign_address_id(
                    model.source
                )

        return self.__mapping
