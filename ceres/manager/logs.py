import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from typing_extensions import Unpack

from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.typedecs import __Database__, __Node__
from ceres.event import LogEvent
from ceres.level import Level
from ceres.logs import LogEntry, LogEntryFilter, LogEntryFilterArgs
from ceres.stream import Stream


class LogManager(
    BaseEntityManager[
        LogEntry,
        LogEntry.Row,
        LogEntry.Create,
        LogEntry.Update,
        LogEntry.Filter,
        LogEntry.FilterArgs,
    ]
):
    def __init__(self, source: __Database__ | __Node__) -> None:
        super().__init__(source, LogEntry)


class LiveLogManager(LogManager):
    if TYPE_CHECKING:
        _node: __Node__  # type: ignore

    def __init__(self, source: __Node__) -> None:
        super().__init__(source)

    def store(self, entry: LogEntry, /) -> None:
        return self._node.store(entry)

    def follow(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> Stream[LogEntry]:
        assert self._node is not None
        filter = self._apply_default_filter(filter, kwargs)
        return (
            self._node.events.follow()
            .every(LogEvent)
            .map(lambda event: event.entry)
            .filter(filter.matches)
        )

    def emit(self, level: Level, content: object, *args: object, **kwargs: object) -> LogEntry:
        if not isinstance(content, str):
            content = str(content)
        if args or kwargs:
            content = content.format(*args, **kwargs)

        config = self._node.get_resolved_logging_config()
        if level >= config.level:
            logger = _get_logger(self._node.address)
            logger.log(logging.getLevelName(level.value.upper()), content)

        entry = LogEntry(
            address=self._node.address,
            level=level,
            content=content,
        )

        from ceres.event import LogEvent

        self._node.events.emit(LogEvent, entry=entry)

        if level >= config.persist.level:
            self._node.store(entry)

        return entry

    def debug(self, content: object, *args: object, **kwargs: object) -> LogEntry:
        return self.emit(Level.DEBUG, content, *args, **kwargs)

    def info(self, content: object, *args: object, **kwargs: object) -> LogEntry:
        return self.emit(Level.INFO, content, *args, **kwargs)

    def warning(self, content: object, *args: object, **kwargs: object) -> LogEntry:
        return self.emit(Level.WARNING, content, *args, **kwargs)

    def error(self, content: object, *args: object, **kwargs: object) -> LogEntry:
        return self.emit(Level.ERROR, content, *args, **kwargs)

    def critical(self, content: object, *args: object, **kwargs: object) -> LogEntry:
        return self.emit(Level.CRITICAL, content, *args, **kwargs)


@dataclass(kw_only=True)
class _LoggingState:
    loggers: dict[str, logging.Logger] = field(default_factory=dict)


_logging_state = _LoggingState()


def _setup_logging() -> None:
    date_format = "%Y-%m-%d %H:%M:%S"

    default_formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt=date_format,
    )

    def create_handler(formatter: logging.Formatter) -> logging.Handler:
        from rich.logging import RichHandler

        handler = RichHandler(
            show_level=False,
            show_path=False,
            show_time=False,
        )
        handler.setFormatter(formatter)
        return handler

    default_handler = create_handler(default_formatter)

    def setup_logger(name: str, handler: logging.Handler) -> None:
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.close()
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    for name in list(_logging_state.loggers.keys()):
        setup_logger(name, default_handler)


def _get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if name not in _logging_state.loggers:
        _logging_state.loggers[name] = logger
        _setup_logging()

    return logger
