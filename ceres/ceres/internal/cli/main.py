import asyncio
import signal
from asyncio import FIRST_COMPLETED
from asyncio import Event as AsyncEvent
from pathlib import Path
from typing import Any

import anyio
import rich
from aiohttp import ClientError, ClientSession
from anyio.abc import TaskGroup
from typer import Option

from ...config import Config
from ...data import jsonify
from ...engine import Engine
from ...exceptions import EngineException
from ...result import Ok
from ...utilities import spawn
from .. import logs
from ..config import load_config
from ..utilities import (
    ensure_event_loop,
    set_current_process_name,
    strify,
    syncify,
    temporary_signal_handler,
)
from .exceptions import (
    CLIEngineNotRunningException,
    CLIInvalidConfigException,
    CLIServerNotEnabledException,
    CLIStartupException,
)
from .shared import AsyncTyper, ConfigOption, ConfigPathOption, get_config
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
    Start the engine as a foreground process.
    """
    try:
        if watch:
            set_current_process_name("ceres-watch")
            await _run_watch(config_path=config_path)
        else:
            set_current_process_name("ceres")
            engine = Engine(await get_config(config_path, checks=[]))
            exiting = AsyncEvent()

            async def main() -> None:
                task_run = asyncio.create_task(engine.run())
                task_wait_until_exiting = asyncio.create_task(exiting.wait())

                await asyncio.wait(
                    [
                        task_run,
                        task_wait_until_exiting,
                    ],
                    return_when=FIRST_COMPLETED,
                )

                try:
                    if task_run.done():
                        if not task_run.cancelled():
                            task_run.result()
                    else:
                        await engine.stop()
                finally:
                    task_run.cancel()
                    task_wait_until_exiting.cancel()

            def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
                exiting.set()

            with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                await main()
    except EngineException as exception:
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


@main.command()
async def reload(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Apply configuration changes while the engine is running.
    """
    if config.server is None or not config.server.enable:
        raise CLIServerNotEnabledException("Engine server is not enabled.")
    try:
        async with ClientSession(base_url=f"http://0.0.0.0:{config.server.port}") as client:
            await client.post("/api/reload")
    except ClientError:
        raise CLIEngineNotRunningException("Engine is not running or not accessible at the moment.")


@main.callback()
def setup() -> None:
    ensure_event_loop()
    logs.setup()


def _run_sync(*, config_path: Path, watch: bool = False) -> None:
    syncify(run)(config_path=config_path, watch=watch)


async def _run_watch(*, config_path: Path) -> None:
    async def main() -> None:
        from watchfiles import PythonFilter, awatch
        from watchfiles.run import CombinedProcess, start_process

        import ceres

        async def start() -> CombinedProcess:
            target = _run_sync
            kwargs = {
                "config_path": config_path,
                "watch": False,
            }

            return await spawn(start_process, target, "function", (), kwargs)

        # Start the initial process.
        process = await start()

        try:
            async for changes in awatch(
                # Watch for changes in the project directory.
                config_path.parent,
                # Watch for changes in "ceres" itself.
                Path(ceres.__file__).parent,
                watch_filter=PythonFilter(
                    # Ignore changes to this module in particular.
                    ignore_paths=[__file__],
                    # Watch for changes in the configuration file.
                    extra_extensions=[str(config_path)],
                ),
            ):
                info = sorted(
                    [(path, change._name_) for (change, path) in changes],
                    key=lambda current: current[0],
                )

                # Indicate a restart and show changed files.
                rich.print(f"Restarting, watch mode detected: {strify(info)}")

                # Stop the running process if necessary.
                if process.is_alive():
                    await spawn(process.stop, 15, 5)

                # Start a new process.
                process = await start()
        finally:
            try:
                # Ensure the last process started is stopped.
                if process.is_alive():
                    await spawn(process.stop, 15, 5)
            except Exception:
                pass

    group: TaskGroup | None = None

    def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
        if group is not None:
            group.cancel_scope.cancel()

    with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
        async with anyio.create_task_group() as group:
            group.start_soon(main, name="main")
