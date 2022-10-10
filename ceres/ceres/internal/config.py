from __future__ import annotations

import os
import traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from logging import Logger
from typing import Any, Callable, Iterable, Sequence

import anyio
import yaml
from pydantic import ValidationError
from yaml import YAMLError

from ..component import Component
from ..config import ComponentConfig, Config, ConnectionConfig, DriverConfig, UnitConfig
from ..connection import Connection
from ..driver import Driver
from ..errors import (
    ComponentReferenceInvalidError,
    ConfigComponentError,
    ConfigDatabaseError,
    ConfigError,
    ConfigParseError,
    ConfigReadError,
    ConfigValidationError,
    ValidationProblem,
)
from ..path import ConnectionPath, DriverPath, create_component_path
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

    def check_unit_config(unit_config: UnitConfig) -> Iterable[ConfigComponentError]:
        loaded_connections: list[tuple[ConnectionConfig, Connection]] = []
        loaded_drivers: list[tuple[DriverConfig, Driver]] = []

        def check_connections() -> Iterable[ConfigComponentError]:
            for connection_config in unit_config.connections:
                path = ConnectionPath.create(unit_config.name, connection_config.name)
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
                path = DriverPath.create(unit_config.name, driver_config.name)
                log(f"Checking component '{path}'...")
                match load_component(
                    Driver,
                    driver_config.component,
                    driver_config.parameters,
                ):
                    case Ok(driver):
                        loaded_drivers.append((driver_config, driver))
                    case Fail(error):
                        log("fail")
                        yield ConfigComponentError(
                            component=path,
                            error=error,
                        )

        def check_references() -> Iterable[ConfigComponentError]:
            loaded_components: list[tuple[ComponentConfig, Component[Any]]] = [
                *loaded_connections,
                *loaded_drivers,
            ]

            for component_config, component in loaded_components:
                for binding in component.get_reference_bindings():
                    if (
                        binding.path.kind == "connection"
                        and binding.path.name not in component_config.references.connections
                        or binding.path.kind == "driver"
                        and binding.path.name not in component_config.references.drivers
                    ):
                        path = create_component_path(
                            "connection" if isinstance(component, Connection) else "driver",
                            unit_config.name,
                            component_config.name,
                        )

                        yield ConfigComponentError(
                            component=path,
                            error=ComponentReferenceInvalidError(
                                message=f"{path} requires {binding.path.kind} reference '{binding.path.name}', but it is not assigned.",
                                reference=binding.path,
                            ),
                        )

        return [*check_connections(), *check_drivers(), *check_references()]

    errors: list[ConfigComponentError] = []

    for unit_config in config.units:
        errors.extend(check_unit_config(unit_config))

    return errors
