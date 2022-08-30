from __future__ import annotations

import asyncio
import functools
import inspect
import os
from typing import Any, Callable, TypeVar, cast

import click
import uvloop
from click import ClickException, Path

from ..config import EngineConfig
from ..engine import Engine
from ..loader import EngineConfigLoader
from ..result import Ok
from .database.manager import DatabaseManager


class InvalidConfigException(ClickException):
    exit_code = 1


class DatabaseUnreachableException(ClickException):
    exit_code = 2


class CheckFailedException(ClickException):
    exit_code = 3


FunctionT = TypeVar("FunctionT", bound=Callable[..., Any])


def asyncronous(function: FunctionT) -> Callable[..., None]:
    if not inspect.iscoroutinefunction(function):
        return function

    @functools.wraps(function)
    def wrapper(*args: list[Any], **kwargs: dict[str, Any]) -> Any:
        uvloop.install()
        return asyncio.run(function(*args, **kwargs))

    return cast(FunctionT, wrapper)


def with_config_path(callable: FunctionT) -> Callable[..., Any]:
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
    def wrapper(*args: Any, config: str | None, **kwargs: Any) -> Any:
        return callable(*args, config_path=_resolve_config_path(config), **kwargs)

    return cast(FunctionT, wrapper)


@click.group()
def main() -> None:
    pass


@main.command()
@with_config_path
@asyncronous
async def run(config_path: str) -> None:
    config = await _get_config(config_path)
    await Engine(config).run()


@main.command()
@with_config_path
@asyncronous
async def check(config_path: str) -> None:
    match await EngineConfigLoader(logger=print).load(config_path):
        case Ok():
            print("All checks passed.")
        case fail:
            raise InvalidConfigException(f"Failed to load configuration. {fail.json(indent=2)}")


@main.group()
def database() -> None:
    pass


@database.command()
@with_config_path
@asyncronous
async def init(config_path: str) -> None:
    config = await _get_config(config_path)
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


def _resolve_config_path(config_path: str | None) -> str:
    if not config_path:
        possibilities = [
            "ceres.yaml",
            "ceres.yml",
        ]

        for possibility in possibilities:
            if os.path.isfile(possibility):
                config_path = os.path.realpath(possibility)
                break
        else:
            raise ClickException(f"Must be in a directory containing one of: {possibilities}")

    return config_path


async def _get_config(config_path: str | None) -> EngineConfig:
    match await EngineConfigLoader().load(_resolve_config_path(config_path)):
        case Ok(config):
            return config
        case fail:
            raise InvalidConfigException(f"Failed to load configuration. {fail.json(indent=2)}")


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
