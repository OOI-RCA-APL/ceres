import logging
from collections.abc import Callable, Iterable
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Final,
    Literal,
    TypeAlias,
    Unpack,
    override,
)

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.database.types import EnumConstraint, EnumMapper, TextMapper
from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityOutputChannel,
    EntityQuery,
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
from ceres.data import MaybeSequence, to_json
from ceres.level import Level
from ceres.timing import utc

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.address import Address
    from ceres.database import DatabaseType

__all__ = [
    "LogEntry",
    "LogEntryField",
    "LogEntryOrder",
    "LogEntryFilterArgs",
    "LogEntryFilter",
    "LogEntryCreate",
    "LogEntryUpdate",
    "LogManager",
    "BoundLogManager",
]


class LogEntryRow(BaseRecordRow, kw_only=True):
    """SQLAlchemy row type backing the `LogEntry` entity."""

    __tablename__: ClassVar[str] = "logs"

    level: Mapped[Level] = mapped_column(EnumMapper(Level))
    content: Mapped[str] = mapped_column(TextMapper())

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            EnumConstraint(cls.level, Level, name=f"ck_{cls.__tablename__}__level"),
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
"""Field names selectable in `LogEntry` queries."""

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
"""Ordering keys accepted by `LogEntry` queries."""


class LogEntryFilterArgs(BaseRecordFilterArgs[LogEntryField, LogEntryOrder], total=False):
    """Keyword-argument form of `LogEntryFilter` for ergonomic call sites."""

    level: MaybeSequence[Level] | None
    min_level: Level | None
    max_level: Level | None
    content: MaybeSequence[str] | None
    contains: MaybeSequence[str] | None
    prefix: MaybeSequence[str] | None
    suffix: MaybeSequence[str] | None


class LogEntryFilter(BaseRecordFilter["LogEntry", LogEntryField, LogEntryOrder]):
    """Filter for selecting `LogEntry` records by level or content."""

    level: MaybeSequence[Level] | None = None
    """Filter by `level` being equal to one or more given levels."""
    min_level: Level | None = None
    """Filter by `level` being greater than or equal to the given level value."""
    max_level: Level | None = None
    """Filter by `level` being less than or equal to the given level value."""
    content: MaybeSequence[str] | None = None
    """Filter by `content` being equal to one or more given strings."""
    contains: MaybeSequence[str] | None = None
    """Filter by `content` containing one or more given substrings."""
    prefix: MaybeSequence[str] | None = None
    """Filter by `content` starting with one or more given prefixes."""
    suffix: MaybeSequence[str] | None = None
    """Filter by `content` ending with one or more given suffixes."""

    @override
    def _matches(self, obj: LogEntry, *, now: datetime | None = None) -> bool:
        now = utc(now)
        if not super()._matches(obj, now=now):
            return False

        if not self._match_value(obj.level, self.level):
            return False

        if self.min_level is not None:
            if obj.level < self.min_level:
                return False
        if self.max_level is not None:
            if obj.level > self.max_level:
                return False

        if not self._match_value(obj.content, self.content):
            return False
        if not self._match_string_contains(obj.content, self.contains):
            return False
        if not self._match_string_prefix(obj.content, self.prefix):
            return False
        if not self._match_string_suffix(obj.content, self.suffix):
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
            yield self._sql_match_value(columns.level, self.level)
        if self.min_level is not None:
            yield columns.level.in_(current for current in Level if current >= self.min_level)
        if self.max_level is not None:
            yield columns.level.in_(current for current in Level if current <= self.max_level)

        if self.content is not None:
            yield self._sql_match_value(columns.content, self.content)
        if self.contains is not None:
            yield self._sql_match_string_contains(columns.content, self.contains)
        if self.prefix is not None:
            yield self._sql_match_string_prefix(columns.content, self.prefix)
        if self.suffix is not None:
            yield self._sql_match_string_suffix(columns.content, self.suffix)


