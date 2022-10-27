from __future__ import annotations

import asyncio
import traceback
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from uuid import uuid4

import yaml
from pydantic import ValidationError
from yaml import MarkedYAMLError, YAMLError

from ..component import Component, FullComponentContext
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
from ..path import create_path
from ..result import Fail, Ok, Result
from .component import load_component
from .database.manager import DatabaseManager
from .utilities import get_now, show_td, unreachable


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"

    @classmethod
    def all(cls) -> Sequence[ConfigCheckKind]:
        return tuple(cls)


async def load_config(
    config: Path | dict[str, Any] | Config,
    *,
    checks: Sequence[ConfigCheckKind] = ConfigCheckKind.all(),
    logger: Logger | Callable[[Any], None] = lambda message: None,
) -> Result[Config, list[ConfigError]]:
    def log(message: Any) -> None:
        if isinstance(logger, Logger):
            logger.info(message)
        else:
            logger(message)

    try:
        if isinstance(config, dict):
            config = Config.parse_obj(config)
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

    start = get_now()
    timeout = config.database.retry.timeout
    interval = config.database.retry.interval

    while True:
        database = DatabaseManager(config.database)

        try:
            async with database.connect():
                log("Connected to database successfully.")
                return []
        except Exception:
            elapsed = get_now() - start

            if elapsed > timeout:
                log(f"Failed to connect to database within {show_td(timeout)}.")
                await database.dispose()
                return [
                    ConfigDatabaseError(
                        message="failed to connect to database",
                        exception=traceback.format_exc(),
                    )
                ]

            log(
                f"Failed to connect to database, {show_td(elapsed)} of {show_td(timeout)} timeout elapsed, retrying in {show_td(interval)}..."
            )
            await database.dispose()
            await asyncio.sleep(interval.total_seconds())
            continue
        finally:
            await database.dispose()


async def _check_components(
    config: Config,
    log: Callable[[Any], None],
) -> list[ConfigComponentError]:
    log("Checking component configurations...")

    def check_unit_config(unit_config: UnitConfig) -> Iterable[ConfigComponentError]:
        loaded_components: list[tuple[ComponentConfig, Component]] = []

        def check_components() -> Iterable[ConfigComponentError]:
            component_configs: list[ComponentConfig] = [
                *unit_config.connections,
                *unit_config.drivers,
                *unit_config.notifiers,
            ]

            for component_config in component_configs:
                match component_config:
                    case ConnectionConfig():
                        cls: type[Component] = Connection
                    case DriverConfig():
                        cls = Driver
                    case NotifierConfig():
                        cls = Notifier
                    case _:
                        unreachable()

                path = create_path(component_config.kind, unit_config.name, component_config.name)
                log(f"Checking component '{path}'...")
                match load_component(
                    cls,
                    component_config.component,
                    component_config.parameters,
                    FullComponentContext(
                        id=uuid4(),
                        path=path,
                        references=component_config.references,
                        root_config=config,
                        unit_config=unit_config,
                        component_config=component_config,
                        users=config.users,
                        units=config.units,
                    ),
                ):
                    case Ok(component):
                        loaded_components.append((component_config, component))
                    case Fail(error):
                        yield ConfigComponentError(
                            component=path,
                            error=error,
                        )

        def check_references() -> Iterable[ConfigComponentError]:
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
            *check_components(),
            *check_references(),
        ]

    errors: list[ConfigComponentError] = []

    for unit_config in config.units:
        errors.extend(check_unit_config(unit_config))

    return errors
