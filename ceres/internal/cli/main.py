import asyncio
import signal
from asyncio import CancelledError
from asyncio import Event as AsyncEvent
from pathlib import Path
from typing import Annotated, Any, Mapping, TypeVar

from click import ParamType
from pydantic import BaseModel
from typer import Argument, Option

from ceres.address import AddressSelector
from ceres.config import Config
from ceres.data import jsonify, simplify
from ceres.engine import Engine
from ceres.exceptions import EngineException
from ceres.filter import ComponentFilter
from ceres.internal import logs
from ceres.internal.cli.exceptions import (
    CLIEngineNotRunningException,
    CLIInvalidConfigException,
    CLIStartupException,
)
from ceres.internal.cli.shared import (
    CLIRouter,
    ConfigPathOption,
    ProjectOption,
    strbool,
    write,
    write_table,
)
from ceres.internal.cli.subcommands.database import router as database
from ceres.internal.cli.subcommands.service import router as service
from ceres.internal.project import Project
from ceres.internal.utilities import (
    cancel,
    ensure_event_loop,
    get_type_adapter,
    set_current_process_name,
    strify,
    syncify,
    temporary_signal_handler,
    wait_any,
)
from ceres.object import Status
from ceres.result import Fail, Ok
from ceres.threading import spawn
from ceres.version import __version__

router = CLIRouter(
    name="ceres",
    help=f"Ceres CLI — Package Version {__version__}",
)

router.add_typer(database)
router.add_typer(service)


@router.command()
def version() -> None:
    """
    Show the current Ceres version number.
    """
    write(__version__)


