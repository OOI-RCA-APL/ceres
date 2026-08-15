import asyncio
import os
import signal
import sys
from asyncio import CancelledError
from asyncio import Event as AsyncEvent
from collections.abc import Sequence
from pathlib import Path
from typing import Any, override

from pydantic import Field, ValidationError, create_model
from pydantic_settings import (
    BaseSettings,
    CliPositionalArg,
    CliSettingsSource,
    CliSubCommand,
    SettingsConfigDict,
    SettingsError,
)

from ceres.__internal__.cli.development import (
    assign_addresses,
    console_dev_server,
    is_development_build,
)
from ceres.__internal__.cli.shared import (
    CLICommand,
    CLICommandExit,
    CLICommandFailed,
    CLICommandGroup,
    temporary_signal_handler,
    write,
)
from ceres.__internal__.lazy import __lazy_imports__, unlazy
from ceres.__internal__.utilities.exceptions import trace
from ceres.address import AddressSelector
from ceres.concurrency import cancel, el, race, spawn
from ceres.data import to_json
from ceres.error import ComponentCombinedError, Error

with __lazy_imports__(__name__):
    from ceres.engine import Engine

_watching = False
"""
Specifies if the current process is being watched by the parent process by the `--watch` flag, and
ignore the `--watch` flag itself, as it's already being handled.
"""


class RunCommand(CLICommand):
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

    # Offered only from a source checkout, an installed wheel having no source to point at.
    if is_development_build():
        development_source: Path | None = None
        """
        Path to a Ceres source tree, whose console is rebuilt as you edit it and served in place
        of the built-in one.
        """

        development_console_port: int | None = None
        """
        Serve the development console on this port instead of in place of the built-in one, so
        that both are available.
        """

    @override
    async def __run__(self) -> None:
        """Load the configuration and start the engine, optionally in watch mode."""
        config_path = self.use_config_path()
        await _run(
            self.addresses,
            config_path=config_path,
            watch=not _watching and self.watch,
            development_source=getattr(self, "development_source", None),
            development_console_port=getattr(self, "development_console_port", None),
        )


class CheckCommand(CLICommand):
    """
    Validate project configuration (ceres.yaml) for errors.
    """

    @override
    async def __run__(self) -> None:
        """Load and validate the configuration with all checks enabled."""
        from ceres.config import ConfigCheckType

        await self.use_config(checks=ConfigCheckType.all())
        write("All checks passed.")


def _show_validation_error(exception: ValidationError, color: bool | None = None) -> None:
    """Format and print validation errors to stderr, then exit with status 1.

    Args:
        exception: The Pydantic validation error to display.
        color: Whether to enable colorized output. None means auto-detect.
    """
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

        write(f"- {location}: {message}", file=sys.stderr, color=color)

    exit(1)


class BaseMainCommand(BaseSettings, CLICommandGroup):
    """Base class for the top-level CLI command that dispatches to subcommands."""

    model_config = SettingsConfigDict(
        cli_prog_name="ceres",
        case_sensitive=True,
        use_attribute_docstrings=True,
        cli_enforce_required=True,
        cli_exit_on_error=True,
        cli_hide_none_type=True,
        cli_implicit_flags=True,
        cli_kebab_case=True,
        cli_parse_args=True,
        cli_use_class_docs_for_groups=True,
    )

    version: bool = False
    """Show the current Ceres version number and exit."""

    run: CliSubCommand[RunCommand]
    check: CliSubCommand[CheckCommand]

    def __init__(self, args: Sequence[str]) -> None:
        """Initialize the command by parsing the provided CLI arguments.

        Args:
            args: The command-line arguments to parse.
        """
        super().__init__(
            _cli_parse_args=list(args),
            _cli_settings_source=MainCliSettingsSource(type(self), args),
        )

    async def execute(self) -> int:
        """Run the parsed command and return an integer exit code.

        Returns:
            0 on success, 1 on failure or unhandled error.
        """
        try:
            await self.__run__()
            return 0
        except Error as error:
            self.write(to_json(error, indent=2))
            return 1
        except CLICommandExit as exception:
            if exception.message is not None:
                self.write(exception.message)
            return exception.status
        except KeyboardInterrupt, CancelledError:
            self.write("Interrupted. Exiting...")
            return 0
        except BrokenPipeError:
            # A dump piped into something that stops reading, `head` being the usual one,
            # ends where the reader stopped. Standard output is redirected first, because
            # the interpreter flushes it again on the way out and would raise a second
            # time against the same closed pipe.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            return 0

    @override
    async def __run__(self) -> None:
        """Print the version if requested, otherwise delegate to the active subcommand."""
        if self.version:
            from ceres import __version__

            self.write(__version__, sys.stdout)
            return

        await super().__run__()


class MainCliSettingsSource(CliSettingsSource):
    """Custom CLI settings source that adjusts how parsed argument lists are merged."""

    @override
    def _merge_parsed_list(self, parsed_list: list[str], field_name: str) -> str:
        # Work around issue where Pydantic Settings will pass an array with one or more dict
        # elements to dict fields, for whatever reason. Here, just return the last element.
        if field_name in self._cli_dict_args:
            return parsed_list[-1]

        # Otherwise, don't merge anything. This avoids the default behavior where passing a string
        # like "abc,def" to a field of the form `T | Sequence[T]` would parse the value as
        # `["abc", "def"]` instead of "abc,def", which occurs commonly when searching things like
        # messages and alerts which often contain commas.
        return to_json(parsed_list)

    @override
    def __init__(self, settings_cls: type[BaseSettings], args: Sequence[str]) -> None:
        """Initialize the settings source with the given settings class and CLI arguments.

        Args:
            settings_cls: The Pydantic settings class to parse arguments for.
            args: The raw CLI arguments to parse.
        """
        super().__init__(settings_cls, cli_parse_args=list(args))


