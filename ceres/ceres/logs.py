import logging
from enum import Enum
from logging import Logger
from typing import Callable, Protocol, Sequence, TypeAlias
from uuid import UUID, uuid4

from pydantic import Field

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject
from ceres.internal import logs
from ceres.level import Level
from ceres.timing import utc


class LogKind(str, Enum):
    ENGINE = "engine"
    SERVER = "server"
    COMPONENT = "component"


class LogEntry(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    kind: LogKind
    source: Address | None = None
    timestamp: DateTime = Field(default_factory=utc)
    level: Level
    content: str


class LogHandler(Protocol):
    def handle(self, entry: LogEntry) -> object:
        ...


LogHandlerFunction: TypeAlias = Callable[[LogEntry], object]


class Log:
    def __init__(
        self,
        kind: LogKind,
        source: Address | Callable[[], Address] | None = None,
    ) -> None:
        self.__kind = kind
        self.__source = source
        self.__handlers: list[LogHandler | LogHandlerFunction] = []

    @property
    def kind(self) -> LogKind:
        return self.__kind

    @property
    def source(self) -> Address | None:
        if callable(self.__source):
            return self.__source()

        return self.__source

    @property
    def handlers(self) -> Sequence[LogHandler | LogHandlerFunction]:
        return list(self.__handlers)

    @property
    def base(self) -> Logger:
        name = f"{self.__kind.value}:{self.source}" if self.source else self.__kind.value
        return logs.get(name)

    def write(self, level: Level, content: object, *args: object, **kwargs: object) -> LogEntry:
        if not isinstance(content, str):
            content = str(content)
        if args or kwargs:
            content = content.format(*args, **kwargs)

        self.base.log(logging.getLevelName(level.value.upper()), content)

        entry = LogEntry(
            kind=self.__kind,
            source=self.source,
            level=level,
            content=content,
        )

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
