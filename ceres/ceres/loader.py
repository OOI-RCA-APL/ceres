from __future__ import annotations

import os
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from logging import Logger
from typing import Any, Callable, Literal, Sequence

import anyio
import yaml
from pydantic import BaseModel, ValidationError
from yaml import YAMLError

from .component import ComponentLoadError
from .config import EngineConfig
from .connection import Connection
from .internal.database.manager import DatabaseManager
from .path import ComponentPath, ConnectionPath
from .result import Fail, Ok, Result
from .validation import ValidationProblem


class EngineConfigErrorKind(str, Enum):
    READ_ERROR = "read-error"
    PARSE_ERROR = "parse-error"
    SCHEMA_ERROR = "schema-error"
    DATABASE_ERROR = "database-error"
    COMPONENT_LOAD_ERROR = "component-load-error"


class EngineConfigReadError(BaseModel):
    kind: Literal[EngineConfigErrorKind.READ_ERROR] = EngineConfigErrorKind.READ_ERROR


class EngineConfigParseError(BaseModel):
    kind: Literal[EngineConfigErrorKind.PARSE_ERROR] = EngineConfigErrorKind.PARSE_ERROR


class EngineConfigSchemaError(BaseModel):
    kind: Literal[EngineConfigErrorKind.SCHEMA_ERROR] = EngineConfigErrorKind.SCHEMA_ERROR
    problems: list[ValidationProblem] = []


class EngineConfigDatabaseError(BaseModel):
    kind: Literal[EngineConfigErrorKind.DATABASE_ERROR] = EngineConfigErrorKind.DATABASE_ERROR
    message: str
    exception: str


class EngineConfigComponentLoadError(BaseModel):
    kind: Literal[
        EngineConfigErrorKind.COMPONENT_LOAD_ERROR
    ] = EngineConfigErrorKind.COMPONENT_LOAD_ERROR
    path: ComponentPath
    inner: ComponentLoadError


EngineConfigError = (
    EngineConfigReadError
    | EngineConfigParseError
    | EngineConfigSchemaError
    | EngineConfigDatabaseError
    | EngineConfigComponentLoadError
)


class EngineConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"


class EngineConfigLoader:
    def __init__(
        self,
        *,
        checks: Sequence[EngineConfigCheckKind] = list(EngineConfigCheckKind),
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
        config: str | dict[str, Any] | EngineConfig,
        checks: Sequence[EngineConfigCheckKind] | None = None,
    ) -> Result[EngineConfig, list[EngineConfigError]]:
        if checks is None:
            checks = self._checks

        try:
            if isinstance(config, dict):
                config = EngineConfig.parse_obj(config)
                self._log("Configuration object matches schema.")
            elif isinstance(config, str):
                try:
                    path = os.path.realpath(config)
                except Exception:
                    return Fail([EngineConfigReadError()])

                try:
                    with open(path, "r") as stream:
                        data = yaml.safe_load(stream)
                except OSError:
                    return Fail([EngineConfigReadError()])
                except YAMLError:
                    return Fail([EngineConfigParseError()])

                config = EngineConfig.parse_obj(data)
                config.__path__ = path
                self._log("Configuration file matches schema.")
        except ValidationError as error:
            return Fail([EngineConfigSchemaError(problems=ValidationProblem.extract(error))])

        errors: list[EngineConfigError] = []

        if EngineConfigCheckKind.DATABASE in checks:
            errors.extend(await self._check_database(config))
        if EngineConfigCheckKind.COMPONENTS in checks:
            errors.extend(await self._check_components(config))

        if errors:
            return Fail(errors)

        return Ok(config)

    async def _check_database(self, config: EngineConfig) -> list[EngineConfigDatabaseError]:
        self._log("Checking database configuration...")

        errors: list[EngineConfigDatabaseError] = []

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
                    EngineConfigDatabaseError(
                        message="Failed to connect to database.",
                        exception=traceback.format_exc(),
                    )
                ]
            finally:
                await database.dispose()

        return errors

    async def _check_components(self, config: EngineConfig) -> list[EngineConfigComponentLoadError]:
        self._log("Checking component configurations...")

        errors: list[EngineConfigComponentLoadError] = []

        for unit in config.units:
            for connection in unit.connections:
                path = ConnectionPath.create(unit.name, connection.name)
                self._log(f"Checking component '{path}'...")
                match Connection.load(connection.component, connection.parameters):
                    case Fail(error):
                        errors.append(
                            EngineConfigComponentLoadError(
                                path=path,
                                inner=error,
                            )
                        )

        return errors
