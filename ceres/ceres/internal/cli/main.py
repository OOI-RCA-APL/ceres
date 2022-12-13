import signal
from pathlib import Path
from typing import Any, Iterable

import anyio
import rich
from anyio.abc import TaskGroup
from typer import Option
from watchfiles import DefaultFilter

from ...data import jsonify
from ...engine import Engine
from ...exceptions import StartupException
from ...result import Ok
from .. import logs
from ..config import load_config
from ..utilities import ensure_event_loop, strify, syncify, temporary_signal_handler
from .exceptions import CLIInvalidConfigException, CLIStartupException
from .shared import AsyncTyper, ConfigPathOption, get_config
from .subcommands.database import database

main = AsyncTyper(
    name="ceres",
    no_args_is_help=True,
    add_completion=False,
)

main.add_typer(database)


@main.command()
async def run(
    *,
    config_path: Path = ConfigPathOption(),
    watch: bool = Option(
        False,
        help="Automatically restart the application on code changes.",
    ),
) -> None:
    """
    Start the Ceres as a foreground process.
    """
    try:
        if watch:
            await _run_watch(config_path=config_path)
        else:
            await Engine(await get_config(config_path, checks=[])).run()
    except StartupException as exception:
        raise CLIStartupException(f"Engine startup failed. {exception.message}")


@main.command()
async def check(*, config_path: Path = ConfigPathOption()) -> None:
    """
    Check project configuration for correctness.
    """
    match await load_config(config_path, logger=rich.print):
        case Ok():
            rich.print("All checks passed.")
        case fail:
            raise CLIInvalidConfigException(
                f"Failed to load configuration. {jsonify(fail, indent=2)}"
            )


@main.callback()
def setup() -> None:
    ensure_event_loop()
    logs.setup()


def _run_sync(*, config_path: Path, watch: bool = False) -> None:
    syncify(run)(config_path=config_path, watch=watch)


async def _run_watch(*, config_path: Path) -> None:
    async def main() -> None:
        from watchfiles import Change, PythonFilter, arun_process

        import ceres

        async def callback(changes: Iterable[tuple[Change, str]]) -> None:
            info = sorted(
                [(path, change._name_) for (change, path) in changes],
                key=lambda current: current[0],
            )

            rich.print(f"Restarting, watch mode detected: {strify(info)}")

        await arun_process(
            # Watch for changes in the project directory.
            config_path.parent,
            # Watch for changes in "ceres" itself.
            Path(ceres.__file__).parent,
            target=_run_sync,
            kwargs={
                "config_path": config_path,
                "watch": False,
            },
            watch_filter=PythonFilter(
                # Ignore changes to this module in particular.
                ignore_paths=[__file__],
                # Watch for changes in the configuration file.
                extra_extensions=[str(config_path)],
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
