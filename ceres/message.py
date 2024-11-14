from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, ClassVar, Iterable, Literal, TypeAlias, override

from pydantic import BeforeValidator, Field, PlainSerializer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import LargeBinary

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.entity import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordField,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordOrder,
    BaseRecordRow,
    BaseRecordUpdate,
)
from ceres._internal.lazy import lazy_imports
from ceres.data import StrEnum
from ceres.database.enums import DatabaseType
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression
    from sqlalchemy.sql.functions import func

    from ceres._internal import util
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
    content_contains: MessageContent | None
    content_prefix: MessageContent | None
    content_suffix: MessageContent | None


class MessageFilter(BaseRecordFilter["Message", MessageField, MessageOrder]):
    direction: Annotated[MessageDirection | None, CLIOption(MessageDirection | None)] = Field(
        default=None,
        description="Filter by message direction.",
    )
    content_contains: Annotated[MessageContent | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only messages with content that contains the given bytes.",
    )
    content_prefix: Annotated[MessageContent | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only messages with content that starts with the given bytes.",
    )
    content_suffix: Annotated[MessageContent | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only messages with content that ends with the given bytes.",
    )

    @override
    def matches(self, obj: Message, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj, now=now):
            return False

        if self.direction is not None:
            if obj.direction not in util.as_sequence(self.direction):
                return False
        if self.content_contains is not None:
            if self.content_contains not in obj.content:
                return False
        if self.content_prefix is not None:
            if not obj.content.startswith(self.content_prefix):
                return False
        if self.content_suffix is not None:
            if not obj.content.endswith(self.content_suffix):
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
            yield columns.content.like(
                b"%" + util.escape_like_expression(self.content_contains) + b"%"
            )
        if self.content_prefix is not None:
            yield columns.content.like(util.escape_like_expression(self.content_prefix) + b"%")
        if self.content_suffix is not None:
            yield columns.content.like(b"%" + util.escape_like_expression(self.content_suffix))


class MessageCreate(BaseRecordCreate):
    direction: Annotated[MessageDirection, CLIOption(MessageDirection)]
    content: Annotated[MessageContent, CLIOption(str)]


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
