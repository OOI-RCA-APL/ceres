from __future__ import annotations

import asyncio
import json
import signal
import sys
from asyncio import CancelledError
from asyncio import Event as AsyncEvent
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence, override

from pydantic import Field, ValidationError, create_model
from pydantic_settings import (
    BaseSettings,
    CliPositionalArg,
    CliSettingsSource,
    CliSubCommand,
    SettingsConfigDict,
    SettingsError,
)

from ceres._internal import util
from ceres._internal.cli.shared import (
    CliCommand,
    CliCommandFailed,
    CliCommandGroup,
    strbool,
    write,
    write_table,
)
from ceres._internal.lazy import lazy_imports, unlazy
from ceres.address import AddressSelector
from ceres.config import ConfigCheckType
from ceres.data import jsonify
from ceres.error import Failure
from ceres.result import Fail, Ok

with lazy_imports(__name__):
    from ceres._internal.cli.client import Client
    from ceres.component import ComponentFilter
    from ceres.engine import Engine
    from ceres.threading import spawn


class RunCommand(CliCommand):
    """
    Start the engine as a foreground process.
    """

    addresses: CliPositionalArg[list[AddressSelector]] = Field(default_factory=list)
    """
    Addresses of components to run on startup.
    """

    watch: bool = False
    """
    Automatically restart the application on code changes.
    """

    @override
    async def __run__(self) -> None:
        config_path = self.use_config_path()
        await _run(self.addresses, config_path=config_path, watch=self.watch)


class CheckCommand(CliCommand):
    """
    Validate project configuration (ceres.yaml) for errors.
    """

    @override
    async def __run__(self) -> None:
        await self.use_config(checks=ConfigCheckType.all())
        write("All checks passed.")


class ReloadCommand(CliCommand):
    """
    Apply configuration changes.
    """

    @override
    async def __run__(self) -> None:
        client = await self.use_client()
        await client.post("/reload")


class StatusCommand(CliCommand):
    """
    Show engine and component statuses.
    """

    addresses: CliPositionalArg[list[AddressSelector]] = Field(default_factory=list)
    """
    Addresses of components to show the status of.
    """

    @override
    async def __run__(self) -> None:
        from aiohttp import ClientError

        if TYPE_CHECKING:
            from ceres._internal.app.api.routes.statuses import GetStatusesQueryParameters
        else:
            GetStatusesQueryParameters = dict

        if self.addresses:
            addresses = self.addresses
        else:
            addresses = [AddressSelector("all")]

        project = await self.use_loaded_project()
        client = Client(project)
        address = AddressSelector(addresses if addresses else "all")

        try:
            from ceres.status import Status

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
                    str(status.address),
                    strbool(status.running),
                    strbool(status.enabled if status.enabled is not None else False),
                )


class StartCommand(CliCommand):
    """
    Start components at the provided addresses.
    """

    addresses: CliPositionalArg[list[AddressSelector]]
    """
    Addresses of components to start.
    """

    @override
    async def __run__(self) -> Any:
        client = await self.use_client()
        address = AddressSelector(self.addresses)
        query = ComponentFilter(address=address)
        return await client.post("/start", query)


class StopCommand(CliCommand):
    """
    Stop components at the provided addresses.
    """

    addresses: CliPositionalArg[list[AddressSelector]]
    """Addresses of components to stop."""

    @override
    async def __run__(self) -> Any:
        client = await self.use_client()
        address = AddressSelector(self.addresses)
        query = ComponentFilter(address=address)
        return await client.post("/stop", query)


class EnableCommand(CliCommand):
    """
    Enable components at the provided addresses.
    """

    addresses: CliPositionalArg[list[AddressSelector]]
    """Addresses of components to enable."""

    @override
    async def __run__(self) -> Any:
        client = await self.use_client()
        address = AddressSelector(self.addresses)
        query = ComponentFilter(address=address)
        return await client.post("/enable", query)


