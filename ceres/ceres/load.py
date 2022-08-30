from __future__ import annotations

import os
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Literal, Sequence

import anyio
import yaml
from pydantic import ValidationError
from yaml import YAMLError

from .component import ComponentLoadError
from .config import EngineConfig
from .connection import Connection
from .data import DataObject
from .database import create_database_manager
from .path import ComponentPath, ConnectionPath
from .result import Fail, Ok, Result


class SchemaProblem(DataObject):
    location: list[str | int]
    message: str
    kind: str


def extract_schema_problems(error: ValidationError) -> list[SchemaProblem]:
    return [
        SchemaProblem(
            location=error["loc"],
            message=error["msg"],
            kind=error["type"],
        )
        for error in error.errors()
    ]


class EngineConfigErrorKind(str, Enum):
    READ_ERROR = "read-error"
    PARSE_ERROR = "parse-error"
    SCHEMA_ERROR = "schema-error"
    DATABASE_ERROR = "database-error"
    COMPONENT_LOAD_ERROR = "component-load-error"


class EngineConfigReadError(DataObject):
    kind: Literal[EngineConfigErrorKind.READ_ERROR] = EngineConfigErrorKind.READ_ERROR


class EngineConfigParseError(DataObject):
    kind: Literal[EngineConfigErrorKind.PARSE_ERROR] = EngineConfigErrorKind.PARSE_ERROR


class EngineConfigSchemaError(DataObject):
    kind: Literal[EngineConfigErrorKind.SCHEMA_ERROR] = EngineConfigErrorKind.SCHEMA_ERROR
    problems: list[SchemaProblem] = []


class EngineConfigDatabaseError(DataObject):
    kind: Literal[EngineConfigErrorKind.DATABASE_ERROR] = EngineConfigErrorKind.DATABASE_ERROR
    message: str
    exception: str


class EngineConfigComponentLoadError(DataObject):
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
    database = "database"
    components = "components"


async def load_engine_config(
    config: str | dict[str, Any] | EngineConfig,
    checks: Sequence[EngineConfigCheckKind] = list(EngineConfigCheckKind),
    on_database_retry: Callable[..., None] | None = None,
) -> Result[EngineConfig, list[EngineConfigError]]:
    try:
        if isinstance(config, dict):
            config = EngineConfig.parse_obj(config)
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
    except ValidationError as error:
        return Fail([EngineConfigSchemaError(problems=extract_schema_problems(error))])

    errors: list[EngineConfigError] = []

    if EngineConfigCheckKind.database in checks:
        errors.extend(await _check_database(config, on_database_retry))
    if EngineConfigCheckKind.components in checks:
        errors.extend(await _check_components(config))

    if errors:
        return Fail(errors)

    return Ok(config)


async def _check_database(
    config: EngineConfig,
    on_retry: Callable[..., None] | None = None,
) -> list[EngineConfigDatabaseError]:
    errors: list[EngineConfigDatabaseError] = []

    attempt = 0
    start = datetime.now(timezone.utc)

    while (datetime.now(timezone.utc) - start) < timedelta(seconds=config.database.retry.timeout):
        try:
            database = create_database_manager(config.database)
            async with database.connect():
                return errors
        except Exception:
            if config.database.retry.attempts is None or attempt < config.database.retry.attempts:
                if on_retry:
                    on_retry()
                await database.dispose()
                await anyio.sleep(1)
                attempt += 1
                continue

            await database.dispose()
            errors.append(
                EngineConfigDatabaseError(
                    message="Failed to connect to database.",
                    exception=traceback.format_exc(),
                )
            )
            break
        finally:
            await database.dispose()

    return errors


async def _check_components(config: EngineConfig) -> list[EngineConfigComponentLoadError]:
    errors: list[EngineConfigComponentLoadError] = []

    for unit in config.units:
        for connection in unit.connections:
            path = ConnectionPath.create(unit.name, connection.name)
            if not (result := Connection.load(connection.component, connection.parameters)).ok:
                errors.append(
                    EngineConfigComponentLoadError(
                        path=path,
                        inner=result.error,
                    )
                )

    return errors
