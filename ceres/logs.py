from __future__ import annotations

import logging
from datetime import datetime
from typing import (
    ClassVar,
    Final,
    Iterable,
    Literal,
    Sequence,
    TypeAlias,
    override,
)

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Text

from ceres._internal import util
from ceres._internal.database.types import EnumConstraint, EnumMapper
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
from ceres.database.enums import DatabaseType
from ceres.level import Level
from ceres.timing import utc

with lazy_imports(__name__):
    from sqlalchemy.schema import Index, SchemaItem
    from sqlalchemy.sql import SQLColumnExpression


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
                cls.content,
                postgresql_ops={"content": "gin_trgm_ops"},
                postgresql_using="gin",
            ),
        )


LogEntryField: TypeAlias = (
    BaseRecordField
    | Literal[
        "level",
        "content",
    ]
)
LogEntryOrder: TypeAlias = (
    BaseRecordOrder
    | Literal[
        "level",
        "-level",
        "content",
        "-content",
    ]
)


class LogEntryFilterArgs(BaseRecordFilterArgs[LogEntryField, LogEntryOrder], total=False):
    level: Level | Sequence[Level] | None
    content_contains: str | None
    content_prefix: str | None
    content_suffix: str | None


class LogEntryFilter(BaseRecordFilter["LogEntry", LogEntryField, LogEntryOrder]):
    level: Level | Sequence[Level] | None = None
    """Match log entries with the given log level(s)."""
    content_contains: str | Sequence[str] | None = None
    """Match log entries with content containing one or more given substrings."""
    content_prefix: str | Sequence[str] | None = None
    """Filter, keeping only log entries with content that starts with the given string."""
    content_suffix: str | Sequence[str] | None = None
    """Filter, keeping only log entries with content that ends with the given string."""

    @override
    def matches(self, obj: LogEntry, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj, now=now):
            return False

        if self.level is not None:
            if obj.level not in util.as_sequence(self.level):
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
    def _get_row_cls(cls) -> type[LogEntryRow]:
        return LogEntryRow

    @override
    def _get_where(
        self,
        dialect: DatabaseType,
        *,
        now: datetime | None = None,
    ) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect, now=now)
        columns = self._get_row_cls()

        if self.level is not None:
            yield columns.level.in_(util.as_sequence(self.level))
        if self.content_contains is not None:
            yield util.sqlorf(
                columns.content.contains(substring)
                for substring in util.as_sequence(self.content_contains)
            )
        if self.content_prefix is not None:
            yield util.sqlorf(
                columns.content.startswith(prefix)
                for prefix in util.as_sequence(self.content_prefix)
            )
        if self.content_suffix is not None:
            yield util.sqlorf(
                columns.content.endswith(suffix) for suffix in util.as_sequence(self.content_suffix)
            )


class LogEntryCreate(BaseRecordCreate):
    level: Level
    content: str


class LogEntryUpdate(BaseRecordUpdate, total=False):
    level: Level
    content: str


class LogEntry(BaseRecord, LogEntryCreate):
    Row: ClassVar[type[LogEntryRow]] = LogEntryRow
    Create: ClassVar[type[LogEntryCreate]] = LogEntryCreate
    Update: ClassVar[type[LogEntryUpdate]] = LogEntryUpdate
    Filter: ClassVar[type[LogEntryFilter]] = LogEntryFilter
    FilterArgs: ClassVar[type[LogEntryFilterArgs]] = LogEntryFilterArgs
    Field = LogEntryField
    Order = LogEntryOrder


def __create_default_formatter() -> logging.Formatter:
    return logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


DEFAULT_FORMATTER: Final = __create_default_formatter()


def __create_default_handler() -> logging.Handler:
    from rich.logging import RichHandler

    handler = RichHandler(
        show_level=False,
        show_path=False,
        show_time=False,
    )
    handler.setFormatter(DEFAULT_FORMATTER)
    return handler


DEFAULT_HANDLER: Final = __create_default_handler()


__loggers: Final[dict[str, logging.Logger]] = {}


def get_logger(name: str) -> logging.Logger:
    if not isinstance(name, str) or not name:
        raise ValueError("Logger name must be a non-empty string, and cannot be `None`.")

    logger = __loggers.get(name)
    if logger is None:
        logger = logging.getLogger(name)
        logger = __loggers.setdefault(name, logger)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    if DEFAULT_HANDLER not in logger.handlers:
        logger.addHandler(DEFAULT_HANDLER)

    return logger
