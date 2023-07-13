import logging
from dataclasses import dataclass, field
from logging import Formatter, Handler, Logger

from rich.logging import RichHandler

from ceres.data import ImmutableDataObject


class LogConfig(ImmutableDataObject):
    level: str = "INFO"
    """
    Set a log level for loggers.
    """


@dataclass(kw_only=True)
class LoggingState:
    config: LogConfig = field(default_factory=LogConfig)
    loggers: dict[str, Logger] = field(default_factory=dict)


__state = LoggingState()


def setup(config: LogConfig | None = None) -> None:
    """
    Set up logging globally.

    :param config: Configuration options to apply.
    """
    if config:
        __state.config = config

    date_format = "%Y-%m-%d %H:%M:%S"

    default_formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s",
        datefmt=date_format,
    )

    def create_handler(formatter: Formatter) -> Handler:
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

    logging.getLogger("uvicorn").disabled = True
    logging.getLogger("uvicorn.error").disabled = True
    logging.getLogger("uvicorn.access").disabled = True


def get(name: str) -> Logger:
    """
    Get a named logger. This can be used to separate logging for different parts of application
    code.

    :param name: The name of the logger. This will be displayed alongside any logged messages.
    """
    logger = logging.getLogger(name)
    if name not in __state.loggers:
        __state.loggers[name] = logger
        setup()

    return logger
