from __future__ import annotations

from pathlib import Path

import rich
from typer import Typer

from ...config import Config
from ...engine import Engine
from ...exceptions import StartupException
from ...result import Ok
from .. import logs
from ..config import load_config
from ..utilities import syncify
from .common import CONFIG_OPTION, CONFIG_PATH_OPTION
from .exceptions import CLIInvalidConfigException, CLIStartupException
from .subcommands.database import database


async def run(config: Config = CONFIG_OPTION) -> None:
    try:
        await Engine(config).run()
    except StartupException as exception:
        raise CLIStartupException(f"Engine startup failed. {exception.message}")


async def check(path: Path = CONFIG_PATH_OPTION) -> None:
    match await load_config(path, logger=rich.print):
        case Ok():
            rich.print("All checks passed.")
        case fail:
            raise CLIInvalidConfigException(f"Failed to load configuration. {fail.json(indent=2)}")


root = Typer(no_args_is_help=True)
root.command(help="Run the project.")(syncify(run))
root.command(help="Check project configuration for correctness.")(syncify(check))

root.add_typer(database, name="database", help="Manage the project database.")


@root.callback()
def setup() -> None:
    logs.setup()
