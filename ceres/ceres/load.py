from __future__ import annotations

import os
import traceback
from enum import Enum
from typing import Any, Callable, Literal, Sequence

import anyio
import yaml
from pydantic import ValidationError
from yaml import YAMLError

from .config import EngineConfig
from .connection import Connection
from .data import DataObject
from .database import create_database_manager
from .exceptions import ComponentLoadException
from .path import ComponentPath, ConnectionPath


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
    read = "read"
    parse = "parse"
    schema = "schema"
    database = "database"
    component = "component"


class EngineConfigReadError(DataObject):
    kind: Literal[EngineConfigErrorKind.read] = EngineConfigErrorKind.read


class EngineConfigParseError(DataObject):
    kind: Literal[EngineConfigErrorKind.parse] = EngineConfigErrorKind.parse


class EngineConfigSchemaError(DataObject):
    kind: Literal[EngineConfigErrorKind.schema] = EngineConfigErrorKind.schema
    problems: list[SchemaProblem] = []


class EngineConfigDatabaseError(DataObject):
    kind: Literal[EngineConfigErrorKind.database] = EngineConfigErrorKind.database
    message: str
    exception: str


class EngineConfigComponentError(DataObject):
    kind: Literal[EngineConfigErrorKind.component] = EngineConfigErrorKind.component
    path: ComponentPath
    message: str
    exception: str


EngineConfigError = (
    EngineConfigReadError
    | EngineConfigParseError
    | EngineConfigSchemaError
    | EngineConfigDatabaseError
    | EngineConfigComponentError
)

# async def check_engine_config(config: str | dict[str, Any] | EngineConfig) ->


class EngineConfigLoadSuccess(DataObject):
    ok: Literal[True] = True
    config: EngineConfig


class EngineConfigLoadFailed(DataObject):
    ok: Literal[False] = False
    errors: list[EngineConfigError]


EngineConfigLoadResult = EngineConfigLoadSuccess | EngineConfigLoadFailed


class EngineConfigCheckKind(str, Enum):
    database = "database"
    components = "components"


async def load(
    config: str | dict[str, Any] | EngineConfig,
    checks: Sequence[EngineConfigCheckKind] = list(EngineConfigCheckKind),
    on_database_retry: Callable[..., None] | None = None,
) -> EngineConfigLoadResult:
    try:
        if isinstance(config, dict):
            config = EngineConfig.parse_obj(config)
        elif isinstance(config, str):
            try:
                path = os.path.realpath(config)
            except Exception:
                return EngineConfigLoadFailed(errors=[EngineConfigReadError()])

            try:
                with open(path, "r") as stream:
                    data = yaml.safe_load(stream)
            except OSError:
                return EngineConfigLoadFailed(errors=[EngineConfigReadError()])
            except YAMLError:
                return EngineConfigLoadFailed(errors=[EngineConfigParseError()])

            config = EngineConfig.parse_obj(data)
            config.__path__ = path
    except ValidationError as error:
        return EngineConfigLoadFailed(
            errors=[EngineConfigSchemaError(problems=extract_schema_problems(error))]
        )

    errors: list[EngineConfigError] = []

    if EngineConfigCheckKind.database in checks:
        errors.extend(await _check_database(config))
    if EngineConfigCheckKind.components in checks:
        errors.extend(await _check_components(config))

    if errors:
        return EngineConfigLoadFailed(errors=errors)

    return EngineConfigLoadSuccess(config=config)


async def _check_database(
    config: EngineConfig,
    on_retry: Callable[..., None] | None = None,
) -> list[EngineConfigDatabaseError]:
    errors: list[EngineConfigDatabaseError] = []

    attempt = 0

    while True:
        try:
            database = create_database_manager(config.database)
            async with database.connect():
                if on_retry:
                    on_retry()
                return errors
        except Exception:
            if config.database.retry.attempts is None or attempt < config.database.retry.attempts:
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


async def _check_components(config: EngineConfig) -> list[EngineConfigComponentError]:
    errors: list[EngineConfigComponentError] = []

    for unit in config.units:
        for connection in unit.connections:
            path = ConnectionPath.create(unit.name, connection.name)
            try:
                Connection.load(connection.component, connection.parameters)
            except ComponentLoadException:
                errors.append(
                    EngineConfigComponentError(
                        path=path,
                        message=f"Configuration check failed, component '{path}' failed to load.",
                        exception=traceback.format_exc(),
                    )
                )

    return errors
