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
)
from ..path import ConnectionPath
from ..result import Fail, Ok, Result
from ..validation import ValidationProblem
from .component import load_component
from .database.manager import DatabaseManager


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"


class Configurator:
    def __init__(
        self,
        *,
        checks: Sequence[ConfigCheckKind] = list(ConfigCheckKind),
        logger: Logger | Callable[[Any], None] | None = None,
    ) -> None:
        self._checks = list(checks)
        self._logger = logger

    def _log(self, message: Any) -> None:
        if not self._logger:
            return

        if isinstance(self._logger, Logger):
            self._logger.info(message)
        else:
            self._logger(message)

    async def load(
        self,
        config: str | dict[str, Any] | Config,
        checks: Sequence[ConfigCheckKind] | None = None,
    ) -> Result[Config, list[ConfigError]]:
        if checks is None:
            checks = self._checks

        try:
            if isinstance(config, dict):
                config = Config.parse_obj(config)
                self._log("Configuration object matches schema.")
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
                self._log("Configuration file matches schema.")
        except ValidationError as error:
            return Fail([ConfigSchemaError(problems=ValidationProblem.extract(error))])

        errors: list[ConfigError] = []

        if ConfigCheckKind.DATABASE in checks:
            errors.extend(await self._check_database(config))
        if ConfigCheckKind.COMPONENTS in checks:
            errors.extend(await self._check_components(config))

        if errors:
            return Fail(errors)

        return Ok(config)

    async def _check_database(self, config: Config) -> list[ConfigDatabaseError]:
        self._log("Checking database configuration...")

        errors: list[ConfigDatabaseError] = []

        attempt = 0
        start = datetime.now(timezone.utc)

        while (datetime.now(timezone.utc) - start) < timedelta(
            seconds=config.database.retry.timeout
        ):
            try:
                database = DatabaseManager.create(config.database)
                async with database.connect():
                    self._log("Connected to database successfully.")
                    return []
            except Exception:
                if (
                    config.database.retry.attempts is None
                    or attempt < config.database.retry.attempts
                ):
                    self._log("Failed to connect to database, trying again...")
                    await database.dispose()
                    await anyio.sleep(1)
                    attempt += 1
                    continue

                self._log("Failed to connect to database.")
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

    async def _check_components(self, config: Config) -> list[ConfigComponentError]:
        self._log("Checking component configurations...")

        errors: list[ConfigComponentError] = []

        for unit in config.units:
            for connection in unit.connections:
                path = ConnectionPath.create(unit.name, connection.name)
                self._log(f"Checking component '{path}'...")
                match load_component(Connection, connection.component, connection.parameters):
                    case Fail(error):
                        errors.append(
                            ConfigComponentError(
                                path=path,
                                error=error,
                            )
                        )

        return errors
