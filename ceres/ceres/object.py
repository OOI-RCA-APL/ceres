import asyncio
from abc import abstractmethod
from asyncio import Event as AsyncEvent
from asyncio import Lock as AsyncLock
from collections import deque
from dataclasses import dataclass, field
from itertools import groupby
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Mapping,
    Sequence,
    TypeVar,
)
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.roles import ExpressionElementRole
from typing_extensions import ParamSpec, dataclass_transform, override

from ceres.address import Address
from ceres.alert import Alert
from ceres.config import DatabaseKind
from ceres.data import (
    VALIDATED_DATACLASS_FIELD_SPECIFIERS,
    ValidatedDataclass,
)
from ceres.database import Database
from ceres.events import (
    AlertEvent,
    Event,
    LogEvent,
    MessageReceivedEvent,
    MessageSentEvent,
    StartedEvent,
    StoppedEvent,
)
from ceres.internal.database.entities import (
    AlertEntity,
    ComponentEntity,
    LogEntryEntity,
    MessageEntity,
)
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import chunkify, dictify
from ceres.level import Level
from ceres.logs import Log, LogEntry
from ceres.message import Message
from ceres.stream import Stream, WriteStream

if TYPE_CHECKING:
    from ceres.component import Component
    from ceres.server import Server
else:
    Component = object
    Server = object

_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")

WhereExpression = ColumnElement[bool] | ExpressionElementRole[bool]
OrderByExpression = ColumnElement[Any] | ExpressionElementRole[Any]

Item = Message | Alert | LogEntry


@dataclass
class _Flush:
    items: Sequence[Item]
    event: AsyncEvent = field(default_factory=AsyncEvent)


