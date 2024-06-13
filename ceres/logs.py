from __future__ import annotations

from typing import Annotated, Any, ClassVar, Iterable, Mapping, Sequence, TypedDict, override

from pydantic import Field

from ceres._internal import util
from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.lazy import lazy_imports
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

with lazy_imports(__name__):
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression
    from sqlalchemy.sql.sqltypes import Text


class LogEntryRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "log_entries"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(Text)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint("level", Level, name=f"ck_{cls.__tablename__}__level"),
            Index(
                f"ix_{cls.__tablename__}__content",
                "content",
                postgresql_ops={"content": "gin_trgm_ops"},
                postgresql_using="gin",
            ),
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
    def matches(self, obj: LogEntry) -> bool:
        if not super().matches(obj):
            return False

        if self.level is not None:
            if obj.level not in util.as_sequence(self.level):
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
    def _get_search_content(self, obj: LogEntry) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "level": obj.level,
            "content": obj.content,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        return {
            **super()._get_database_search_content(dialect),
            "level": columns.level,
            "content": columns.content,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.level is not None:
            yield columns.level.in_(util.as_sequence(self.level))
        if self.content_contains is not None:
            yield columns.content.like(
                "%" + util.escape_like_expression(self.content_contains) + "%"
            )
        if self.content_prefix is not None:
            yield columns.content.like(util.escape_like_expression(self.content_prefix) + "%")
        if self.content_suffix is not None:
            yield columns.content.like("%" + util.escape_like_expression(self.content_suffix))


class LogEntryCreate(BaseRecordCreate):
    level: Annotated[Level, CLIOption(Level)]
    content: Annotated[str, CLIOption(str)]


class LogEntry(BaseRecord, LogEntryCreate):
    Order: ClassVar[type[LogEntryOrder]] = LogEntryOrder

    Row: ClassVar[type[LogEntryRow]] = LogEntryRow
    Create: ClassVar[type[LogEntryCreate]] = LogEntryCreate
    Update: ClassVar[type[LogEntryUpdate]] = LogEntryUpdate
    Filter: ClassVar[type[LogEntryFilter]] = LogEntryFilter
    FilterArgs: ClassVar[type[LogEntryFilterArgs]] = LogEntryFilterArgs

    level: Annotated[Level, CLIOption(Level)]
    content: Annotated[str, CLIOption(str)]
