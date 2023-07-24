import logging
from logging import Logger
from typing import TYPE_CHECKING, Callable, Protocol, Sequence, TypeAlias
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject
from ceres.internal import logs
from ceres.level import Level
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.object import Object
else:
    Object = object


class LogEntry(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    address: Address
    timestamp: DateTime = Field(default_factory=utc)
    level: Level
    content: str


class LogHandler(Protocol):
    def handle(self, entry: LogEntry) -> object:
        ...


LogHandlerFunction: TypeAlias = Callable[[LogEntry], object]


class Log:
    def __init__(self, target: "Object | Address | Callable[[], Address]", /) -> None:
        self.__target = target
        self.__handlers: list[LogHandler | LogHandlerFunction] = []

    @property
    def address(self) -> Address:
        from ceres.object import Object

        if isinstance(self.__target, Object):
            return self.__target.address
        if callable(self.__target):
            return self.__target()

        return self.__target

    @property
    def handlers(self) -> Sequence[LogHandler | LogHandlerFunction]:
        return list(self.__handlers)

    @property
    def base(self) -> Logger:
        return logs.get(self.address)

    def write(self, level: Level, content: object, *args: object, **kwargs: object) -> LogEntry:
        from ceres.object import Object

        if not isinstance(content, str):
            content = str(content)
        if args or kwargs:
            content = content.format(*args, **kwargs)

        self.base.log(logging.getLevelName(level.value.upper()), content)

        entry = LogEntry(
            address=self.address,
            level=level,
            content=content,
        )

        if isinstance(self.__target, Object):
            from ceres.events import LogEvent

            self.__target.emit(LogEvent, entry=entry)

        for handler in self.__handlers:
            if callable(handler):
                handler(entry)
            else:
                handler.handle(entry)

        return entry

    def debug(self, content: object, *args: object, **kwargs: object) -> None:
        self.write(Level.DEBUG, content, *args, **kwargs)

    def info(self, content: object, *args: object, **kwargs: object) -> None:
        self.write(Level.INFO, content, *args, **kwargs)

    def warning(self, content: object, *args: object, **kwargs: object) -> None:
        self.write(Level.WARNING, content, *args, **kwargs)

    def error(self, content: object, *args: object, **kwargs: object) -> None:
        self.write(Level.ERROR, content, *args, **kwargs)

    def critical(self, content: object, *args: object, **kwargs: object) -> None:
        self.write(Level.CRITICAL, content, *args, **kwargs)

    def add_handler(self, handler: LogHandler | LogHandlerFunction) -> None:
        if handler not in self.__handlers:
            self.__handlers.append(handler)

    def remove_handler(self, handler: LogHandler | LogHandlerFunction) -> None:
        try:
            self.__handlers.remove(handler)
        except ValueError:
            pass