class DisableCommand(CliCommand):
    """
    Disable components at the provided addresses.
    """

    addresses: CliPositionalArg[list[AddressSelector]]
    """Addresses of components to disable."""

    @override
    async def __run__(self) -> Any:
        client = await self.use_client()
        address = AddressSelector(self.addresses)
        query = ComponentFilter(address=address)
        return await client.post("/disable", query)


class UpCommand(CliCommand):
    """
    Start and enable components at the provided addresses.
    """

    addresses: CliPositionalArg[list[AddressSelector]]
    """Addresses of components to start and enable."""

    @override
    async def __run__(self) -> Any:
        client = await self.use_client()
        address = AddressSelector(self.addresses)
        query = ComponentFilter(address=address)
        return await client.post("/up", query)


class DownCommand(CliCommand):
    """
    Stop and disable components at the provided addresses.
    """

    addresses: CliPositionalArg[list[AddressSelector]]
    """Addresses of components to stop and disable."""

    @override
    async def __run__(self) -> Any:
        client = await self.use_client()
        address = AddressSelector(self.addresses)
        query = ComponentFilter(address=address)
        return await client.post("/down", query)


def _show_validation_error(exception: ValidationError) -> None:
    write("Errors:")

    for error in exception.errors():
        location = error.get("loc")
        if location is not None:
            location = ".".join(str(segment) for segment in location[1:] if "[" not in str(segment))
        else:
            location = "unknown-location"

        message = error.get("msg")
        if message is not None:
            if not message.endswith("."):
                message += "."
        else:
            message = "(unknown-message)"

        value = error.get("input") or "(unknown-value)"

        write(f"- {location} = {value!r}: {message}", file=sys.stderr)

    exit(1)


with lazy_imports(__name__):
    from ceres._internal.cli.subcommands.alerts import AlertsCommand
    from ceres._internal.cli.subcommands.database import DatabaseCommand
    from ceres._internal.cli.subcommands.generate import GenerateCommand
    from ceres._internal.cli.subcommands.logs import LogsCommand
    from ceres._internal.cli.subcommands.messages import MessagesCommand
    from ceres._internal.cli.subcommands.particles import ParticlesCommand
    from ceres._internal.cli.subcommands.service import ServiceCommand
    from ceres._internal.cli.subcommands.settings import SettingsCommand
    from ceres._internal.cli.subcommands.users import UsersCommand
    from ceres._internal.cli.subcommands.variables import VariablesCommand


class BaseMainCommand(BaseSettings, CliCommandGroup):
    model_config = SettingsConfigDict(
        cli_prog_name="ceres",
        case_sensitive=True,
        cli_avoid_json=True,
        cli_enforce_required=True,
        cli_exit_on_error=True,
        cli_hide_none_type=True,
        cli_implicit_flags=True,
        cli_kebab_case=True,
        cli_parse_args=True,
        cli_use_class_docs_for_groups=True,
        enable_decoding=True,
    )

    version: bool = False
    """Show the current Ceres version number and exit."""

    run: CliSubCommand[RunCommand]
    check: CliSubCommand[CheckCommand]
    reload: CliSubCommand[ReloadCommand]
    status: CliSubCommand[StatusCommand]
    start: CliSubCommand[StartCommand]
    stop: CliSubCommand[StopCommand]
    enable: CliSubCommand[EnableCommand]
    disable: CliSubCommand[DisableCommand]
    up: CliSubCommand[UpCommand]
    down: CliSubCommand[DownCommand]

    @override
    async def __execute__(self) -> Any:
        if self.version:
            from ceres import __version__

            return __version__

        return await super().__execute__()

    def __init__(self, args: Sequence[str]) -> None:
        super().__init__(
            _cli_parse_args=list(args),
            _cli_settings_source=MainCliSettingsSource(type(self), args),
        )


