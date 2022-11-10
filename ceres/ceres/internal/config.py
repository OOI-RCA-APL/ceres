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

from ..address import ComponentAddress
from ..component import Component
from ..config import Config, UnitConfig
from ..connection import Connection
from ..driver import Driver
from ..errors import (
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
from ..result import Fail, Ok, Result
from ..utilities import utc
from .component import load_component
from .database.manager import DatabaseManager
from .utilities import show_td, unreachable


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"

    @classmethod
    def all(cls) -> Sequence["ConfigCheckKind"]:
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

    start = utc()
    timeout = config.database.retry.timeout
    interval = config.database.retry.interval

    while True:
        database = DatabaseManager(config.database)

        try:
            async with database.connect():
                log("Connected to database successfully.")
                return []
        except Exception:
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
        components: dict[str, Component] = {}

        def check_components() -> Iterable[ConfigComponentError]:
            database = DatabaseManager(config.database)

            for component_config in unit_config.components:
                match component_config.kind:
                    case "connection":
                        cls: type[Component] = Connection
                    case "driver":
                        cls = Driver
                    case "notifier":
                        cls = Notifier
                    case _:
                        unreachable()

                address = ComponentAddress(unit_config.name, component_config.name)
                log(f"Checking component '{address}'...")
                match load_component(
                    cls,
                    component_config,
                    Component.CompleteContext(
                        id=uuid4(),
                        address=address,
                        root_config=config,
                        unit_config=unit_config,
                        component_config=component_config,
                        database=database,
                        entities=database.entities,
                    ),
                    components,
                ):
                    case Ok(component):
                        components[component_config.name] = component
                    case Fail(error):
                        yield ConfigComponentError(
                            component=address,
                            error=error,
                        )

        yield from check_components()

    errors: list[ConfigComponentError] = []

    for unit_config in config.units:
        errors.extend(check_unit_config(unit_config))

    return errors
