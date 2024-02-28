import logging
from dataclasses import dataclass, field
from datetime import datetime
from logging import Formatter, Handler, Logger
from typing import TYPE_CHECKING, Annotated, Callable, Protocol, Sequence, TypeAlias
from uuid import UUID, uuid4

from pydantic import Field
from typing_extensions import Self, TypedDict

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject
from ceres.internal.cli.plumbing import CLIOption
from ceres.level import Level
from ceres.timing import utc

if TYPE_CHECKING:
    from ceres.object import Object
else:
    Object = object


class LogEntry(ImmutableDataObject):
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    address: Annotated[Address, CLIOption(str)]
    timestamp: Annotated[DateTime, CLIOption(datetime)] = Field(default_factory=utc)
    level: Annotated[Level, CLIOption(Level)]
    content: Annotated[str, CLIOption(str)]


class LogEntryUpdate(TypedDict, total=False):
    address: Address
    timestamp: DateTime
    level: Level
    content: str


class LogHandler(Protocol):
    def handle(self, entry: LogEntry) -> object: ...


LogHandlerFunction: TypeAlias = Callable[[LogEntry], object]


class Log:
    __slots__ = (
        "__weakref__",
        "__target",
        "__emitter",
        "__handlers",
    )

    def __init__(
        self,
        target: "Object | Address | Callable[[], Address]",
        emitter: "Object | None" = None,
    ) -> None:
        self.__target = target
        self.__emitter = emitter
        self.__handlers: tuple[LogHandler | LogHandlerFunction, ...] = ()

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
        return self.__handlers

    @property
    def base(self) -> Logger:
        return _get_logger(self.address)

    def write(self, level: Level, content: object, *args: object, **kwargs: object) -> LogEntry:
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

        if self.__emitter is not None:
            from ceres.events import LogEvent

            self.__emitter.emit(LogEvent, entry=entry)

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

    def derive(self, target: "Object | Address | Callable[[], Address]", /) -> Self:
        derived = type(self)(target, self.__emitter)
        derived.__handlers = self.__handlers
        return derived

    def add_handler(self, handler: LogHandler | LogHandlerFunction) -> None:
        if handler in self.__handlers:
            return

        self.__handlers = tuple([*self.__handlers, handler])

    def remove_handler(self, handler: LogHandler | LogHandlerFunction) -> None:
        if handler not in self.__handlers:
            return

        try:
            self.__handlers = tuple(
                [current for current in self.__handlers if current is not handler]
            )
        except ValueError:
            pass


class LogConfig(ImmutableDataObject):
    level: str = "INFO"
    """
    Set a log level for loggers.
    """


@dataclass(kw_only=True)
class __LoggingState:
    config: LogConfig = field(default_factory=LogConfig)
    loggers: dict[str, Logger] = field(default_factory=dict)


__state = __LoggingState()


def __setup_logging() -> None:
    date_format = "%Y-%m-%d %H:%M:%S"

    default_formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt=date_format,
    )

    def create_handler(formatter: Formatter) -> Handler:
        from rich.logging import RichHandler

        handler = RichHandler(
            show_level=False,
            show_path=False,
            show_time=False,
        )
        handler.setFormatter(formatter)
        return handler

    default_handler = create_handler(default_formatter)

    def setup_logger(name: str, handler: Handler) -> None:
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.close()
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(__state.config.level)
        logger.propagate = False

    for name in list(__state.loggers.keys()):
        setup_logger(name, default_handler)


def _get_logger(name: str) -> Logger:
    logger = logging.getLogger(name)
    if name not in __state.loggers:
        __state.loggers[name] = logger
        __setup_logging()

    return logger