@router.command()
async def run(
    *,
    config_path: Path = ConfigPathOption(),
    all: bool = False,
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
            await _run_watch(config_path=config_path, all=all)
        else:
            set_current_process_name("ceres")
            server = Engine(config_path)
            match await server.load():
                case Ok():
                    pass
                case Fail() as fail:
                    raise CLIInvalidConfigException(
                        f"Failed to load configuration. {jsonify(fail, indent=2)}"
                    )

            exiting = AsyncEvent()

            async def run() -> None:
                server.start()
                if all:
                    server.get_components().start()

                await server.wait_until_stopped()

            async def main() -> None:
                task_run = asyncio.create_task(run())
                task_exit = asyncio.create_task(exiting.wait())
                await wait_any(task_run, task_exit)

                try:
                    await server.stop()
                finally:
                    await cancel(task_run, task_exit)

            def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
                exiting.set()

            with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                await main()
    except EngineException as exception:
        raise CLIStartupException(f"Engine startup failed. {exception.message}")


@router.command()
async def check(*, config_path: Path = ConfigPathOption()) -> None:
    """
    Validate project configuration (ceres.yaml) for errors.
    """
    match await Config.load(config_path, log=write):
        case Ok():
            write("All checks passed.")
        case fail:
            raise CLIInvalidConfigException(
                f"Failed to load configuration. {jsonify(fail, indent=2)}"
            )


@router.callback()
def setup() -> None:
    ensure_event_loop()
    logs.setup()


def _run_sync(
    *,
    config_path: Path,
    watch: bool,
    all: bool,
) -> None:
    syncify(run)(config_path=config_path, watch=watch, all=all)


async def _run_watch(
    *,
    config_path: Path,
    all: bool,
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
                "config_path": config_path,
                "watch": False,
                "all": all,
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


_T = TypeVar("_T")


class APIClient:
    def __init__(self, project: Project) -> None:
        self.project = project

    async def online(self) -> bool:
        try:
            await self.get("/status", result=Status)
        except Exception:
            return False

        return True

    async def request(
        self,
        method: str,
        path: str,
        *,
        data: object = None,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[_T],
    ) -> _T:
        path = "/api/" + path.lstrip("/")
        path = f"http+unix://{str(self.project.socket_path).replace('/', '%2F')}{path}"

        if isinstance(params, BaseModel):
            params = {
                key: str(value) for key, value in params.model_dump(exclude_defaults=True).items()
            }

        from aiohttp import ClientSession, UnixConnector

        async with ClientSession(connector=UnixConnector(str(self.project.socket_path))) as session:
            async with session.request(
                method,
                path,
                json=simplify(data),
                params=params,
            ) as response:
                return get_type_adapter(result).validate_python(await response.json())

    async def get(
        self,
        path: str,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        result: type[_T],
    ) -> _T:
        return await self.request("GET", path, params=params, result=result)

    async def post(
        self,
        path: str,
        data: object | None = None,
        *,
        params: BaseModel | Mapping[str, object] | None = None,
        parse: type[_T] = Any,
    ) -> _T:
        return await self.request("POST", path, data=data, params=params, result=parse)


@router.command()
async def reload(*, project: Project = ProjectOption()) -> None:
    """
    Apply configuration changes.
    """
    from aiohttp import ClientError

    client = APIClient(project)

    try:
        await client.post("/reload")
    except ClientError:
        raise CLIEngineNotRunningException("Engine is not running or not accessible at the moment.")


class AddressPatternParser(ParamType):
    name = "AddressPattern"

    def convert(self, value: str, param: object, ctx: object) -> AddressSelector:
        return AddressSelector(value)


AddressPatternInput = Annotated[
    AddressSelector,
    Argument(click_type=AddressPatternParser()),
]


@router.command()
async def status(
    addresses: list[str] = Argument(
        None,
        help="Addresses of components to show the status of.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Show engine and component statuses.
    """
    from aiohttp import ClientError

    from ceres.internal.app import GetStatusesQueryParameters

    if not addresses:
        addresses = [":all"]

    client = APIClient(project)
    address = AddressSelector("|".join(addresses) if addresses else ":all")

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
                strbool(status.enabled),
            )


@router.command()
async def start(
    addresses: list[str] = Argument(
        help="Addresses of components to start.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Start components at the provided address(s).
    """
    client = APIClient(project)
    address = AddressSelector("|".join(addresses))
    query = ComponentFilter(address=address)
    from ceres.internal.app import StartResult

    result = await client.post("/start", query, parse=StartResult)

    write(result)


@router.command()
async def stop(
    addresses: list[str] = Argument(
        help="Addresses of components to stop.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Stop components at the provided address(s).
    """
    client = APIClient(project)
    address = AddressSelector("|".join(addresses))
    query = ComponentFilter(address=address)
    from ceres.internal.app import StopResult

    result = await client.post("/stop", query, parse=StopResult)

    write(result)


@router.command()
async def enable(
    addresses: list[str] = Argument(
        help="Addresses of components to enable.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Enable components at the provided address(s).
    """
    client = APIClient(project)
    address = AddressSelector("|".join(addresses))
    query = ComponentFilter(address=address)
    from ceres.internal.app import EnableResult

    result = await client.post("/enable", query, parse=EnableResult)

    write(result)


@router.command()
async def disable(
    addresses: list[str] = Argument(
        help="Addresses of components to disable.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Disable components at the provided address(s).
    """
    client = APIClient(project)
    address = AddressSelector("|".join(addresses))
    query = ComponentFilter(address=address)
    from ceres.internal.app import DisableResult

    result = await client.post("/disable", query, parse=DisableResult)

    write(result)


@router.command()
async def up(
    addresses: list[str] = Argument(
        help="Addresses of components to start and enable.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Start and enable components at the provided address(s).
    """
    client = APIClient(project)
    address = AddressSelector("|".join(addresses))
    query = ComponentFilter(address=address)
    from ceres.internal.app import UpResult

    result = await client.post("/up", query, parse=UpResult)

    write(result)


@router.command()
async def down(
    addresses: list[str] = Argument(
        help="Addresses of components to stop and disable.",
    ),
    *,
    project: Project = ProjectOption(),
) -> None:
    """
    Stop and disable components at the provided address(s).
    """
    client = APIClient(project)
    address = AddressSelector("|".join(addresses))
    query = ComponentFilter(address=address)
    from ceres.internal.app import DownResult

    result = await client.post("/down", query, parse=DownResult)

    write(result)
