from __future__ import annotations

import os
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from logging import Logger
from typing import Any, Callable, Sequence

import anyio
import yaml
from pydantic import ValidationError
from yaml import YAMLError

from ..config import Config
from ..connection import Connection
from ..errors import (
    ConfigComponentError,
    ConfigDatabaseError,
    ConfigError,
    ConfigParseError,
    ConfigReadError,
    ConfigSchemaError,
    ValidationProblem,
)
from ..path import ConnectionPath
from ..result import Fail, Ok, Result
from .component import load_component
from .database.manager import DatabaseManager


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"


async def load_config(
    config: str | dict[str, Any] | Config,
    *,
    checks: Sequence[ConfigCheckKind] = list(ConfigCheckKind),
    logger: Logger | Callable[[Any], None] = lambda message: None,
) -> Result[Config, list[ConfigError]]:
    def log(message: Any) -> None:
        if not logger:
            return

        if isinstance(logger, Logger):
            logger.info(message)
        else:
            logger(message)

    try:
        if isinstance(config, dict):
            config = Config.parse_obj(config)
            log("Configuration object matches schema.")
        elif isinstance(config, str):
            try:
                path = os.path.realpath(config)
            except Exception:
                return Fail([ConfigReadError()])

            try:
                with open(path, "r") as stream:
                    data = yaml.safe_load(stream)
            except OSError:
                return Fail([ConfigReadError()])
            except YAMLError:
                return Fail([ConfigParseError()])

            config = Config.parse_obj(data)
            config.__path__ = path
            log("Configuration file matches schema.")
    except ValidationError as error:
        return Fail([ConfigSchemaError(problems=ValidationProblem.extract(error))])

    errors: list[ConfigError] = []

    if ConfigCheckKind.DATABASE in checks:
        errors.extend(await _check_database(config, log))
    if ConfigCheckKind.COMPONENTS in checks:
        errors.extend(await _check_components(config, log))

    if errors:
        return Fail(errors)

    return Ok(config)


async def _check_database(
    config: Config,
    log: Callable[[Any], None],
) -> list[ConfigDatabaseError]:
    log("Checking database configuration...")

    errors: list[ConfigDatabaseError] = []

    attempt = 0
    start = datetime.now(timezone.utc)

    while (datetime.now(timezone.utc) - start) < timedelta(seconds=config.database.retry.timeout):
        try:
            database = DatabaseManager.create(config.database)
            async with database.connect():
                log("Connected to database successfully.")
                return []
        except Exception:
            if config.database.retry.attempts is None or attempt < config.database.retry.attempts:
                log("Failed to connect to database, trying again...")
                await database.dispose()
                await anyio.sleep(1)
                attempt += 1
                continue

            log("Failed to connect to database.")
            await database.dispose()
            return [
                ConfigDatabaseError(
                    message="Failed to connect to database.",
                    exception=traceback.format_exc(),
                )
            ]
        finally:
            await database.dispose()

    return errors


async def _check_components(
    config: Config,
    log: Callable[[Any], None],
) -> list[ConfigComponentError]:
    log("Checking component configurations...")

    errors: list[ConfigComponentError] = []

    for unit in config.units:
        for connection in unit.connections:
            path = ConnectionPath.create(unit.name, connection.name)
            log(f"Checking component '{path}'...")
            match load_component(Connection, connection.component, connection.parameters):
                case Fail(error):
                    errors.append(
                        ConfigComponentError(
                            path=path,
                            error=error,
                        )
                    )

    return errors