class LogEntryCreate(BaseRecordCreate, slots=True):
    """Payload for creating a new `LogEntry` record."""

    level: Level
    """Severity level of the log entry."""
    content: str
    """Rendered textual content of the log entry."""


class LogEntryUpdate(BaseRecordUpdate, total=False):
    """Partial update for an existing `LogEntry` record."""

    level: Level
    content: str


def __create_default_formatter() -> logging.Formatter:
    return logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


DEFAULT_FORMATTER: Final = __create_default_formatter()
"""Shared `logging.Formatter` applied to loggers returned from `get_logger()`."""


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
"""Shared rich-backed `logging.Handler` attached to loggers returned from `get_logger()`."""


__loggers: Final[dict[str, logging.Logger]] = {}


def get_logger(name: str) -> logging.Logger:
    """Return the cached logger for `name`, creating and configuring it if needed.

    The returned logger is configured with `DEFAULT_HANDLER`, set to debug level, and has
    propagation disabled so its records do not climb to the root logger.

    Args:
        name: Non-empty string identifying the logger.

    Returns:
        The cached `logging.Logger` instance associated with `name`.

    Raises:
        ValueError: If `name` is not a non-empty string.
    """
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
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[LogEntryQuery]:
        return LogEntryQuery

    @override
    def where(  # type: ignore
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
    """Query builder for `LogEntry` records."""

    __slots__ = ()


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
    """Database-bound manager for `LogEntry` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, LogEntry)

    async def get(self, id: UUID, /) -> LogEntry | None:
        """Fetch a single log entry by its identifier.

        Args:
            id: UUID of the log entry to fetch.

        Returns:
            The matching log entry, or `None` if no entry with that id exists.
        """
        return await self.where(id=id).first()


class BoundLogManager(LogManager, BaseNodeManager):
    """Component-bound log manager that exposes the live log stream and emit helpers.

    Use `emit()` (or the level-named shortcuts like `info()` and `error()`) to write a log entry
    from a component or engine. Each entry is stored, forwarded to the Python logger for stderr
    output, and broadcast as a `LogEvent`, subject to the node's logging config.
    """

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)

    @property
    def stream(self) -> LogEntryOutputChannel:
        """Return an output channel that yields log entries from `LogEvent` events."""
        from ceres.event import LogEvent

        return LogEntryOutputChannel(
            self.__node__.events.stream.every(LogEvent)
            .map(lambda event: event.entry)
            .where(lambda entry: self._get_resolved_filter().matches(entry))
        )

    def write(self, entry: LogEntry, /) -> None:
        """Dispatch a pre-built log entry through the configured output, storage, and event stream.

        The entry is forwarded to the Python logger when its level meets the `output` threshold,
        stored when its level meets the `store` threshold, and always emitted as a `LogEvent`.

        Args:
            entry: Pre-constructed log entry to dispatch.
        """
        from ceres.event import LogEvent

        config = self.__node__.get_resolved_logging_config()

        if config is not None:
            # If the log entry's level reaches the `output` threshold, write to the Python logger,
            # and subsequently stderr. The `output` threshold is `Level.INFO` by default.
            if entry.level >= config.output:
                logger = get_logger(str(self.__node__.address))
                logger.log(entry.level.to_int(), entry.content)

            # If the log entry's level reaches the `store` threshold, write the log entry to the
            # project database. The `store` threshold is `Level.DEBUG` by default, meaning all log
            # entries are persisted.
            if entry.level >= config.store:
                self.__node__.store(entry)

        # Log events are always emitted.
        self.__node__.events.emit(LogEvent, entry=entry)

    def emit(
        self,
        level: Level,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        """Construct a log entry and dispatch it through `write()`.

        Non-string `content` values are coerced with `str()`. When `kwargs` are provided, the
        content is formatted with them via `str.format()`.

        Args:
            level: Severity level of the entry.
            content: Message body, formatted with `kwargs` when any are provided.
            address: Source address for the entry, defaults to the bound node's address.
            **kwargs: Format arguments substituted into `content`.

        Returns:
            The constructed and dispatched `LogEntry` instance.
        """
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
        """Emit a log entry at `Level.DEBUG`. See `emit()` for details."""
        return self.emit(Level.DEBUG, content, address, **kwargs)

    def info(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        """Emit a log entry at `Level.INFO`. See `emit()` for details."""
        return self.emit(Level.INFO, content, address, **kwargs)

    def warning(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        """Emit a log entry at `Level.WARNING`. See `emit()` for details."""
        return self.emit(Level.WARNING, content, address, **kwargs)

    def error(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        """Emit a log entry at `Level.ERROR`. See `emit()` for details."""
        return self.emit(Level.ERROR, content, address, **kwargs)

    def critical(
        self,
        content: object,
        address: Address | None = None,
        /,
        **kwargs: object,
    ) -> LogEntry:
        """Emit a log entry at `Level.CRITICAL`. See `emit()` for details."""
        return self.emit(Level.CRITICAL, content, address, **kwargs)

    def event(self, event: Event, level: Level | None = None, /) -> None:
        """Log an `Event` as a formatted `[event]` entry, defaulting to the event's own level."""
        if level is None:
            level = event.level

        self.emit(level, "[event] {data}", event.address, data=to_json(event))

    def message(self, message: Message, level: Level | None = None, /) -> None:
        """Log a `Message` as a formatted `[message]` entry, defaulting to `Level.INFO`."""
        if level is None:
            level = Level.INFO

        self.emit(level, "[message] {data}", message.address, data=to_json(message))

    def particle(self, particle: Particle, level: Level | None = None, /) -> None:
        """Log a `Particle` as a formatted `[particle]` entry, defaulting to `Level.INFO`."""
        if level is None:
            level = Level.INFO

        self.emit(level, "[particle] {data}", particle.address, data=to_json(particle))

    def alert(self, alert: Alert, level: Level | None = None, /) -> None:
        """Log an `Alert` as a formatted `[alert]` entry, defaulting to the alert's own level."""
        if level is None:
            level = alert.level

        self.emit(level, "[alert] {data}", alert.address, data=to_json(alert))


class LogEntryOutputChannel(
    EntityOutputChannel[
        "LogEntry",
        LogEntryFilter,
        LogEntryFilterArgs,
    ]
):
    """Output channel for streaming `LogEntry` instances with filtering helpers."""

    __slots__ = ()

    @override
    def _get_filter_class(self) -> type[LogEntryFilter]:
        return LogEntryFilter

    @override
    def where(  # type: ignore
        self,
        filter: LogEntryFilter | Callable[[LogEntry], bool] | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntryOutputChannel:
        """Return a new channel that only yields log entries matching the given filter.

        Args:
            filter: A `LogEntryFilter`, a callable predicate, or `None` to filter by keyword
                arguments only.
            **kwargs: Additional filter fields forwarded to `LogEntryFilter`.

        Returns:
            A filtered `LogEntryOutputChannel`.
        """
        return super().where(filter, **kwargs)


class LogEntry(
    BaseRecord,
    LogEntryCreate,
    ConcreteEntity[LogEntryRow],
    slots=True,
):
    """Text-content log line emitted by a component or engine and persisted as a record.

    Log entries are the primary human-readable trail of activity in the system. Each entry
    carries a severity `level` and rendered `content`, and is produced via `BoundLogManager`
    on a running node.
    """

    Manager = LogManager
    BoundManager = BoundLogManager
    Create = LogEntryCreate
    Update = LogEntryUpdate
    Filter = LogEntryFilter
    FilterArgs = LogEntryFilterArgs
    Field = LogEntryField
    Order = LogEntryOrder
    Level = Level

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming(
        singular="log entry",
        plural="log entries",
        container="logs",
    )