with __lazy_imports__(__name__):
    from ceres.__internal__.cli.subcommands.database import DatabaseCommand
    from ceres.__internal__.cli.subcommands.generate import GenerateCommand


def main(args: Sequence[str] | None = None) -> int:
    """Serve as the public entry point for the Ceres CLI.

    Args:
        args: CLI arguments to parse. Default to `sys.argv[1:]` when None.

    Returns:
        An integer exit code.
    """
    return _main(args)


def _main(args: Sequence[str] | None = None, *, watching: bool = False) -> int:
    """Parse CLI arguments, build the appropriate command hierarchy, and execute it.

    Args:
        args: CLI arguments to parse. Default to `sys.argv[1:]` when None.
        watching: True when this process was spawned by a watch-mode parent, which suppresses
            re-entering watch mode.

    Returns:
        An integer exit code.
    """
    if args is None:
        args = sys.argv[1:]

    global _watching
    if watching:
        _watching = True

    arguments = [token for token in args if not token.startswith("-")]
    subcommand = arguments[0] if arguments else None
    subcommands = {
        "database": DatabaseCommand,
        "generate": GenerateCommand,
    }

    if subcommand in subcommands:
        subcommands = {subcommand: unlazy(subcommands[subcommand])}
    else:
        subcommands = {name: unlazy(value) for name, value in subcommands.items()}

    fields: dict[str, Any] = {
        name: (CliSubCommand[subcommand], ...) for name, subcommand in subcommands.items()
    }

    from ceres.version import __version__

    MainCommand = create_model(
        "MainCommand",
        **fields,
        __base__=BaseMainCommand,
        __doc__=f"""Ceres CLI Version {__version__}""",
    )

    color = None
    if "--color" in args:
        color = True
    if "--no-color" in args:
        color = False

    try:
        command = MainCommand(args)
    except ValidationError as exception:
        _show_validation_error(exception, color)
        return 1
    except SettingsError as exception:
        write(exception, color=color)
        return 1
    except Exception:
        import traceback

        traceback.print_exc()
        return 1

    return asyncio.run(command.execute(), loop_factory=el)


async def _run(
    addresses: Sequence[AddressSelector],
    *,
    config_path: Path,
    watch: bool,
    development_source: Path | None = None,
    development_console_port: int | None = None,
) -> None:
    """Load and run the engine, optionally restarting on file changes when watch mode is enabled.

    Args:
        addresses: Component address selectors to start on launch.
        config_path: Path to the Ceres configuration file.
        watch: Whether to run in watch mode, restarting on source changes.
        development_source: Root of a Ceres source tree whose console dev server runs alongside the
            engine.
        development_console_port: Port to serve the development console on, leaving the built-in
            one where it is.

    Raises:
        CLICommandFailed: If the engine fails to load or start.
    """
    address = AddressSelector(addresses) if addresses else None

    try:
        if watch:
            _set_current_process_name("ceres-watch")
            await _run_watch(address, config_path=config_path)
        else:
            _set_current_process_name("ceres")

            engine = Engine()
            try:
                await engine.load(config_path)
            except Error as error:
                # Structured errors carry an actionable message, show it instead of a dump.
                message = getattr(error, "message", None) or getattr(error, "reason", None)
                if isinstance(message, str):
                    raise CLICommandFailed(f"Failed to load engine. {message}")

                if isinstance(error, ComponentCombinedError):
                    count = len(error.errors)
                    raise CLICommandFailed(
                        f"Failed to load engine. {count} component error(s) occurred, "
                        "see the log output above."
                    )

                raise CLICommandFailed(
                    f"Failed to load engine with current configuration. {to_json(error, indent=2)}"
                )

            # Decided before the engine starts, since moving it aside means rewriting the
            # server section it is about to bind from.
            development_addresses = assign_addresses(engine.config, development_console_port)

            exiting = AsyncEvent()

            async def main() -> None:
                engine.start()
                if address is not None:
                    for component in engine.get_components(address):
                        component.system.start()

                try:
                    await race(engine.wait_until_stopped(), exiting.wait())
                finally:
                    await engine.stop()

            def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
                exiting.set()

            with temporary_signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
                async with console_dev_server(development_source, development_addresses):
                    await main()
    except Exception as exception:
        if isinstance(exception, CLICommandFailed):
            raise

        # Structured errors carry an actionable message, show it instead of a traceback.
        message = getattr(exception, "message", None) or getattr(exception, "reason", None)
        if isinstance(exception, Error) and isinstance(message, str):
            raise CLICommandFailed(f"Engine startup failed. {message}")

        raise CLICommandFailed(f"Engine startup failed. {trace(exception)}")


async def _run_watch(
    address: AddressSelector | None = None,
    *,
    config_path: Path,
) -> None:
    """Watch for Python and config file changes, restarting the engine process on each change.

    Args:
        address: Optional address selector constraining which components to start.
        config_path: Path to the Ceres configuration file.
    """

    async def main() -> None:
        import importlib.util

        from watchfiles import PythonFilter, awatch
        from watchfiles.run import CombinedProcess, start_process

        ceres = importlib.util.find_spec("ceres")
        assert ceres is not None and ceres.origin is not None

        async def start() -> CombinedProcess:
            return await spawn(
                start_process,
                _main,
                "function",
                (),
                {"args": sys.argv[1:], "watching": True},
            )

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
                write(f"Restarting, watch mode detected: {info}")

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


def _set_current_process_name(name: str) -> None:
    """Attempt to set the OS-visible process name using `setproctitle`, ignoring failures.

    Args:
        name: The desired process name.
    """
    try:
        from setproctitle import setproctitle

        setproctitle(name)
    except Exception:
        pass
