import signal
from pathlib import Path
from typing import Any, Iterable

import anyio
import rich
from anyio.abc import TaskGroup
from typer import Typer
from watchfiles import Change, PythonFilter, arun_process

from ...config import Config
from ...data import jsonify
from ...engine import Engine
from ...exceptions import StartupException
from ...result import Ok
from .. import logs
from ..config import load_config
from ..utilities import strify, syncify, temporary_signal_handler
from .common import ConfigOption, ConfigPathOption
from .exceptions import CLIInvalidConfigException, CLIStartupException
from .subcommands.database import database


async def run(*, config: Config = ConfigOption(checks=[]), watch: bool = False) -> None:
    try:
        if watch:
            await _run_watch(config)
        else:
            await Engine(config).run()
    except StartupException as exception:
        raise CLIStartupException(f"Engine startup failed. {exception.message}")


def _run_sync(*, config: Config, watch: bool = False) -> None:
    syncify(run)(config=config, watch=watch)


async def _run_watch(config: Config) -> None:
    async def main() -> None:
        import ceres

        def callback(changes: Iterable[tuple[Change, str]]) -> None:
            info = sorted(
                [(path, change._name_) for (change, path) in changes],
                key=lambda current: current[0],
            )

            rich.print(f"Restarting, watch mode detected: {strify(info)}")

        await arun_process(
            # Watch for changes in "ceres" itself.
            Path(ceres.__file__).parent,
            # Watch for changes in the project directory.
            *([Path(config.path).parent] if config.path else []),
            target=_run_sync,
            kwargs={
                "config": config,
                "watch": False,
            },
            watch_filter=PythonFilter(
                # Ignore changes to this module in particular.
                ignore_paths=[__file__],
            ),
            callback=callback,
        )

    group: TaskGroup | None = None

    def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
        if group is not None:
            group.cancel_scope.cancel()

    with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
        async with anyio.create_task_group() as group:
            group.start_soon(main, name="main")


async def check(*, path: Path = ConfigPathOption()) -> None:
    match await load_config(path, logger=rich.print):
        case Ok():
            rich.print("All checks passed.")
        case fail:
            raise CLIInvalidConfigException(
                f"Failed to load configuration. {jsonify(fail, indent=2)}"
            )


root = Typer(no_args_is_help=True)
root.command(help="Run the project.")(syncify(run))
root.command(help="Check project configuration for correctness.")(syncify(check))

root.add_typer(database, name="database", help="Manage the project database.")


@root.callback()
def setup() -> None:
    logs.setup()
