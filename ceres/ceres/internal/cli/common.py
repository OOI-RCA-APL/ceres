from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import rich
from typer import Option

from ...config import Config
from ...result import Ok
from ..config import ConfigCheckKind, load_config
from ..utilities import syncify
from .exceptions import CLIInvalidConfigException


def get_config_path(config_path: Path | None) -> Path:
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
            raise CLIInvalidConfigException(f"Failed to load configuration. {fail.json(indent=2)}")


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
