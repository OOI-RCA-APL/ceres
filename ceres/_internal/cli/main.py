import asyncio
import signal
from asyncio import CancelledError
from asyncio import Event as AsyncEvent
from pathlib import Path
from typing import Annotated, Any, Optional, Sequence

from typer import Exit, Option

from ceres._internal.cli.client import Client
from ceres._internal.cli.plumbing import (
    CLIArgument,
    CLICommandFailed,
    CLIContext,
    CLIOption,
    CLIRouter,
)
from ceres._internal.cli.shared import (
    get_config_path,
    strbool,
    use_config_path,
    use_project,
    write,
    write_table,
)
from ceres._internal.cli.subcommands.alert import router as subcommand__alert
from ceres._internal.cli.subcommands.database import router as subcommand__database
from ceres._internal.cli.subcommands.generate import router as subcommand__generate
from ceres._internal.cli.subcommands.log_entry import router as subcommand__log_entry
from ceres._internal.cli.subcommands.message import router as subcommand__message
from ceres._internal.cli.subcommands.service import router as subcommand__service
from ceres._internal.cli.subcommands.user import router as subcommand__user
from ceres._internal.utilities import (
    cancel,
    ensure_event_loop,
    set_current_process_name,
    strify,
    syncify,
    temporary_signal_handler,
    wait_any,
)
from ceres.address import AddressSelector
from ceres.component import ComponentFilter
from ceres.config import Config
from ceres.data import jsonify
from ceres.engine import Engine
from ceres.result import Fail, Ok
from ceres.status import Status
from ceres.threading import spawn
from ceres.version import __version__

router = CLIRouter(
    name="ceres",
    help=f"Ceres CLI — Package Version {__version__}",
)

router.add_typer(subcommand__alert)
router.add_typer(subcommand__database)
router.add_typer(subcommand__generate)
router.add_typer(subcommand__log_entry)
router.add_typer(subcommand__message)
router.add_typer(subcommand__service)
router.add_typer(subcommand__user)


@router.callback(invoke_without_command=True)
def setup(
    *,
    version: Annotated[
        bool,
        Option("--version", help="Show the current Ceres version number."),
    ] = False,
    config: Annotated[
        Optional[Path],
        Option(
            "--config",
            help="Optional, explicit path to configuration file.",
            exists=True,
            resolve_path=True,
            dir_okay=False,
        ),
    ] = None,
    context: CLIContext,
) -> None:
    if version:
        write(__version__)
        raise Exit()

    ensure_event_loop()
    config = get_config_path(config)
    context.meta["config_path"] = config


@router.command()
async def run(
    addresses: Annotated[
        Sequence[AddressSelector] | None,
        CLIArgument(list[str] | None, help="Addresses of components to start on startup."),
    ] = None,
    *,
    watch: Annotated[
        bool,
        CLIOption(bool, help="Automatically restart the application on code changes."),
    ] = False,
    context: CLIContext,
) -> None:
    """
    Start the engine as a foreground process.
    """
    config_path = await use_config_path(context)
    await _run(addresses or [], config_path=config_path, watch=watch)


async def _run(addresses: Sequence[AddressSelector], *, config_path: Path, watch: bool) -> None:
    address = AddressSelector(addresses) if addresses else None

    try:
        if watch:
            set_current_process_name("ceres-watch")
            await _run_watch(address, config_path=config_path)
        else:
            set_current_process_name("ceres")
            match Config.read(config_path):
                case Ok():
                    pass
                case Fail(errors):
                    raise CLICommandFailed(
                        f"Failed to load configuration. {jsonify(Fail(errors), indent=2)}"
                    )

            engine = Engine(config_path)
            match await engine.load():
                case Ok():
                    pass
                case Fail() as fail:
                    raise CLICommandFailed(
                        f"Failed to load configuration. {jsonify(fail, indent=2)}"
                    )

            exiting = AsyncEvent()

            async def run() -> None:
                engine.start()
                if address is not None:
                    for component in engine.get_components(address):
                        component.system.start()

                await engine.wait_until_stopped()

            async def main() -> None:
                task_run = asyncio.create_task(run())
                task_exit = asyncio.create_task(exiting.wait())
                await wait_any(task_run, task_exit)

                try:
                    await engine.stop()
                finally:
                    await cancel(task_run, task_exit)

            def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
                exiting.set()

            with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                await main()
    except Exception as exception:
        raise CLICommandFailed(f"Engine startup failed. {exception}")


def _run_sync(
    address: AddressSelector | None = None,
    *,
    config_path: Path,
    watch: bool,
) -> None:
    syncify(_run)(addresses=[address] if address else [], config_path=config_path, watch=watch)


