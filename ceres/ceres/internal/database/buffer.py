import traceback
from abc import ABC
from asyncio import Event as AsyncEvent
from typing import TYPE_CHECKING, Any, Callable, Generic, TypeVar

from ceres.alert import Alert
from ceres.config import DatabaseKind
from ceres.internal.database.entities import AlertEntity, LogEntryEntity, MessageEntity
from ceres.logs import Log, LogEntry
from ceres.message import Message

_ModelT = TypeVar("_ModelT", bound=Message | Alert | LogEntry)
_EntityT = TypeVar("_EntityT", bound=MessageEntity | AlertEntity | LogEntryEntity)

if TYPE_CHECKING:
    from ceres.environment import Environment
else:
    Environment = "Environment"


class WriteBuffer(Generic[_ModelT, _EntityT], ABC):
    def __init__(
        self,
        model_cls: type[_ModelT],
        entity_cls: type[_EntityT],
        environment: Callable[[], Environment],
        log: Log | None = None,  # TODO: Remove this.
    ) -> None:
        self.__model_cls = model_cls
        self.__entity_cls = entity_cls
        self.__environment = environment
        self.__pending: list[_ModelT] = []
        self.__flushing = False
        self.__empty_event = AsyncEvent()
        self.__empty_event.set()
        self.__logger = log

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

        environment = self.__environment()

        try:
            async with environment.database.session() as session:
                match environment.database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert
                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert  # noqa

                values: list[dict[str, Any]] = []

                for model in pending:
                    data = model.dict()
                    data.pop("source", None)
                    if model.source is not None:
                        data["source_id"] = await environment.assign_address_id(model.source)
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
