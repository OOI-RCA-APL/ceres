import asyncio
import traceback
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Callable, Iterable, Sequence

import yaml
from pydantic import ValidationError
from yaml import MarkedYAMLError, YAMLError

from ceres.address import Address
from ceres.component import Component, Paths
from ceres.config import Config, UnitConfig
from ceres.data import Name
from ceres.database import Database
from ceres.errors import (
    ComponentInitExceptionError,
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
from ceres.internal.utilities import show_td
from ceres.logs import Log
from ceres.result import Fail, Ok, Result
from ceres.timing import utc


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"

    @classmethod
    def all(cls) -> Sequence["ConfigCheckKind"]:
        return tuple(cls)


async def load_config(
    config: Path | dict[str, object] | Config,
    *,
    checks: Sequence[ConfigCheckKind] = ConfigCheckKind.all(),
    logger: Logger | Log | Callable[[object], None] = lambda message: None,
) -> Result[Config, list[ConfigError]]:
    def log(message: object) -> None:
        if isinstance(logger, Logger | Log):
            logger.info(message)
        else:
            logger(message)

    try:
        if isinstance(config, dict):
            config = Config.from_data(config)
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

            config = Config.from_data(data, path)
    except ValidationError as error:
        return Fail([ConfigValidationError(problems=ValidationProblem.extract(error))])

    errors: list[ConfigError] = []

    if ConfigCheckKind.DATABASE in checks:
        errors.extend(await _check_database(config, log))
        log("Database configuration is valid.")
    if ConfigCheckKind.COMPONENTS in checks:
        errors.extend(await _check_components(config, log))
        log("Component configurations are valid.")

    if errors:
        return Fail(errors)

    return Ok(config)


async def _check_database(
    config: Config,
    log: Callable[[object], None],
) -> list[ConfigDatabaseError]:
    log("Checking database configuration...")

    start = utc()
    timeout = config.database.retry.timeout
    interval = config.database.retry.interval

    while True:
        database = Database(config.database)

        try:
            async with database.connect():
                log("Connected to database successfully.")
                return []
        except Exception as exception:
            elapsed = utc() - start

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
                f"Failed to connect to database, {exception}, {show_td(elapsed)} of "
                f"{show_td(timeout)} timeout elapsed, retrying in {show_td(interval)}..."
            )
            await database.dispose()
            await asyncio.sleep(interval.total_seconds())
            continue
        finally:
            await database.dispose()


async def _check_components(
    config: Config,
    log: Callable[[object], None],
) -> list[ConfigComponentError]:
    log("Checking component configurations...")

    Paths()

    def check_unit_config(unit_config: UnitConfig) -> Iterable[ConfigComponentError]:
        references: dict[Name, Component] = {}

        def check_components() -> Iterable[ConfigComponentError]:
            for component_config in unit_config.components:
                address = Address(unit_config.name) / component_config.name
                log(f"Checking component '{address}'...")
                try:
                    component = component_config.load()
                    error = component.assign_references(references)
                except Exception as exception:
                    yield ConfigComponentError(
                        component=address,
                        error=ComponentInitExceptionError(
                            message="an exception occurred while loading this component",
                            traceback=traceback.format_exception(exception),
                        ),
                    )
                    continue

                if error is not None:
                    yield ConfigComponentError(
                        component=address,
                        error=ComponentReferenceInvalidError(
                            message=error.message,
                        ),
                    )

                references[component_config.name] = component

        yield from check_components()

    errors: list[ConfigComponentError] = []

    for unit_config in config.units:
        errors.extend(check_unit_config(unit_config))

    return errors