async def _run_watch(
    address: AddressSelector | None = None,
    *,
    config_path: Path,
) -> None:
    async def main() -> None:
        import importlib.util

        from watchfiles import PythonFilter, awatch
        from watchfiles.run import CombinedProcess, start_process

        ceres = importlib.util.find_spec("ceres")
        assert ceres is not None and ceres.origin is not None

        async def start() -> CombinedProcess:
            target = _run_sync
            kwargs = {
                "address": address,
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
                Path(ceres.origin).parent,
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
                write(f"Restarting, watch mode detected: {strify(info)}")

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

    task = asyncio.create_task(main(), name="main")

    def handle_exit_signal(*args: object, **kwargs: object) -> None:
        task.cancel()

    with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
        try:
            await task
        except CancelledError:
            pass
        finally:
            await cancel(task)


@router.command()
async def check(*, context: CLIContext) -> None:
    """
    Validate project configuration (ceres.yaml) for errors.
    """
    config_path = await use_config_path(context)
    match await Config.load(config_path, log=write):
        case Ok():
            write("All checks passed.")
        case fail:
            raise CLICommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")


@router.command()
async def reload(*, context: CLIContext) -> None:
    """
    Apply configuration changes.
    """

    project = await use_project(context)
    client = Client(project)

    await client.post("/reload")


@router.command()
async def status(
    addresses: Annotated[
        Sequence[AddressSelector] | None,
        CLIArgument(list[str] | None, help="Addresses of components to show the status of."),
    ] = None,
    *,
    context: CLIContext,
) -> None:
    """
    Show engine and component statuses.
    """
    from aiohttp import ClientError

    from ceres._internal.app.api.routes.statuses import GetStatusesQueryParameters

    project = await use_project(context)

    if not addresses:
        addresses = [AddressSelector("all")]

    client = Client(project)
    address = AddressSelector(addresses if addresses else "all")

    try:
        statuses = await client.get(
            "/statuses",
            params=GetStatusesQueryParameters(address=address),
            result=list[Status],
        )
    except ClientError:
        statuses = None

    running = statuses is not None

    with write_table("Engine") as table:
        table.add_column("Configuration")
        table.add_column("Running")
        table.add_column("Port")
        table.add_column("Socket")
        table.add_row(
            str(project.config_path),
            strbool(running),
            str(project.port or "(Disabled)"),
            str(project.socket_path),
        )

    if not running:
        return

    with write_table("Components") as table:
        table.add_column("Address")
        table.add_column("Running")
        table.add_column("Enabled")
        for status in statuses:
            table.add_row(
                status.address,
                strbool(status.running),
                strbool(status.enabled if status.enabled is not None else False),
            )


@router.command()
async def start(
    addresses: Annotated[
        Sequence[AddressSelector],
        CLIArgument(list[str], help="Addresses of components to start."),
    ],
    *,
    context: CLIContext,
) -> None:
    """
    Start components at the provided address(s).
    """
    project = await use_project(context)
    client = Client(project)
    address = AddressSelector(addresses or [])
    query = ComponentFilter(address=address)
    from ceres._internal.app.api import StartResult

    result = await client.post("/start", query, result=StartResult)

    write(result)


@router.command()
async def stop(
    addresses: Annotated[
        Sequence[AddressSelector],
        CLIArgument(list[str], help="Addresses of components to stop."),
    ],
    *,
    context: CLIContext,
) -> None:
    """
    Stop components at the provided address(s).
    """
    project = await use_project(context)
    client = Client(project)
    address = AddressSelector(addresses)
    query = ComponentFilter(address=address)
    from ceres._internal.app.api import StopResult

    result = await client.post("/stop", query, result=StopResult)

    write(result)


@router.command()
async def enable(
    addresses: Annotated[
        Sequence[AddressSelector],
        CLIArgument(list[str], help="Addresses of components to enable."),
    ],
    *,
    context: CLIContext,
) -> None:
    """
    Enable components at the provided address(s).
    """
    project = await use_project(context)
    client = Client(project)
    address = AddressSelector(addresses)
    query = ComponentFilter(address=address)
    from ceres._internal.app.api import EnableResult

    result = await client.post("/enable", query, result=EnableResult)

    write(result)


@router.command()
async def disable(
    addresses: Annotated[
        Sequence[AddressSelector],
        CLIArgument(list[str], help="Addresses of components to disable."),
    ],
    *,
    context: CLIContext,
) -> None:
    """
    Disable components at the provided address(s).
    """
    project = await use_project(context)
    client = Client(project)
    address = AddressSelector(addresses)
    query = ComponentFilter(address=address)
    from ceres._internal.app.api import DisableResult

    result = await client.post("/disable", query, result=DisableResult)

    write(result)


@router.command()
async def up(
    addresses: Annotated[
        Sequence[AddressSelector],
        CLIArgument(list[str], help="Addresses of components to start and enable."),
    ],
    *,
    context: CLIContext,
) -> None:
    """
    Start and enable components at the provided address(s).
    """
    project = await use_project(context)
    client = Client(project)
    address = AddressSelector(addresses)
    query = ComponentFilter(address=address)
    from ceres._internal.app.api import UpResult

    result = await client.post("/up", query, result=UpResult)

    write(result)


@router.command()
async def down(
    addresses: Annotated[
        Sequence[AddressSelector],
        CLIArgument(list[str], help="Addresses of components to stop and disable."),
    ],
    *,
    context: CLIContext,
) -> None:
    """
    Stop and disable components at the provided address(s).
    """
    project = await use_project(context)
    client = Client(project)
    address = AddressSelector(addresses)
    query = ComponentFilter(address=address)
    from ceres._internal.app.api import DownResult

    result = await client.post("/down", query, result=DownResult)

    write(result)


def main() -> None:
    router()
