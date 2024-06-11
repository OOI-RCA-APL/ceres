from __future__ import annotations

import os
from contextlib import contextmanager
from typing import IO, Annotated, Any, Callable, Literal, Mapping, Sequence, TypeVar, overload

import typer
from click import ParamType
from pydantic import Field, field_validator

from ceres._internal.cli.plumbing import CLICommandFailed, CLIContext, CLIOption
from ceres._internal.lazy import lazy_imports
from ceres.config import Config, ConfigCheckType, ConfigMeta
from ceres.data import FromYAML, ImmutableDataObject, NonEmpty, jsonify
from ceres.result import Ok

with lazy_imports(__name__):
    import sys
    import warnings
    from functools import wraps
    from pathlib import Path

    from ceres._internal import util
    from ceres._internal.cli.client import Client
    from ceres._internal.project import LoadedProject, Project
    from ceres.engine import Engine

chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    os.chdir = __disabled_chdir__


POSSIBLE_CONFIG_NAMES = [
    "ceres.yaml",
    "ceres.yml",
    "ceres.json",
]


@overload
def get_config_path(config_path: Path | None, required: Literal[True]) -> Path: ...


@overload
def get_config_path(config_path: Path | None, required: Literal[False] = False) -> Path | None: ...


def get_config_path(config_path: Path | None = None, required: bool = False) -> Path | None:
    if config_path is None:
        possibilities = [Path(name) for name in POSSIBLE_CONFIG_NAMES]

        for possibility in possibilities:
            if possibility.is_file():
                config_path = possibility
                break
        else:
            if required:
                raise CLICommandFailed(
                    f"Must be in a directory containing one of: {POSSIBLE_CONFIG_NAMES}"
                )

            return None

    config_path = config_path.absolute()
    chdir(config_path.parent)
    disable_chdir()
    sys.path.insert(0, str(config_path.parent))
    return config_path


async def get_config_meta(
    config_path: Path | None,
    checks: Sequence[ConfigCheckType],
) -> ConfigMeta:
    match await ConfigMeta.load(get_config_path(config_path, required=True), checks=checks):
        case Ok(config):
            return config
        case fail:
            raise CLICommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")


async def get_config(
    config_path: Path | None,
    checks: Sequence[ConfigCheckType],
) -> Config:
    match await Config.load(get_config_path(config_path, required=True), checks=checks):
        case Ok(config):
            return config
        case fail:
            raise CLICommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")


async def use_config_path(context: CLIContext) -> Path:
    config_path = context.meta.get("config_path")
    if config_path is None:
        raise CLICommandFailed(f"Must be in a directory containing one of: {POSSIBLE_CONFIG_NAMES}")

    return config_path


async def use_config(
    context: CLIContext,
    checks: Sequence[ConfigCheckType] = (),
) -> Config:
    config_path = await use_config_path(context)
    return await get_config(config_path, checks)


async def use_project(context: CLIContext) -> Project:
    config_path = await use_config_path(context)
    return Project(config_path)


async def use_loaded_project(
    context: CLIContext,
    checks: Sequence[ConfigCheckType] = (),
) -> LoadedProject:
    config_path = await use_config_path(context)
    return LoadedProject(
        get_config_path(config_path, required=True),
        await get_config_meta(config_path, checks),
    )


async def use_client(
    context: CLIContext,
) -> Client:
    project = await use_loaded_project(context)
    return Client(project)


@wraps(typer.confirm)
def get_confirmation(
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
def get_input(
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
        raise CLICommandFailed("Failed to connect to database.")

    if initialized:
        if not await database.initialized():
            raise CLICommandFailed("Database appears uninitialized, exiting.")

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
        raise CLICommandFailed("Failed to connect to database.")

    if initialized:
        if not await database.initialized():
            raise CLICommandFailed("Database appears uninitialized, exiting.")

    return database


async def use_temporary_engine(context: CLIContext):
    config_path = await use_config_path(context)
    engine = Engine()
    await engine.load(config_path)
    return engine


class ValidateEmptyAsNone(ImmutableDataObject):
    @field_validator("*")
    def __validate_empty_as_none(cls, value: Any) -> Any:
        if util.is_true_collection(value) and len(value) == 0:
            return None

        return value


Confirm = Annotated[bool, Field(description="Ask before executing."), CLIOption(bool)]

_TFields = TypeVar("_TFields", bound=Mapping[Any, Any])
Assign = Annotated[
    NonEmpty[FromYAML[_TFields]],
    Field(description="Field(s) to assign, passed as a non-empty JSON or YAML object."),
    CLIOption(str, metavar="JSON/YAML"),
]
