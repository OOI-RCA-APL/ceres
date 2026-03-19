from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Unpack, override

from sqlalchemy import Index, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from ceres.__internal__.database.bytes import tokenize_bytes
from ceres.__internal__.database.types import EnumConstraint, EnumMapper
from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
    Filtering,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres.__internal__.utilities.collections import seq
from ceres.data import BytesFromString, BytesToString, MaybeSequence, StrEnum
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType

__all__ = [
    "Message",
]


class MessageDirection(StrEnum):
    SEND = "send"
    RECEIVE = "receive"


type MessageDirectionRaw = Literal["send", "receive"]
type MessageDirectionInput = MessageDirection | MessageDirectionRaw

type MessageData = Annotated[
    bytes,
    BytesFromString("latin-1", "backslashreplace"),
    BytesToString("latin-1", "backslashreplace"),
]


class MessageRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "messages"

    connection: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        server_default=expression.null(),
    )
    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    data: Mapped[bytes] = mapped_column(LargeBinary)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__connection", cls.connection),
            EnumConstraint(cls.direction, MessageDirection, f"ck_{cls.__tablename__}__direction"),
            Index(f"ix_{cls.__tablename__}__data", cls.data).ddl_if("sqlite"),
            Index(
                f"ix_{cls.__tablename__}__data",
                func.ceres_tokenize_bytes(cls.data).label("tokens"),
                postgresql_ops={"tokens": "gin_trgm_ops"},
                postgresql_using="gin",
            ).ddl_if("postgresql"),
        )


type MessageField = (
    BaseRecordField
    | Literal[
        "connection",
        "direction",
        "data",
    ]
)
type MessageOrder = (
    BaseRecordOrder
    | Literal[
        "connection",
        "connection:asc",
        "connection:desc",
        "direction",
        "direction:asc",
        "direction:desc",
        "data",
        "data:asc",
        "data:desc",
    ]
)


class MessageFilterArgs(BaseRecordFilterArgs[MessageField, MessageOrder], total=False):
    connection: MaybeSequence[str] | None
    connection_contains: MaybeSequence[str] | None
    connection_prefix: MaybeSequence[str] | None
    connection_suffix: MaybeSequence[str] | None
    direction: MaybeSequence[MessageDirectionInput] | None
    data: MaybeSequence[MessageData] | None
    contains: MaybeSequence[MessageData] | None
    prefix: MaybeSequence[MessageData] | None
    suffix: MaybeSequence[MessageData] | None


