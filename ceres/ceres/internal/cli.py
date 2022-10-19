from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

from click import ClickException as ExitException
from rich import print
from typer import Option, Typer

from ..config import Config
from ..engine import Engine
from ..result import Ok
from .config import load_config
from .database.manager import DatabaseManager
from .utilities import syncify


class InvalidConfigException(ExitException):
    exit_code = 1


class DatabaseUnreachableException(ExitException):
    exit_code = 2


class CheckFailedException(ExitException):
    exit_code = 3


def _get_config_path(config_path: Path | None) -> Path:
    if not config_path:
        possibilities = [
            "ceres.yaml",
            "ceres.yml",
        ]

        for possibility in possibilities:
            if os.path.isfile(possibility):
                config_path = Path(os.path.realpath(possibility))
                break
        else:
            raise ExitException(f"Must be in a directory containing one of: {possibilities}")

    return config_path


async def _get_config(config_path: Path | None) -> Config:
    match await load_config(_get_config_path(config_path)):
        case Ok(config):
            return config
        case fail:
            raise InvalidConfigException(f"Failed to load configuration. {fail.json(indent=2)}")


CONFIG_PATH_OPTION = Option(
    None,
    "--config",
    exists=True,
    resolve_path=True,
    dir_okay=False,
    callback=_get_config_path,
)

CONFIG_OPTION = Option(
    None,
    "--config",
    exists=True,
    resolve_path=True,
    dir_okay=False,
    callback=syncify(_get_config),
)


async def run(config: Config = CONFIG_OPTION) -> None:
    await Engine(config).run()


async def check(path: Path = CONFIG_PATH_OPTION) -> None:
    match await load_config(path, logger=print):
        case Ok():
            print("All checks passed.")
        case fail:
            raise InvalidConfigException(f"Failed to load configuration. {fail.json(indent=2)}")


async def init(config: Config = CONFIG_OPTION) -> None:
    database = DatabaseManager.create(config.database)

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


def _get_yes_no(prompt: str, default: bool | None = None) -> bool:
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


main = Typer(no_args_is_help=True)
main.command(help="Run the project.")(syncify(run))
main.command(help="Check project configuration for correctness.")(syncify(check))

database = Typer(no_args_is_help=True)
main.add_typer(database, name="database", help="Manage the project database.")
database.command(help="Initialize project database.")(syncify(init))
