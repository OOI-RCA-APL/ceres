from __future__ import annotations

from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Iterable,
    Literal,
    TypeAlias,
    Unpack,
    override,
)
from uuid import UUID

from pydantic import BeforeValidator, PlainSerializer
from sqlalchemy import LargeBinary, SQLColumnExpression, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, SchemaItem

from ceres._internal import util
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.entity import BaseEntityManager, BaseEntityQuery, EntityQuery
from ceres._internal.manager import BaseNodeManager
from ceres._internal.protocols import DatabaseSource, NodeSource
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
from ceres.database import DatabaseType
from ceres.stream import Stream
from ceres.timing import utc


class MessageDirection(StrEnum):
    SEND = "send"
    RECEIVE = "receive"


def _serialize_message_content_json(value: bytes) -> str:
    return value.decode("latin-1")


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

    direction: Mapped[MessageDirection] = mapped_column(EnumMapper(MessageDirection))
    content: Mapped[bytes] = mapped_column(LargeBinary)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("direction", MessageDirection, f"ck_{cls.__tablename__}__direction"),
            Index(f"ix_{cls.__tablename__}__content", cls.content).ddl_if("sqlite"),
            Index(
                f"ix_{cls.__tablename__}__content",
                func.ceres_decode_latin1(cls.content).label("decoded_content"),
                postgresql_ops={"decoded_content": "gin_trgm_ops"},
                postgresql_using="gin",
            ).ddl_if("postgresql"),
        )


MessageField: TypeAlias = (
    BaseRecordField
    | Literal[
        "direction",
        "content",
    ]
)
MessageOrder: TypeAlias = (
    BaseRecordOrder
    | Literal[
        "direction",
        "direction:asc",
        "direction:desc",
        "content",
        "content:asc",
        "content:desc",
    ]
)


class MessageFilterArgs(BaseRecordFilterArgs[MessageField, MessageOrder], total=False):
    direction: MaybeSequence[MessageDirection] | None
    content: MaybeSequence[MessageContent] | None
    contains: MaybeSequence[MessageContent] | None
    prefix: MaybeSequence[MessageContent] | None
    suffix: MaybeSequence[MessageContent] | None


class MessageFilter(BaseRecordFilter["Message", MessageField, MessageOrder]):
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
    def matches(self, obj: Message, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj, now=now):
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

        if self.direction is not None:
            yield util.sql_match_value(columns.direction, self.direction)

        if self.content is not None:
            yield util.sql_match_value(columns.content, self.content)

        decoded = func.ceres_decode_latin1(columns.content)
        if self.contains is not None:
            matches = [current.decode("latin-1") for current in util.as_sequence(self.contains)]
            yield util.sql_match_string(decoded, matches, MatchMode.CONTAINS)
        if self.prefix is not None:
            matches = [current.decode("latin-1") for current in util.as_sequence(self.prefix)]
            yield util.sql_match_string(decoded, matches, MatchMode.PREFIX)
        if self.suffix is not None:
            matches = [current.decode("latin-1") for current in util.as_sequence(self.suffix)]
            yield util.sql_match_string(decoded, matches, MatchMode.SUFFIX)


def _escape_bytes_like_expression(text: bytes) -> bytes:
    return text.replace(b"%", b"%%").replace(b"_", b"__")


class MessageCreate(BaseRecordCreate):
    direction: MessageDirection
    content: MessageContent


class MessageUpdate(BaseRecordUpdate, total=False):
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
    pass


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
    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Message)

    async def get(self, id: UUID, /) -> Message | None:
        return await self.where(id=id).first()


class BoundMessageManager(MessageManager, BaseNodeManager):
    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    def follow(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Stream[Message]:
        from ceres.event import MessageEvent, MessageReceivedEvent

        resolved = self._get_resolved_filter_args(filter, kwargs)
        return (
            self.__node__.events.follow()
            .every(MessageEvent if not TYPE_CHECKING else MessageReceivedEvent)
            .map(lambda event: event.message)
            .filter(resolved.matches)
        )


class Message(BaseRecord, MessageCreate):
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
