from __future__ import annotations

import logging
from dataclasses import dataclass, field
from logging import Formatter, Handler, Logger

import uvicorn.logging
from rich.logging import RichHandler


@dataclass(kw_only=True, frozen=True)
class LogConfig:
    """
    Common logging configuration.
    """

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
        "[%(asctime)s.%(msecs)03d] [%(process)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt=date_format,
    )
    server_formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(process)s] [%(levelname)s] [server] %(message)s",
        datefmt=date_format,
    )
    access_formatter = uvicorn.logging.AccessFormatter(
        "[%(asctime)s.%(msecs)03d] [%(process)s] [%(levelname)s] [server] [%(client_addr)s] - %(request_line)s - %(status_code)s",
        datefmt=date_format,
        use_colors=False,
    )

    def create_handler(formatter: Formatter) -> RichHandler:
        handler = RichHandler(
            show_level=False,
            show_path=False,
            show_time=False,
        )
        handler.setFormatter(formatter)
        return handler

    default_handler = create_handler(default_formatter)
    server_handler = create_handler(server_formatter)
    access_handler = create_handler(access_formatter)

    def setup_logger(name: str, handler: Handler) -> None:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(__state.config.level)
        logger.propagate = False

    for name in __state.loggers.keys():
        setup_logger(name, default_handler)

    setup_logger("uvicorn", server_handler)
    setup_logger("uvicorn.access", access_handler)


def main() -> Logger:
    """
    Get the main logger. This should be used in mainline application code.
    """
    return get("uvicorn")


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