@dataclass_transform(
    kw_only_default=True,
    field_specifiers=VALIDATED_DATACLASS_FIELD_SPECIFIERS,
)
class Object(ValidatedDataclass, Tasklet):
    def __post_init_post_parse__(self) -> None:
        self.__events: WriteStream[Event] = WriteStream()
        self.__log = Log(self)

        self.__mapping: dict[Address, UUID] | None = None
        self.__mapping_lock = AsyncLock()
        self.__flush_buffer: list[Item] = []
        self.__flushes: deque[_Flush] = deque()
        self.__flushed = AsyncEvent()
        self.__flushed.set()

    @property
    def __container__(self) -> "Object | None":
        return None

    @property
    @abstractmethod
    def address(self) -> Address:
        ...

    @property
    @abstractmethod
    def root(self) -> Component:
        ...

    @property
    @abstractmethod
    def database(self) -> Database:
        ...

    @property
    @abstractmethod
    def server(self) -> Server | None:
        ...

    @property
    def log(self) -> Log:
        return self.__log

    @property
    def events(self) -> Stream[Event]:
        return self.__events.view()

    @property
    def settled(self) -> bool:
        if not self.running:
            return True

        return self.__flushed.is_set()

    async def settle(self) -> None:
        await self.flush()
        await self.__flushed.wait()

    def emit(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        if "address" not in kwargs:
            kwargs["address"] = self.address

        return self.propagate(event_cls(*args, **kwargs))

    def propagate(self, event: _EventT) -> _EventT:
        # Add the event to the outgoing event stream.
        self.__events.put(event)
        # If there is no containing object, store the event ourselves.
        if self.__container__ is None:
            match event:
                case MessageSentEvent() | MessageReceivedEvent():
                    self.store(event.message)
                case AlertEvent():
                    self.store(event.alert)
                case LogEvent():
                    self.store(event.entry)
                case _:
                    pass
        # Otherwise propagate the event to the containing object.
        else:
            self.__container__.propagate(event)

        return event

    def alert(
        self,
        level: Level,
        code: str,
        info: Mapping[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            address=self.address,
            level=level,
            code=code,
            info=info if info is not None else {},
        )

        self.emit(AlertEvent, alert=alert)
        return alert

    @override
    async def __run__(self) -> None:
        self.emit(StartedEvent)

        await self.__process_flush()

    async def __process_flush(self) -> None:
        while True:
            if self.__flush_buffer:
                await self.flush()
            await asyncio.sleep(0.1)

    @override
    async def __stop__(self) -> None:
        await self.flush()

    @override
    async def __done__(self) -> None:
        self.emit(StoppedEvent)

    async def get_id(
        self,
        address: Address | None = None,
        default: UUID | None = None,
    ) -> UUID:
        if address is None:
            address = self.address
        if self.__container__ is not None:
            return await self.__container__.get_id(address, default=default)

        if self.__mapping is not None:
            id = self.__mapping.get(address)
            if id is not None:
                return id

        async with await self.__init_database_session() as session:
            mapping = await self.__get_or_load_mapping(session)
            id = mapping.get(address)
            if id is not None:
                return id

            if id is None:
                id = await session.scalar(
                    select(ComponentEntity.id).where(ComponentEntity.address == address),
                )

            if id is None:
                id = default or uuid4()
                component = ComponentEntity(id=id, address=address)

                session.add(component)
                await session.commit()

            mapping[address] = id
            return id

    def store(self, item: Item) -> None:
        if not isinstance(item, Item):
            raise TypeError(f"unsupported item type: {type(item)}")

        # Add the item to the flush buffer and clear the flushed event.
        self.__flush_buffer.append(item)
        self.__flushed.clear()

    async def flush(self) -> None:
        # Keep track of all pending flushes.
        pending = tuple(self.__flushes)

        # If there's no items in the buffer, wait for the latest flush to complete.
        if not self.__flush_buffer:
            if pending:
                await pending[-1].event.wait()

            # Otherwise return, there's nothing to wait for.
            return

        # Register the flush request.
        flush = _Flush(items=tuple(self.__flush_buffer))
        self.__flushes.append(flush)

        # Clear the buffer.
        self.__flush_buffer = []

        try:
            # Wait for the previous flush to complete.
            if pending:
                await pending[-1].event.wait()

            async with await self.__init_database_session() as session:
                # Pick the number of items to insert in a single query based on the database kind.
                match self.database.kind:
                    case DatabaseKind.SQLITE:
                        from sqlalchemy.dialects.sqlite import insert

                        chunk_size = 500

                    case DatabaseKind.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert  # noqa

                        chunk_size = 1000

                # Group items by item class.
                for model_cls, model in groupby(flush.items, type):
                    # Determine the entity class of item.
                    if issubclass(model_cls, Message):
                        entity_cls = MessageEntity
                    elif issubclass(model_cls, Alert):
                        entity_cls = AlertEntity
                    elif issubclass(model_cls, LogEntry):
                        entity_cls = LogEntryEntity
                    else:
                        continue

                    # Insert items in chunks.
                    for chunk in chunkify(model, chunk_size):
                        values: list[dict[str, Any]] = []

                        for model in chunk:
                            # Convert the model to a dictionary, replacing the "address" field with
                            # the "component_id".
                            data = dictify(model)
                            data.pop("address", None)
                            data["component_id"] = await self.get_id(model.address)
                            values.append(data)

                        await session.execute(
                            insert(entity_cls).on_conflict_do_nothing(),
                            values,
                        )

                await session.commit()
        finally:
            # Notify the flush is complete.
            flush.event.set()
            # Remove it from the queue.
            self.__flushes.popleft()
            # If there are items no items remaining in the buffer and no pending flushes, set
            # the "flushed" event.
            if not self.__flush_buffer and not self.__flushes:
                self.__flushed.set()

    async def __generate_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        return dict(
            tuple(row)
            for row in await session.execute(
                select(ComponentEntity.address, ComponentEntity.id),
            )
        )

    async def __get_or_load_mapping(self, session: AsyncSession) -> dict[Address, UUID]:
        async with self.__mapping_lock:
            if self.__mapping is None:
                self.__mapping = await self.__generate_mapping(session)

        return self.__mapping

    async def __init_database_session(self) -> AsyncSession:
        await self.database.init()
        return self.database.session()
