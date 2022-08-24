from typing import Callable, Optional, TypeVar

import click
from click import Path

from .database import Database
from .engine import Engine
from .internal import syncify
from .server import Server
from .supervisor import Supervisor


def _create_engine(path: str) -> Engine:
    return Engine(path, Server, Supervisor)


def _create_database(path: str) -> Database:
    return _create_engine(path).database


@click.group()
def main() -> None:
    pass


@main.command()
@click.argument(
    "path",
    default="ceres.yaml",
    type=Path(
        exists=True,
        resolve_path=True,
        dir_okay=False,
    ),
)
@syncify
async def run(path: str) -> None:
    await _create_engine(path).run()


@main.group()
def database() -> None:
    pass


async def _can_connect_to_database(database: Database) -> bool:
    try:
        async with database.connect():
            return True
    except Exception:
        return False


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


@database.command()
@click.option(
    "--config",
    default="ceres.yaml",
    type=Path(
        exists=True,
        resolve_path=True,
        dir_okay=False,
    ),
)
@syncify
async def init(config: str) -> None:
    database = _create_database(config)

    if not await _can_connect_to_database(database):
        print("Failed to connect to database.")
        return

    if await database.tables():
        print("Database appears to already be initialized. Ensure it provides this schema: ")
        for statement in database.ddl:
            print(f"> {statement}")
        return

    if _get_yes_no("Database appears to be uninitialized. Initialize now?"):
        for statement in database.ddl:
            print(f"> {statement}")
        await database.init()
    else:
        print("Database has not been modified.")
