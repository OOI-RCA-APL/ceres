from __future__ import annotations

from typing import Annotated, Any, ClassVar, Iterable, Mapping, TypedDict, override

from pydantic import BeforeValidator, Field, PlainSerializer

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.lazy import lazy_imports
from ceres.address import Address
from ceres.data import DateTime, StrEnum
from ceres.database.enums import DatabaseType
from ceres.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordRow,
)

with lazy_imports(__name__):
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression
    from sqlalchemy.sql.functions import func
    from sqlalchemy.sql.sqltypes import LargeBinary

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
            Index(f"ix_{cls.__tablename__}__content", "content").ddl_if("sqlite"),
            Index(
                f"ix_{cls.__tablename__}__content",
                func.ceres_decode_latin1("content").label("decoded_content"),
                postgresql_ops={"decoded_content": "gin_trgm_ops"},
                postgresql_using="gin",
            ).ddl_if("postgresql"),
        )


class MessageOrder(StrEnum):
    OLDEST = "oldest"
    NEWEST = "newest"


class MessageFilterArgs(BaseRecordFilterArgs, total=False):
    direction: MessageDirection | None
    content_contains: MessageContent | None
    content_prefix: MessageContent | None
    content_suffix: MessageContent | None
    order: MessageOrder | None  # type: ignore


class MessageFilter(BaseRecordFilter["Message"]):
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
    order: Annotated[MessageOrder | None, CLIOption(MessageOrder | None)] = Field(
        default=None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: Message) -> bool:
        if not super().matches(obj):
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

    @override
    def _get_row_cls(self) -> type[MessageRow]:
        return MessageRow

    @override
    def _get_search_content(self, obj: Message) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "direction": obj.direction,
            "content": obj.content.decode("latin-1", "ignore"),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        match dialect:
            case DatabaseType.POSTGRES:
                content = func.ceres_decode_latin1(columns.content)
            case DatabaseType.SQLITE:
                content = columns.content

        return {
            **super()._get_database_search_content(dialect),
            "direction": columns.direction,
            "content": content,
        }

    @override
    def _get_database_search_content_encoded_fields(self, dialect: DatabaseType) -> set[str]:
        fields = super()._get_database_search_content_encoded_fields(dialect)

        match dialect:
            case DatabaseType.POSTGRES:
                pass
            case DatabaseType.SQLITE:
                fields.add("content")

        return fields

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
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


class MessageUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    direction: MessageDirection
    content: MessageContent


class Message(BaseRecord, MessageCreate):
    Order: ClassVar[type[MessageOrder]] = MessageOrder
    Direction: ClassVar[type[MessageDirection]] = MessageDirection

    Row: ClassVar[type[MessageRow]] = MessageRow
    Create: ClassVar[type[MessageCreate]] = MessageCreate
    Update: ClassVar[type[MessageUpdate]] = MessageUpdate
    Filter: ClassVar[type[MessageFilter]] = MessageFilter
    FilterArgs: ClassVar[type[MessageFilterArgs]] = MessageFilterArgs
