import os
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

import rich
from typer import Option, Typer

from ceres.config import Config
from ceres.data import jsonify
from ceres.internal.cli.exceptions import CLIInvalidConfigException
from ceres.internal.config import ConfigCheckKind, load_config
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


def get_config_path(config_path: Path | None) -> Path:
    if not config_path:
        possibilities = [
            "ceres.yaml",
            "ceres.yml",
            "ceres.json",
        ]

        for possibility in possibilities:
            if os.path.isfile(possibility):
                config_path = Path(os.path.realpath(possibility))
                break
        else:
            raise CLIInvalidConfigException(
                f"Must be in a directory containing one of: {possibilities}"
            )

    return config_path


async def get_config(
    config_path: Path | None,
    checks: Sequence[ConfigCheckKind],
) -> Config:
    match await load_config(get_config_path(config_path), logger=rich.print, checks=checks):
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
