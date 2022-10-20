from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import yaml
from pydantic import ValidationError
from yaml import MarkedYAMLError, YAMLError

from ..component import Component
from ..config import (
    ComponentConfig,
    Config,
    ConnectionConfig,
    DriverConfig,
    NotifierConfig,
    UnitConfig,
)
from ..connection import Connection
from ..driver import Driver
from ..errors import (
    ComponentReferenceInvalidError,
    ConfigComponentError,
    ConfigDatabaseError,
    ConfigError,
    ConfigParseError,
    ConfigParseErrorLocation,
    ConfigReadError,
    ConfigValidationError,
    ValidationProblem,
)
from ..notifier import Notifier
from ..path import ConnectionPath, DriverPath, NotifierPath, create_path
from ..result import Fail, Ok, Result
from .component import load_component
from .database.manager import DatabaseManager


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"


async def load_config(
    config: Path | dict[str, Any] | Config,
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
        elif isinstance(config, Path):
            try:
                path = config.resolve()
            except Exception:
                return Fail([ConfigReadError(message=f"path '{config}' could not be resolved")])

            try:
                with open(path, "r") as stream:
                    data = yaml.safe_load(stream)
            except OSError:
                return Fail([ConfigReadError(message=f"failed to read file at '{path}'")])
            except YAMLError as error:
                message: str | None = None
                location: ConfigParseErrorLocation | None = None

                if isinstance(error, MarkedYAMLError):
                    message = error.problem

                    if error.problem_mark:
                        location = ConfigParseErrorLocation(
                            line=error.problem_mark.line,
                            column=error.problem_mark.column,
                        )

                return Fail(
                    [
                        ConfigParseError(
                            message=message,
                            location=location,
                        )
                    ]
                )

            config = Config.parse_obj(data)
            config.__path__ = path
            log("Configuration file matches schema.")
    except ValidationError as error:
        return Fail([ConfigValidationError(problems=ValidationProblem.extract(error))])

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
        database = DatabaseManager.create(config.database)

        try:
            async with database.connect():
                log("Connected to database successfully.")
                return []
        except Exception:
            if config.database.retry.attempts is None or attempt < config.database.retry.attempts:
                log("Failed to connect to database, trying again...")
                await database.dispose()
                await asyncio.sleep(1)
                attempt += 1
                continue

            log("Failed to connect to database.")
            await database.dispose()
            return [
                ConfigDatabaseError(
                    message="failed to connect to database",
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

    def check_unit_config(unit_config: UnitConfig) -> Iterable[ConfigComponentError]:
        loaded_connections: list[tuple[ConnectionConfig, Connection]] = []
        loaded_drivers: list[tuple[DriverConfig, Driver]] = []
        loaded_notifiers: list[tuple[NotifierConfig, Notifier]] = []

        def check_connections() -> Iterable[ConfigComponentError]:
            for connection_config in unit_config.connections:
                path = ConnectionPath(unit_config.name, connection_config.name)
                log(f"Checking component '{path}'...")
                match load_component(
                    Connection,
                    connection_config.component,
                    connection_config.parameters,
                ):
                    case Ok(connection):
                        loaded_connections.append((connection_config, connection))
                    case Fail(error):
                        yield ConfigComponentError(
                            component=path,
                            error=error,
                        )

        def check_drivers() -> Iterable[ConfigComponentError]:
            for driver_config in unit_config.drivers:
                path = DriverPath(unit_config.name, driver_config.name)
                log(f"Checking component '{path}'...")
                match load_component(
                    Driver,
                    driver_config.component,
                    driver_config.parameters,
                ):
                    case Ok(driver):
                        loaded_drivers.append((driver_config, driver))
                    case Fail(error):
                        yield ConfigComponentError(
                            component=path,
                            error=error,
                        )

        def check_notifiers() -> Iterable[ConfigComponentError]:
            for notifier_config in unit_config.notifiers:
                path = NotifierPath(unit_config.name, notifier_config.name)
                log(f"Checking component '{path}'...")
                match load_component(
                    Notifier,
                    notifier_config.component,
                    notifier_config.parameters,
                ):
                    case Ok(notifier):
                        loaded_notifiers.append((notifier_config, notifier))
                    case Fail(error):
                        yield ConfigComponentError(
                            component=path,
                            error=error,
                        )

        def check_references() -> Iterable[ConfigComponentError]:
            loaded_components: list[tuple[ComponentConfig, Component]] = [
                *loaded_connections,
                *loaded_drivers,
                *loaded_notifiers,
            ]

            for component_config, component in loaded_components:
                for binding in component.get_reference_bindings():
                    if not component_config.references.has(binding.path):
                        path = create_path(
                            binding.path.kind,
                            unit_config.name,
                            component_config.name,
                        )

                        yield ConfigComponentError(
                            component=path,
                            error=ComponentReferenceInvalidError(
                                message=f"{path} requires {binding.path.kind} reference '{binding.path.name}', but it is not assigned",
                                reference=binding.path,
                            ),
                        )

        return [
            *check_connections(),
            *check_drivers(),
            *check_notifiers(),
            *check_references(),
        ]

    errors: list[ConfigComponentError] = []

    for unit_config in config.units:
        errors.extend(check_unit_config(unit_config))

    return errors