class MessageFilter(BaseRecordFilter["Message", MessageField, MessageOrder]):
    connection: MaybeSequence[str] | None = None
    """Filter by `connection` being equal to one or more given strings."""
    connection_contains: MaybeSequence[str] | None = None
    """Filter by `connection` containing one or more given substrings."""
    connection_prefix: MaybeSequence[str] | None = None
    """Filter by `connection` starting with one or more given substrings."""
    connection_suffix: MaybeSequence[str] | None = None
    """Filter by `connection` ending with one or more given substrings."""
    direction: MaybeSequence[MessageDirection] | None = None
    """Filter by `direction`."""
    data: MaybeSequence[MessageData] | None = None
    """Filter by `data` being equal to one or more given byte sequences."""
    contains: MaybeSequence[MessageData] | None = None
    """Filter by `data` containing one or more given byte substrings."""
    prefix: MaybeSequence[MessageData] | None = None
    """Filter by `data` starting with one or more given byte prefixes."""
    suffix: MaybeSequence[MessageData] | None = None
    """Filter by `data` ending with one or more given byte suffixes."""

    @override
    def _matches(self, obj: Message, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super()._matches(obj, now=now):
            return False

        if self.connection is not None:
            if obj.connection is None or not self._match_value(obj.connection, self.connection):
                return False
        if not self._match_string_contains(obj.connection, self.connection_contains):
            return False
        if not self._match_string_prefix(obj.connection, self.connection_prefix):
            return False
        if not self._match_string_suffix(obj.connection, self.connection_suffix):
            return False

        if not self._match_value(obj.direction, self.direction):
            return False

        if not self._match_value(obj.data, self.data):
            return False
        if not self._match_string_contains(obj.data, self.contains):
            return False
        if not self._match_string_prefix(obj.data, self.prefix):
            return False
        if not self._match_string_suffix(obj.data, self.suffix):
            return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[MessageRow]:
        return MessageRow

    @override
    def _get_where(
        self,
        dialect: DatabaseType,
        *,
        now: datetime | None = None,
    ) -> Iterable[SQLColumnExpression[bool]]:
        now = utc(now)
        yield from super()._get_where(dialect, now=now)
        columns = self._get_row_cls()

        if self.connection is not None:
            yield self._sql_match_value(columns.connection, self.connection)
        if self.connection_contains is not None:
            yield self._sql_match_string_contains(columns.connection, self.connection_contains)
        if self.connection_prefix is not None:
            yield self._sql_match_string_prefix(columns.connection, self.connection_prefix)
        if self.connection_suffix is not None:
            yield self._sql_match_string_suffix(columns.connection, self.connection_suffix)

        if self.direction is not None:
            yield self._sql_match_value(columns.direction, self.direction)

        if self.data is not None:
            yield self._sql_match_value(columns.data, self.data)

        hex = func.ceres_tokenize_bytes(columns.data)
        if self.contains is not None:
            matches = [tokenize_bytes(current) for current in seq(self.contains)]
            yield self._sql_match_string_contains(hex, matches)
        if self.prefix is not None:
            matches = [tokenize_bytes(current) for current in seq(self.prefix)]
            yield self._sql_match_string_prefix(hex, matches)
        if self.suffix is not None:
            matches = [tokenize_bytes(current) for current in seq(self.suffix)]
            yield self._sql_match_string_suffix(hex, matches)


class MessageCreate(BaseRecordCreate, slots=True):
    connection: str | None = None
    direction: MessageDirection
    data: MessageData


class MessageUpdate(BaseRecordUpdate, total=False):
    connection: str | None
    direction: MessageDirection
    data: MessageData


class _BaseMessageQuery(
    BaseEntityQuery[
        "Message",
        MessageFilter,
        MessageUpdate,
        "MessageQuery",
    ]
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[MessageQuery]:
        return MessageQuery

    @override
    def where(  # type: ignore
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> MessageQuery:
        return super().where(filter, **kwargs)


class MessageQuery(
    EntityQuery[
        "Message",
        MessageFilter,
        MessageUpdate,
    ],
    _BaseMessageQuery,
):
    __slots__ = ()


class MessageManager(
    BaseEntityManager[
        "Message",
        MessageRow,
        MessageCreate,
        MessageUpdate,
        MessageFilter,
        MessageFilterArgs,
    ],
    _BaseMessageQuery,
):
    __slots__ = ()

    def __init__(
        self,
        source: DatabaseSource,
        /,
        filtering: Filtering[MessageFilter] = None,
    ) -> None:
        super().__init__(source, Message, filtering)

    async def get(self, id: UUID, /) -> Message | None:
        return await self.where(id=id).first()


class BoundMessageManager(MessageManager, BaseNodeManager):
    __slots__ = ()

    def __init__(
        self,
        source: NodeSource,
        /,
        filtering: Filtering[MessageFilter] = None,
    ) -> None:
        super().__init__(source, filtering)

    @property
    def stream(self) -> MessageOutputChannel:
        from ceres.event import MessageReceivedEvent, MessageSentEvent

        return MessageOutputChannel(
            self.__node__.events.stream.every(MessageSentEvent, MessageReceivedEvent)
            .map(lambda event: event.message)
            .where(lambda message: self._get_resolved_filter().matches(message))
        )


class MessageOutputChannel(
    EntityOutputChannel[
        "Message",
        MessageFilter,
        MessageFilterArgs,
    ]
):
    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[MessageFilter]:
        return MessageFilter

    @property
    def received(self) -> MessageOutputChannel:
        return self.where(lambda message: message.direction == MessageDirection.RECEIVE)

    @property
    def sent(self) -> MessageOutputChannel:
        return self.where(lambda message: message.direction == MessageDirection.SEND)

    @override
    def where(  # type: ignore
        self,
        filter: MessageFilter | Callable[[Message], bool] | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> MessageOutputChannel:
        return super().where(filter, **kwargs)


class Message(BaseRecord, MessageCreate, ConcreteEntity, slots=True):
    Manager = MessageManager
    BoundManager = BoundMessageManager
    Row = MessageRow
    Create = MessageCreate
    Update = MessageUpdate
    Filter = MessageFilter
    FilterArgs = MessageFilterArgs
    Field = MessageField
    Order = MessageOrder
    Direction = MessageDirection
    Data = MessageData

    __naming__: ClassVar[EntityNaming] = EntityNaming("message")
