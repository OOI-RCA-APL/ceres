from __future__ import annotations

from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterable,
    ClassVar,
    Iterable,
    Literal,
    TypeAlias,
    Unpack,
    override,
)

from pydantic import BeforeValidator, PlainSerializer
from sqlalchemy import LargeBinary, SQLColumnExpression, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, SchemaItem

from ceres._internal import util
from ceres._internal.entity import BaseEntityManager
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager import BaseBoundManager
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
from ceres.data import MaybeSequence, StrEnum
from ceres.database import DatabaseType
from ceres.timing import utc

with lazy_imports(__name__):
    from ceres._internal.database.types import EnumConstraint, EnumMapper


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
        "-direction",
        "content",
        "-content",
    ]
)


class MessageFilterArgs(BaseRecordFilterArgs[MessageField, MessageOrder], total=False):
    direction: MessageDirection | None
    content_contains: MaybeSequence[MessageContent] | None
    content_prefix: MaybeSequence[MessageContent] | None
    content_suffix: MaybeSequence[MessageContent] | None


class MessageFilter(BaseRecordFilter["Message", MessageField, MessageOrder]):
    direction: MessageDirection | None = None
    """Filter by `direction`."""
    content_contains: MaybeSequence[MessageContent] | None = None
    """Filter by `content` containing one or more given byte substrings."""
    content_prefix: MaybeSequence[MessageContent] | None = None
    """Filter by `content` starting with one or more given byte prefixes."""
    content_suffix: MaybeSequence[MessageContent] | None = None
    """Filter by `content` ending with one or more given byte suffixes."""

    @override
    def matches(self, obj: Message, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj, now=now):
            return False

        if self.direction is not None:
            if obj.direction not in util.as_sequence(self.direction):
                return False
        if self.content_contains is not None:
            if not any(
                substring in obj.content for substring in util.as_sequence(self.content_contains)
            ):
                return False
        if self.content_prefix is not None:
            if not any(
                obj.content.startswith(prefix) for prefix in util.as_sequence(self.content_prefix)
            ):
                return False
        if self.content_suffix is not None:
            if not any(
                obj.content.endswith(suffix) for suffix in util.as_sequence(self.content_suffix)
            ):
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
            yield columns.direction == self.direction
        if self.content_contains is not None:
            yield util.sqlorf(
                columns.content.like(b"%" + _escape_bytes_like_expression(substring) + b"%")
                for substring in util.as_sequence(self.content_contains)
            )
        if self.content_prefix is not None:
            yield util.sqlorf(
                columns.content.like(_escape_bytes_like_expression(prefix) + b"%")
                for prefix in util.as_sequence(self.content_prefix)
            )
        if self.content_suffix is not None:
            yield util.sqlorf(
                columns.content.like(b"%" + _escape_bytes_like_expression(suffix))
                for suffix in util.as_sequence(self.content_suffix)
            )


def _escape_bytes_like_expression(text: bytes) -> bytes:
    return text.replace(b"%", b"%%").replace(b"_", b"__")


class MessageCreate(BaseRecordCreate):
    direction: MessageDirection
    content: MessageContent


class MessageUpdate(BaseRecordUpdate, total=False):
    direction: MessageDirection
    content: MessageContent


class Message(BaseRecord, MessageCreate):
    Row: ClassVar[type[MessageRow]] = MessageRow
    Create: ClassVar[type[MessageCreate]] = MessageCreate
    Update: ClassVar[type[MessageUpdate]] = MessageUpdate
    Filter: ClassVar[type[MessageFilter]] = MessageFilter
    FilterArgs: ClassVar[type[MessageFilterArgs]] = MessageFilterArgs
    Field = MessageField
    Order = MessageOrder
    Direction: ClassVar[type[MessageDirection]] = MessageDirection


with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node
    from ceres.stream import Stream


class MessageManager(
    BaseEntityManager[
        Message,
        Message.Row,
        Message.Create,
        Message.Update,
        Message.Filter,
        Message.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node, /) -> None:
        super().__init__(source, Message)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Message
        _F = Message.Filter
        _FA = Message.FilterArgs

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        def select(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> AsyncIterable[_E]: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...


class BoundMessageManager(MessageManager, BaseBoundManager[Message]):
    def __init__(self, source: Node, /) -> None:
        super().__init__(source)

    def store(self, message: Message, /) -> None:
        return self._node.store(message)

    def follow(
        self,
        filter: MessageFilter | None = None,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Stream[Message]:
        from ceres.event import MessageEvent, MessageReceivedEvent

        filter = self._apply_default_filter(filter, kwargs)

        if TYPE_CHECKING:
            util.blackhole(MessageEvent)

        return (
            self._node.events.follow()
            .every(MessageEvent if not TYPE_CHECKING else MessageReceivedEvent)
            .map(lambda event: event.message)
            .filter(filter.matches)
        )
