import os
import sys
import warnings
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import IO, Any, Callable, Sequence

import typer
from click import ParamType
from pydantic import field_validator

from ceres.config import Config, ConfigCheckType
from ceres.data import ImmutableDataObject, jsonify
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException, CLIInvalidConfigException
from ceres.internal.cli.plumbing import CLIContext
from ceres.internal.project import Project
from ceres.internal.utilities import is_non_stringy_collection
from ceres.result import Ok

chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    os.chdir = __disabled_chdir__


def get_config_path(config_path: Path | None = None) -> Path:
    if config_path is None:
        possibilities = [
            Path(name)
            for name in (
                "ceres.yaml",
                "ceres.yml",
                "ceres.json",
            )
        ]

        for possibility in possibilities:
            if possibility.is_file():
                config_path = possibility
                break
        else:
            raise CLIInvalidConfigException(
                f"Must be in a directory containing one of: {possibilities}"
            )

    config_path = config_path.absolute()
    chdir(config_path.parent)
    disable_chdir()
    sys.path.insert(0, str(config_path.parent))
    return config_path


async def get_config(
    config_path: Path | None,
    checks: Sequence[ConfigCheckType],
    silent: bool = False,
) -> Config:
    import rich

    match await Config.load(
        get_config_path(config_path),
        log=rich.print if not silent else lambda *args: None,
        checks=checks,
    ):
        case Ok(config):
            return config
        case fail:
            raise CLIInvalidConfigException(
                f"Failed to load configuration. {jsonify(fail, indent=2)}"
            )


async def use_config_path(context: CLIContext) -> Path:
    config_path = context.meta.get("config_path")
    if config_path is None:
        raise CLIInvalidConfigException("No `config_path` is set.")

    return config_path


async def use_config(
    context: CLIContext,
    checks: Sequence[ConfigCheckType] = (),
    silent: bool = False,
) -> Config:
    config_path = await use_config_path(context)
    return await get_config(config_path, checks, silent)


async def use_project(
    context: CLIContext,
    checks: Sequence[ConfigCheckType] = (),
    silent: bool = False,
) -> Project:
    config_path = await use_config_path(context)
    return Project(
        get_config_path(config_path),
        await get_config(config_path, checks, silent),
    )


@wraps(typer.confirm)
def confirm(
    text: str,
    default: bool | None = False,
    abort: bool = False,
    prompt_suffix: str = ": ",
    show_default: bool = True,
    err: bool = False,
) -> bool:
    return typer.confirm(
        text=text,
        default=default,
        abort=abort,
        prompt_suffix=prompt_suffix,
        show_default=show_default,
        err=err,
    )


@wraps(typer.prompt)
def prompt(
    text: str,
    default: Any | None = None,
    hide_input: bool = False,
    confirmation_prompt: bool | str = False,
    type: ParamType | Any | None = None,
    value_proc: Callable[[str], Any] | None = None,
    prompt_suffix: str = ": ",
    show_default: bool = True,
    err: bool = False,
    show_choices: bool = True,
) -> Any:
    return typer.prompt(
        text=text,
        default=default,
        hide_input=hide_input,
        confirmation_prompt=confirmation_prompt,
        type=type,
        value_proc=value_proc,
        prompt_suffix=prompt_suffix,
        show_default=show_default,
        err=err,
        show_choices=show_choices,
    )


def write(
    *args: object,
    sep: str = " ",
    end: str = "\n",
    file: IO[str] | None = None,
    flush: bool = False,
):
    import rich

    rich.print(
        *args,
        sep=sep,
        end=end,
        file=file,
        flush=flush,
    )


@contextmanager
def write_table(title: str | None = None):
    import rich.box
    from rich.table import Table

    table = Table(title=title, box=rich.box.ROUNDED, title_justify="left")
    yield table
    write(table)


def strbool(value: bool) -> str:
    return "Yes" if value else "No"


async def get_database(config: Config, *, initialized: bool = False):
    from ceres.database.database import Database

    database = Database(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if initialized:
        if not await database.initialized():
            raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    return database


async def use_database(
    context: CLIContext,
    *,
    initialized: bool = False,
):
    from ceres.database.database import Database

    config = await use_config(context)
    database = Database(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if initialized:
        if not await database.initialized():
            raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    return database


async def use_temporary_engine(
    context: CLIContext,
    checks: Sequence[ConfigCheckType] = (ConfigCheckType.DATABASE,),
    silent: bool = True,
):
    from ceres.engine import Engine

    config = await use_config(
        context,
        checks=checks,
        silent=silent,
    )
    return Engine(config)


class ValidateEmptyAsNone(ImmutableDataObject):
    @field_validator("*")
    def __validate_empty_as_none(cls, value: Any) -> Any:
        if is_non_stringy_collection(value) and len(value) == 0:
            return None

        return value
