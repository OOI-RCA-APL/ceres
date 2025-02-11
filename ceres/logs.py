from __future__ import annotations

import logging
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Final,
    Iterable,
    Literal,
    TypeAlias,
    Unpack,
    override,
)
from uuid import UUID

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, SchemaItem
from sqlalchemy.sql import SQLColumnExpression

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
from ceres.address import Address
from ceres.data import MaybeSequence
from ceres.database import DatabaseType
from ceres.level import Level
from ceres.stream import Stream
from ceres.timing import utc


class LogEntryRow(BaseRecordRow, kw_only=True):
    __tablename__: ClassVar[str] = "logs"

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
        "level:asc",
        "level:desc",
        "content",
        "content:asc",
        "content:desc",
    ]
)


class LogEntryFilterArgs(BaseRecordFilterArgs[LogEntryField, LogEntryOrder], total=False):
    level: MaybeSequence[Level] | None
    content: MaybeSequence[str] | None
    contains: MaybeSequence[str] | None
    prefix: MaybeSequence[str] | None
    suffix: MaybeSequence[str] | None


class LogEntryFilter(BaseRecordFilter["LogEntry", LogEntryField, LogEntryOrder]):
    level: MaybeSequence[Level] | None = None
    """Filter by `level` being equal to one or more given levels."""
    content: MaybeSequence[str] | None = None
    """Filter by `content` being equal to one or more given strings."""
    contains: MaybeSequence[str] | None = None
    """Filter by `content` containing one or more given substrings."""
    prefix: MaybeSequence[str] | None = None
    """Filter by `content` starting with one or more given prefixes."""
    suffix: MaybeSequence[str] | None = None
    """Filter by `content` ending with one or more given suffixes."""

    @override
    def matches(self, obj: LogEntry, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super().matches(obj, now=now):
            return False

        if not util.match_value(obj.level, self.level):
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
            yield util.sql_match_value(columns.level, self.level)
        if self.content is not None:
            yield util.sql_match_value(columns.content, self.content)
        if self.contains is not None:
            yield util.sql_match_string(columns.content, self.contains, MatchMode.CONTAINS)
        if self.prefix is not None:
            yield util.sql_match_string(columns.content, self.prefix, MatchMode.PREFIX)
        if self.suffix is not None:
            yield util.sql_match_string(columns.content, self.suffix, MatchMode.SUFFIX)


class LogEntryCreate(BaseRecordCreate):
    level: Level
    content: str


class LogEntryUpdate(BaseRecordUpdate, total=False):
    level: Level
    content: str


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


if TYPE_CHECKING:
    from ceres.alert import Alert
    from ceres.event import Event
    from ceres.level import Level
    from ceres.message import Message
    from ceres.particle import Particle


class _BaseLogEntryQuery(
    BaseEntityQuery[
        "LogEntry",
        LogEntryFilter,
        LogEntryUpdate,
        "LogEntryQuery",
    ]
):
    @override
    def _get_query_class(self) -> type[LogEntryQuery]:
        return LogEntryQuery

    @override
    def where(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntryQuery:
        return super().where(filter, **kwargs)


class LogEntryQuery(
    EntityQuery[
        "LogEntry",
        LogEntryFilter,
        LogEntryUpdate,
    ],
    _BaseLogEntryQuery,
):
    pass


class LogManager(
    BaseEntityManager[
        "LogEntry",
        LogEntryRow,
        LogEntryCreate,
        LogEntryUpdate,
        LogEntryFilter,
        LogEntryFilterArgs,
    ],
    _BaseLogEntryQuery,
):
    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, LogEntry)

    async def get(self, id: UUID, /) -> LogEntry | None:
        return await self.where(id=id).first()


class BoundLogManager(LogManager, BaseNodeManager):
    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    def follow(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> Stream[LogEntry]:
        from ceres.event import LogEvent

        filter = self._get_resolved_filter_args(filter, kwargs)
        return (
            self.__node__.events.follow()
            .every(LogEvent)
            .map(lambda event: event.entry)
            .filter(filter.matches)
        )

    def write(self, entry: LogEntry, /) -> None:
        from ceres.event import LogEvent

        config = self.__node__.get_resolved_logging_config()
        if entry.level >= config.level:
            logger = get_logger(str(self.__node__.address))
            logger.log(entry.level.to_int(), entry.content)
            self.__node__.store(entry)

        self.__node__.events.emit(LogEvent, entry=entry)

    def emit(
        self,
        level: Level,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        if not isinstance(content, str):
            content = str(content)

        if kwargs:
            content = content.format(**kwargs)

        entry = LogEntry(
            address=address or self.__node__.address,
            level=level,
            content=content,
        )

        self.write(entry)
        return entry

    def debug(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        return self.emit(Level.DEBUG, content, address, **kwargs)

    def info(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        return self.emit(Level.INFO, content, address, **kwargs)

    def warning(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        return self.emit(Level.WARNING, content, address, **kwargs)

    def error(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        return self.emit(Level.ERROR, content, address, **kwargs)

    def critical(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        return self.emit(Level.CRITICAL, content, address, **kwargs)

    def event(self, level: Level, event: Event, /) -> None:
        self.emit(level, "[event] {data}", event.address, data=event.model_dump_json())

    def message(self, level: Level, message: Message, /) -> None:
        self.emit(level, "[message] {data}", message.address, data=message.model_dump_json())

    def particle(self, level: Level, particle: Particle, /) -> None:
        self.emit(level, "[particle] {data}", particle.address, data=particle.model_dump_json())

    def alert(self, level: Level, alert: Alert, /) -> None:
        self.emit(level, "[alert] {data}", alert.address, data=alert.model_dump_json())


class LogEntry(BaseRecord, LogEntryCreate):
    Manager: ClassVar[type[LogManager]] = LogManager
    BoundManager: ClassVar[type[BoundLogManager]] = BoundLogManager
    Row: ClassVar[type[LogEntryRow]] = LogEntryRow
    Create: ClassVar[type[LogEntryCreate]] = LogEntryCreate
    Update: ClassVar[type[LogEntryUpdate]] = LogEntryUpdate
    Filter: ClassVar[type[LogEntryFilter]] = LogEntryFilter
    FilterArgs: ClassVar[type[LogEntryFilterArgs]] = LogEntryFilterArgs
    Field = LogEntryField
    Order = LogEntryOrder
    Level: ClassVar[type[Level]] = Level
