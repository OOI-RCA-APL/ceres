from __future__ import annotations

import functools
import os
from typing import Any, Callable, TypeVar, cast

import click
from click import ClickException, Path

from .config import EngineConfig
from .database import create_database_manager
from .engine import Engine
from .internal import syncify
from .load import load_engine_config

EXIT_CODE_INVALID_CONFIG = 1


class InvalidConfigException(ClickException):
    exit_code = 1


class DatabaseUnreachableException(ClickException):
    exit_code = 2


class CheckFailedException(ClickException):
    exit_code = 3


CallableT = TypeVar("CallableT", bound=Callable[..., Any])


def register(callable: CallableT) -> CallableT:
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
    @syncify
    async def wrapper(*args: Any, config: str | None, **kwargs: Any) -> Any:
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

        def on_database_retry() -> None:
            print("Failed to connect to database, retrying...")

        if not (
            result := await load_engine_config(
                config,
                on_database_retry=on_database_retry,
            )
        ).ok:
            raise InvalidConfigException(f"Failed to load configuration. {result.json(indent=2)}")

        return await callable(*args, config=result.value, **kwargs)

    return cast(CallableT, wrapper)


@click.group()
def main() -> None:
    pass


@main.command()
@register
async def run(config: EngineConfig) -> None:
    await Engine(config).run()


@main.command()
@register
async def check(config: EngineConfig) -> None:
    print("All checks passed.")


@main.group()
def database() -> None:
    pass


@database.command()
@register
async def init(config: EngineConfig) -> None:
    database = create_database_manager(config.database)

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


def _get_value(parser: Callable[[str], T], prompt: str, default: T | None = None) -> T:
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


def _get_yes_no(prompt: str, default: bool | None = None) -> bool:
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
