from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Sequence, Unpack

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres.address import Address
from ceres.logs import LogEntry, LogEntryFilter, LogEntryFilterArgs

with lazy_imports(__name__):
    from ceres.alert import Alert
    from ceres.database.database import Database
    from ceres.event import Event, LogEvent
    from ceres.level import Level
    from ceres.message import Message
    from ceres.node import Node
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
    def __init__(self, source: Database | Node) -> None:
        super().__init__(source, LogEntry)


LogInterpolate = Mapping[str, object] | Sequence[object]


class LiveLogManager(LogManager):
    if TYPE_CHECKING:
        _node: Node  # type: ignore

    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, entry: LogEntry, /) -> None:
        return self._node.store(entry)

    def follow(
        self,
        filter: LogEntryFilter | None = None,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> Stream[LogEntry]:
        filter = self._apply_default_filter(filter, kwargs)
        return (
            self._node.events.follow()
            .every(LogEvent)
            .map(lambda event: event.entry)
            .filter(filter.matches)
        )

    def write(self, entry: LogEntry, /) -> None:
        from ceres.event import LogEvent

        config = self._node.get_resolved_logging_config()
        if entry.level >= config.level:
            logger = _get_logger(self._node.address)
            logger.log(logging.getLevelName(entry.level.value.upper()), entry.content)
            self._node.log.store(entry)

        self._node.events.emit(LogEvent, entry=entry)

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
            address=address or self._node.address,
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

    def alert(self, level: Level, alert: Alert, /) -> None:
        self.emit(level, "[alert] {data}", alert.address, data=alert.model_dump_json())


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
