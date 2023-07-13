import os
import warnings
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Sequence

import rich
import rich.box
from rich.table import Table
from typer import Option, Typer

from ceres.config import Config, ConfigCheckKind
from ceres.data import jsonify
from ceres.internal.cli.exceptions import CLIInvalidConfigException
from ceres.internal.utilities import syncify
from ceres.result import Ok


class AsyncTyper(Typer):
    if not TYPE_CHECKING:

        @wraps(Typer.command)
        def command(self, *args, **kwargs):
            base = super()

            def decorator(function):
                base.command(*args, **kwargs)(syncify(function))
                return function

            return decorator

        @wraps(Typer.callback)
        def callback(self, *args, **kwargs):
            base = super()

            def decorator(function):
                base.callback(*args, **kwargs)(syncify(function))
                return function

            return decorator


chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir():
    os.chdir = __disabled_chdir__


def get_config_path(config_path: Path | None) -> Path:
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
                config_path = possibility.absolute()
                break
        else:
            raise CLIInvalidConfigException(
                f"Must be in a directory containing one of: {possibilities}"
            )

    chdir(config_path.parent)
    disable_chdir()
    return config_path


async def get_config(
    config_path: Path | None,
    checks: Sequence[ConfigCheckKind],
) -> Config:
    match await Config.load(
        get_config_path(config_path),
        log=rich.print,
        checks=checks,
    ):
        case Ok(config):
            return config
        case fail:
            raise CLIInvalidConfigException(
                f"Failed to load configuration. {jsonify(fail, indent=2)}"
            )


def ConfigPathOption() -> Any:
    return Option(
        None,
        "--config",
        exists=True,
        resolve_path=True,
        dir_okay=False,
        callback=get_config_path,
    )


def ConfigOption(*, checks: Sequence[ConfigCheckKind]) -> Any:
    async def callback(config_path: Path = ConfigPathOption()) -> Config:
        return await get_config(config_path, checks)

    return Option(
        None,
        "--config",
        help="Provide an explicit path to a Ceres configuration file.",
        exists=True,
        resolve_path=True,
        dir_okay=False,
        callback=syncify(callback),
    )


def get_yes_no(prompt: str, default: bool | None = None) -> bool:
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


def write(
    *args: object,
    sep: str = " ",
    end: str = "\n",
    file: IO[str] | None = None,
    flush: bool = False,
):
    rich.print(
        *args,
        sep=sep,
        end=end,
        file=file,
        flush=flush,
    )


@contextmanager
def write_table(title: str | None = None):
    table = Table(title=title, box=rich.box.SQUARE, title_justify="left")
    yield table
    rich.print(table)


def strbool(value: bool) -> str:
    return "Yes" if value else "No"
