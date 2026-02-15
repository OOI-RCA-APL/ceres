from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Literal,
    TypeAlias,
    Unpack,
    override,
)

from pydantic import BeforeValidator, PlainSerializer
from sqlalchemy import Index, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from ceres._internal import util
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
    Filtering,
)
from ceres._internal.manager import BaseNodeManager
from ceres._internal.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres._internal.util import MatchMode
from ceres.data import MaybeSequence, StrEnum
from ceres.timing import utc

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres._internal.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType


class MessageDirection(StrEnum):
    SEND = "send"
    RECEIVE = "receive"


MessageDirectionRaw: TypeAlias = Literal["send", "receive"]
MessageDirectionInput: TypeAlias = MessageDirection | MessageDirectionRaw


def _serialize_message_content_json(value: bytes) -> str:
    return value.decode("latin-1", "ignore")


def _deserialize_message_content_json(value: Any) -> Any | None:
    if isinstance(value, str):
        return value.encode("latin-1", "ignore")

    return value


MessageContent = Annotated[
    bytes,
    BeforeValidator(_deserialize_message_content_json),
    PlainSerializer(_serialize_message_content_json, str, "json-unless-none"),
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
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__connection", cls.connection),
            EnumConstraint(cls.direction, MessageDirection, f"ck_{cls.__tablename__}__direction"),
            Index(f"ix_{cls.__tablename__}__content", cls.content).ddl_if("sqlite"),
            Index(
                f"ix_{cls.__tablename__}__content",
                func.ceres_tokenize_bytes(cls.content).label("tokens"),
                postgresql_ops={"tokens": "gin_trgm_ops"},
                postgresql_using="gin",
            ).ddl_if("postgresql"),
        )


MessageField: TypeAlias = (
    BaseRecordField
    | Literal[
        "connection",
        "direction",
        "content",
    ]
)
MessageOrder: TypeAlias = (
    BaseRecordOrder
    | Literal[
        "connection",
        "connection:asc",
        "connection:desc",
        "direction",
        "direction:asc",
        "direction:desc",
        "content",
        "content:asc",
        "content:desc",
    ]
)


class MessageFilterArgs(BaseRecordFilterArgs[MessageField, MessageOrder], total=False):
    direction: MaybeSequence[MessageDirectionInput] | None
    content: MaybeSequence[MessageContent] | None
    contains: MaybeSequence[MessageContent] | None
    prefix: MaybeSequence[MessageContent] | None
    suffix: MaybeSequence[MessageContent] | None


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
    content: MaybeSequence[MessageContent] | None = None
    """Filter by `content` being equal to one or more given byte sequences."""
    contains: MaybeSequence[MessageContent] | None = None
    """Filter by `content` containing one or more given byte substrings."""
    prefix: MaybeSequence[MessageContent] | None = None
    """Filter by `content` starting with one or more given byte prefixes."""
    suffix: MaybeSequence[MessageContent] | None = None
    """Filter by `content` ending with one or more given byte suffixes."""

    @override
    def _matches(self, obj: Message, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super()._matches(obj, now=now):
            return False

        if self.connection is not None:
            if obj.connection is None or not util.match_value(obj.connection, self.connection):
                return False
        if not util.match_string(obj.connection, self.connection_contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.connection, self.connection_prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.connection, self.connection_suffix, MatchMode.SUFFIX):
            return False

        if not util.match_value(obj.direction, self.direction):
            return False

        if not util.match_value(obj.content, self.content):
            return False
        if not util.match_string(obj.content, self.contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.content, self.prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.content, self.suffix, MatchMode.SUFFIX):
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
            yield util.sql_match_value(columns.connection, self.connection)

        if self.connection_contains is not None:
            yield util.sql_match_string(
                columns.connection,
                self.connection_contains,
                MatchMode.CONTAINS,
            )
        if self.connection_prefix is not None:
            yield util.sql_match_string(
                columns.connection,
                self.connection_prefix,
                MatchMode.PREFIX,
            )
        if self.connection_suffix is not None:
            yield util.sql_match_string(
                columns.connection,
                self.connection_suffix,
                MatchMode.SUFFIX,
            )

        if self.direction is not None:
            yield util.sql_match_value(columns.direction, self.direction)

        if self.content is not None:
            yield util.sql_match_value(columns.content, self.content)

        hex = func.ceres_tokenize_bytes(columns.content)
        if self.contains is not None:
            matches = [util.tokenize_bytes(current) for current in util.seq(self.contains)]
            yield util.sql_match_string(hex, matches, MatchMode.CONTAINS)
        if self.prefix is not None:
            matches = [util.tokenize_bytes(current) for current in util.seq(self.prefix)]
            yield util.sql_match_string(hex, matches, MatchMode.PREFIX)
        if self.suffix is not None:
            matches = [util.tokenize_bytes(current) for current in util.seq(self.suffix)]
            yield util.sql_match_string(hex, matches, MatchMode.SUFFIX)


class MessageCreate(BaseRecordCreate, slots=True):
    connection: str | None = None
    direction: MessageDirection
    content: MessageContent


class MessageUpdate(BaseRecordUpdate, total=False):
    connection: str | None
    direction: MessageDirection
    content: MessageContent


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
    def where(
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
    def where(
        self,
        filter: MessageFilter | Callable[[Message], bool] | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> MessageOutputChannel:
        return super().where(filter, **kwargs)


class Message(BaseRecord, MessageCreate, ConcreteEntity, slots=True):
    Manager: ClassVar[type[MessageManager]] = MessageManager
    BoundManager: ClassVar[type[BoundMessageManager]] = BoundMessageManager
    Row: ClassVar[type[MessageRow]] = MessageRow
    Create: ClassVar[type[MessageCreate]] = MessageCreate
    Update: ClassVar[type[MessageUpdate]] = MessageUpdate
    Filter: ClassVar[type[MessageFilter]] = MessageFilter
    FilterArgs: ClassVar[type[MessageFilterArgs]] = MessageFilterArgs
    Field = MessageField
    Order = MessageOrder
    Direction: ClassVar[type[MessageDirection]] = MessageDirection

    __naming__: ClassVar[EntityNaming] = EntityNaming("message")
