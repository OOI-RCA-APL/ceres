from datetime import datetime
from typing import Annotated, ClassVar, Iterable, Sequence
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import ColumnExpressionArgument, Index, Text
from sqlalchemy.orm import Mapped, QueryableAttribute, mapped_column
from sqlalchemy.schema import SchemaItem
from typing_extensions import TypedDict, override

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.utilities import as_sequence, escape_like_expression
from ceres.address import Address
from ceres.data import DateTime, StrEnum
from ceres.database.enums import DatabaseType
from ceres.level import Level
from ceres.record import (
    BaseRecord,
    BaseRecordCreate,
    BaseRecordFilter,
    BaseRecordFilterArgs,
    BaseRecordRow,
)
from ceres.timing import utc


class LogEntryRow(BaseRecordRow, kw_only=True):
    __tablename__ = "log_entries"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("level", Level, name=f"ck_{cls.__tablename__}__level"),
            Index(f"ix_{cls.__tablename__}__content", "content"),
        )


class LogEntryUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    level: Level
    content: str


class LogEntryOrder(StrEnum):
    OLD_TO_NEW = "old-to-new"
    NEW_TO_OLD = "new-to-old"


class LogEntryFilterArgs(BaseRecordFilterArgs, total=False):
    level: Level | Sequence[Level] | None
    content_contains: str | None
    content_prefix: str | None
    content_suffix: str | None
    order: LogEntryOrder | None  # type: ignore


class LogEntryFilter(BaseRecordFilter["LogEntry"]):
    level: Annotated[Level | Sequence[Level] | None, CLIOption(list[Level] | None)] = Field(
        default=None,
        description="Filter by log level(s).",
    )
    content_contains: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only log entries with content that contain the given string.",
    )
    content_prefix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only log entries with content that starts with the given string.",
    )
    content_suffix: Annotated[str | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter, keeping only log entries with content that ends with the given string.",
    )
    order: Annotated[LogEntryOrder | None, CLIOption(LogEntryOrder | None)] = Field(
        default=None,
        description="Specify result order.",
    )

    @override
    def matches(self, obj: "LogEntry") -> bool:
        if not super().matches(obj):
            return False

        if self.level is not None:
            if obj.level not in as_sequence(self.level):
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
    def _get_row_cls(self) -> type[LogEntryRow]:
        return LogEntryRow

    @override
    def _get_search_content(self, obj: "LogEntry") -> dict[str, str]:
        return {
            **super()._get_search_content(obj),
            "level": obj.level,
            "content": obj.content,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_row_cls()

        return {
            **super()._get_database_search_content(dialect),
            "level": columns.level,
            "content": columns.content,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.level is not None:
            yield columns.level.in_(as_sequence(self.level))
        if self.content_contains is not None:
            yield columns.content.like("%" + escape_like_expression(self.content_contains) + "%")
        if self.content_prefix is not None:
            yield columns.content.like(escape_like_expression(self.content_prefix) + "%")
        if self.content_suffix is not None:
            yield columns.content.like("%" + escape_like_expression(self.content_suffix))


class LogEntryCreate(BaseRecordCreate):
    level: Annotated[Level, CLIOption(Level)]
    content: Annotated[str, CLIOption(str)]


class LogEntry(BaseRecord, LogEntryCreate):
    Order: ClassVar = LogEntryOrder

    Row: ClassVar = LogEntryRow
    Create: ClassVar = LogEntryCreate
    Update: ClassVar = LogEntryUpdate
    Filter: ClassVar = LogEntryFilter
    FilterArgs: ClassVar = LogEntryFilterArgs

    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    address: Annotated[Address, CLIOption(str)]
    timestamp: Annotated[DateTime, CLIOption(datetime)] = Field(default_factory=utc)
    level: Annotated[Level, CLIOption(Level)]
    content: Annotated[str, CLIOption(str)]
