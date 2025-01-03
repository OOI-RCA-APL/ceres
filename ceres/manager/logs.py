from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterable, Mapping, Sequence, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres.address import Address
from ceres.logs import LogEntry, LogEntryFilter, LogEntryFilterArgs, get_logger

with lazy_imports(__name__):
    from ceres.alert import Alert
    from ceres.database import Database
    from ceres.event import Event, LogEvent
    from ceres.level import Level
    from ceres.message import Message
    from ceres.node import Node
    from ceres.particle import Particle
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

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = LogEntry
        _F = LogEntryFilter
        _FA = LogEntryFilterArgs

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


LogInterpolate = Mapping[str, object] | Sequence[object]


class BoundLogManager(LogManager):
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
            logger = get_logger(str(self._node.address))
            logger.log(entry.level.to_int(), entry.content)
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

    def particle(self, level: Level, particle: Particle, /) -> None:
        self.emit(level, "[particle] {data}", particle.address, data=particle.model_dump_json())

    def alert(self, level: Level, alert: Alert, /) -> None:
        self.emit(level, "[alert] {data}", alert.address, data=alert.model_dump_json())
