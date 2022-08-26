import functools
import os
from typing import Any, Callable, Optional, TypeVar, cast

import click
from click import ClickException, Path

from .database import DatabaseManager
from .engine import Engine
from .exceptions import ConfigException
from .internal import syncify

EXIT_CODE_INVALID_CONFIG = 1


class InvalidConfigException(ClickException):
    exit_code = 1


class DatabaseUnreachableException(ClickException):
    exit_code = 2


def _create_engine(config_path: str) -> Engine:
    return Engine(config_path)


def _create_database(config_path: str) -> DatabaseManager:
    return _create_engine(config_path).database


CallableT = TypeVar("CallableT", bound=Callable[..., Any])


def with_config(callable: CallableT) -> CallableT:
    @functools.wraps(callable)
    @click.option(
        "--config",
        default=None,
        type=Path(
            exists=True,
            resolve_path=True,
            dir_okay=False,
        ),
    )
    def wrapper(*args: Any, config: Optional[str], **kwargs: Any) -> Any:
        if not config:
            possibilities = [
                "ceres.yaml",
                "ceres.yml",
            ]

            for possibility in possibilities:
                if os.path.isfile(possibility):
                    config = os.path.realpath(possibility)
                    break
            else:
                raise ClickException(f"Must be in a directory containing one of: {possibilities}")

        return callable(*args, config=config, **kwargs)

    return cast(CallableT, wrapper)


@click.group()
def main() -> None:
    pass


@main.command()
@with_config
@syncify
async def run(config: str) -> None:
    try:
        engine = _create_engine(config)
    except ConfigException as exception:
        raise InvalidConfigException(exception.message)

    await engine.run()


@main.group()
def database() -> None:
    pass


@database.command()
@with_config
@syncify
async def init(config: str) -> None:
    try:
        database = _create_database(config)
    except ConfigException as exception:
        raise InvalidConfigException(exception.message)

    try:
        async with database.connect():
            pass
    except Exception:
        raise DatabaseUnreachableException("Failed to connect to database.")

    print("Pending commands to execute: ")
    for statement in database.ddl:
        print(f"> {statement}")

    if await database.tables():
        confirm = "Database is not empty, execute above commands anyway?"
    else:
        confirm = "Database appears to be uninitialized. Initialize now?"

    if _get_yes_no(confirm):
        await database.init()
    else:
        print("Database has not been modified.")

    await database.dispose()


T = TypeVar("T")


def _get_value(parser: Callable[[str], T], prompt: str, default: Optional[T]) -> T:
    """
    Get input of a given type from the user. The first argument should be a function to parse the
    input text. If the parser throws an exception while parsing the input, the input will be
    requested again.

    :param parser: The function/class called to parse the input.
    :param prompt: The prompt to display to the user.
    :param default: The default value to return if the user enters an empty input.
    :return: The parsed input or default value.
    """
    while True:
        if default:
            text = input(f"{prompt} ({default}): ")
        else:
            text = input(f"{prompt}: ")

        if text == "":
            if default is not None:
                return default

            if isinstance(parser, type):
                if issubclass(parser, (bool, int, float)):
                    continue

        try:
            return parser(text)
        except:
            pass


def _get_yes_no(prompt: str, default: Optional[bool] = None) -> bool:
    """
    Get a yes/no boolean input from the user with an optional default value.

    :param prompt: The prompt to display to the user.
    :param default: The default value to return if the user enters an empty input.
    :return: The input boolean or default value.
    """
    while True:
        if default is None:
            default_indicator = "y/n"
        elif default:
            default_indicator = "Y/n"
        else:
            default_indicator = "y/N"

        text = input(f"{prompt} ({default_indicator}): ").lower()
        if default is not None and text == "":
            return default
        if text in ("yes", "y"):
            return True
        if text in ("no", "n"):
            return False