class MainCliSettingsSource(CliSettingsSource):
    @override
    def _merge_parsed_list(self, parsed_list: list[str], field_name: str) -> str:
        return json.dumps(parsed_list)  # Don't merge anything.

    @override
    def __init__(self, settings_cls: type[BaseSettings], args: Sequence[str]) -> None:
        super().__init__(settings_cls, cli_parse_args=list(args))


def main(args: Sequence[str] | None = None) -> None:
    if args is None:
        args = sys.argv[1:]

    arguments = [token for token in args if not token.startswith("-")]
    subcommand = arguments[0] if arguments else None
    subcommands = {
        "alerts": AlertsCommand,
        "database": DatabaseCommand,
        "generate": GenerateCommand,
        "logs": LogsCommand,
        "messages": MessagesCommand,
        "particles": ParticlesCommand,
        "service": ServiceCommand,
        "settings": SettingsCommand,
        "users": UsersCommand,
        "variables": VariablesCommand,
    }

    if subcommand in subcommands:
        subcommands = {subcommand: unlazy(subcommands[subcommand])}
    else:
        subcommands = {name: unlazy(value) for name, value in subcommands.items()}

    fields: dict[str, Any] = {
        name: (CliSubCommand[subcommand], ...) for name, subcommand in subcommands.items()
    }

    MainCommand = create_model(
        "MainCommand",
        **fields,
        __base__=BaseMainCommand,
    )

    async def run() -> None:
        try:
            command = MainCommand(args)
        except ValidationError as exception:
            _show_validation_error(exception)
            exit(1)
        except SettingsError as exception:
            write(exception)
            exit(1)

        try:
            result = await command.__execute__()
            if result is not None:
                result = jsonify(result, indent=2)

            write(result, to="stdout")
        except Failure as failure:
            write(jsonify(failure.error, indent=2))
            exit(1)
        except SettingsError as exception:
            write(exception)
            exit(1)
        except KeyboardInterrupt:
            write("Interrupted by user. Exiting...")
            exit(0)

    asyncio.run(run())


async def _run(addresses: Sequence[AddressSelector], *, config_path: Path, watch: bool) -> None:
    address = AddressSelector(addresses) if addresses else None

    try:
        if watch:
            _set_current_process_name("ceres-watch")
            await _run_watch(address, config_path=config_path)
        else:
            _set_current_process_name("ceres")

            engine = Engine()
            match await engine.load(config_path):
                case Ok():
                    pass
                case Fail() as fail:
                    raise CliCommandFailed(
                        f"Failed to load engine with current configuration. {jsonify(fail, indent=2)}"
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
                await util.wait_any(task_run, task_exit)

                try:
                    await engine.stop()
                finally:
                    await util.cancel(task_run, task_exit)

            def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
                exiting.set()

            with _temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                await main()
    except Exception as exception:
        if not isinstance(exception, CliCommandFailed):
            raise CliCommandFailed(f"Engine startup failed. {util.get_traceback(exception)}")
        else:
            raise


def _run_sync(
    address: AddressSelector | None = None,
    *,
    config_path: Path,
    watch: bool,
) -> None:
    util.syncify(_run)(addresses=[address] if address else [], config_path=config_path, watch=watch)


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
                write(f"Restarting, watch mode detected: {util.strify(info)}")

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

    with _temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
        try:
            await task
        except CancelledError:
            pass
        finally:
            await util.cancel(task)


def _set_current_process_name(name: str) -> None:
    try:
        from setproctitle import setproctitle

        setproctitle(name)
    except Exception:
        pass


@contextmanager
def _temporary_signal_handler(signums: Sequence[int], handler: Callable[..., Any]):
    import signal

    loop = util.get_event_loop_or_none()
    originals: dict[int, Any] = {}

    for signum in signums:
        if original := signal.getsignal(signum):
            originals[signum] = original

        if loop is not None:
            loop.add_signal_handler(signum, handler)
        else:
            signal.signal(signum, handler)

    try:
        yield
    finally:
        for signum, original in originals.items():
            signal.signal(signum, original)
