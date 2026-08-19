import os
import sys
import time
import warnings
from abc import abstractmethod
from collections.abc import (
    Callable,
    Iterator,
    Sequence,
)
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import (
    IO,
    Any,
    Literal,
    Self,
    overload,
    override,
)

from pydantic import (
    ConfigDict,
    Field,
    model_validator,
)
from pydantic_settings import (
    SettingsError,
    get_subcommand,
)

from ceres.__internal__.lazy import __lazy_imports__
from ceres.__internal__.project import LoadedProject
from ceres.data import (
    DataModel,
    from_json,
    to_dict,
    to_json,
)
from ceres.error import Error

with __lazy_imports__(__name__):
    from ceres.config import Config, ConfigCheckType, ConfigMeta


def get_confirmation(
    prompt: str,
    default: bool | None = None,
    *,
    abort: bool = False,
) -> bool:
    """Prompt the user for a yes/no confirmation and return the result.

    Args:
        prompt: The question to display to the user.
        default: The default answer when the user presses Enter without typing. None means no
            default.
        abort: If True, raise `CLICommandFailed` when the user declines.

    Returns:
        True if the user confirmed, False otherwise.

    Raises:
        CLICommandFailed: If `abort` is True and the user did not confirm.
    """
    confirmed = False

    while True:
        if default is None:
            default_indicator = "y/n"
        elif default:
            default_indicator = "Y/n"
        else:
            default_indicator = "y/N"

        # A closed stdin cannot consent, so it declines cleanly instead of crashing.
        try:
            text = input(f"{prompt} ({default_indicator}): ").lower()
        except EOFError:
            sys.stdout.write("\n")
            confirmed = False
            break

        if default is not None and text == "":
            confirmed = default
            break
        if text in ("yes", "y"):
            confirmed = True
            break
        if text in ("no", "n"):
            confirmed = False
            break

    if abort and not confirmed:
        raise CLICommandFailed("Aborted.")

    return confirmed


def _compute_color_enabled_by_variables() -> bool | None:
    """Check `NO_COLOR` and `FORCE_COLOR` environment variables and return the implied setting."""
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR") is not None:
        return True

    return None


_color_enabled_by_variables: bool | None = _compute_color_enabled_by_variables()
_color_enabled_checked = time.time()


def _get_color_enabled_by_variables() -> bool | None:
    """Return the cached color-enabled state, refreshing from environment variables periodically."""
    global _color_enabled_by_variables
    global _color_enabled_checked

    now = time.time()
    if now - _color_enabled_checked > 1:
        _color_enabled_by_variables = _compute_color_enabled_by_variables()
        _color_enabled_checked = now

    _color_enabled_by_variables = _compute_color_enabled_by_variables()
    return _color_enabled_by_variables


def write(
    value: object,
    file: IO[str] = sys.stderr,
    end: str = "\n",
    flush: bool = False,
    color: bool | None = None,
):
    """Write a value to the given file stream, optionally with Rich colorized output.

    Args:
        value: The value to print.
        file: The output stream. Defaults to stderr.
        end: The string appended after the value. Defaults to newline.
        flush: Whether to flush the stream after writing.
        color: Explicitly enable or disable color. None means auto-detect from the terminal and
            environment variables.
    """
    interactive = file.isatty() if file else None
    if color is None:
        color_enabled_by_variables = _get_color_enabled_by_variables()
        if color_enabled_by_variables is not None:
            color = color_enabled_by_variables
        else:
            color = interactive

    if color:
        import rich

        printer = rich.print
    else:
        printer = print

    printer(value, end=end, file=file, flush=flush)


_write = write


@contextmanager
def write_progress(file: IO[str] = sys.stderr):
    """Create a Rich progress context that draws itself while the block runs.

    A task is a list of pieces of work that finish one after another, drawn as a spinner,
    what is running now, and how far through the list it is. There is no bar, because a
    bar of whole steps only redraws the count beside it in a second shape, and nothing
    here can see inside a step to fill one smoothly. The spinner carries that something is
    happening and becomes a check when the list is done.

    Nothing is drawn when the stream is not a terminal, so a redirected or piped run
    writes its lines and no control codes.

    Args:
        file: The output stream to draw on. Defaults to stderr.

    Yields:
        A `rich.progress.Progress` to add tasks to.
    """
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    interactive = file.isatty() if file else False
    with Progress(
        SpinnerColumn(finished_text="[green]✓[/green]"),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.fields[note]}"),
        console=Console(file=file, force_terminal=interactive or None),
        disable=not interactive,
        transient=False,
    ) as progress:
        yield progress


@contextmanager
def write_table(title: str | None = None, file: IO[str] = sys.stderr):
    """Create a Rich table context that prints itself on exit.

    Args:
        title: Optional table title.
        file: The output stream to write the rendered table to. Defaults to stderr.

    Yields:
        A `rich.table.Table` instance to populate with columns and rows.
    """
    import rich.box
    from rich.table import Table

    table = Table(title=title, box=rich.box.ROUNDED, title_justify="left")
    yield table
    write(table, file)


def strbool(value: bool) -> str:
    """Convert a boolean to "Yes" or "No"."""
    return "Yes" if value else "No"


chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    """Replacement for `os.chdir` that emits a warning instead of changing directories."""
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    """Replace `os.chdir` with a no-op that warns, preventing further directory changes."""
    os.chdir = __disabled_chdir__


class CLICommand(DataModel):
    """Base class for all CLI commands, providing shared configuration and utility methods."""

    model_config = ConfigDict(defer_build=True)

    config_path: Path | None = Field(default=None, alias="config")
    """
    Use a specific Ceres configuration file, possibly outside the current working directory.
    """

    color: bool | None = None
    """Enable or disable colorized output."""

    @model_validator(mode="after")
    def _globals(self) -> Self:
        """Propagate shared options (color, config_path) upward from nested subcommands."""
        subcommands = self.get_subcommands()
        for command in subcommands:
            if self.color is None and command.color is not None:
                self.color = command.color
            if self.config_path is None and command.config_path is not None:
                self.config_path = command.config_path

        return self

    def get_subcommands(self, output: list[CLICommand] | None = None) -> list[CLICommand]:
        """Collect and return all nested `CLICommand` instances from this command's fields.

        Args:
            output: An optional list to append results to. A new list is created when None.

        Returns:
            A list of `CLICommand` instances found in this command's field values.
        """
        if output is None:
            output = []

        for value in to_dict(self).values():
            if isinstance(value, CLICommand):
                output.append(value)

        return output

    @abstractmethod
    async def __run__(self) -> None:
        """Execute the command logic. Subclasses must implement this method."""
        ...

    @overload
    def use_config_path(self, required: Literal[True] = True) -> Path: ...

    @overload
    def use_config_path(self, required: Literal[False]) -> Path | None: ...

    def use_config_path(self, required: bool = True) -> Path | None:
        """Locate the project config file, set the working directory, and return the resolved path.

        Search for `ceres.yaml`, `ceres.yml`, or `ceres.json` in the current directory when no
        explicit path is configured. Change the working directory to the config file's parent and
        disable further `os.chdir` calls.

        Args:
            required: If True, raise `CLICommandFailed` when no config file is found.

        Returns:
            The absolute path to the configuration file, or None if not found and not required.

        Raises:
            CLICommandFailed: If required is True and no configuration file can be located.
        """
        config_path: Path | None = self.config_path

        POSSIBLE_CONFIG_NAMES = [
            "ceres.yaml",
            "ceres.yml",
            "ceres.json",
        ]

        if config_path is None:
            possibilities = [Path(name) for name in POSSIBLE_CONFIG_NAMES]

            config_path: Path | None = None

            for possibility in possibilities:
                if possibility.is_file():
                    config_path = possibility
                    break

        if config_path is None:
            if not required:
                return None

            raise CLICommandFailed(
                f"Must be in a directory containing one of: {POSSIBLE_CONFIG_NAMES}"
            )

        config_path = config_path.absolute()
        chdir(config_path.parent)
        disable_chdir()
        sys.path.insert(0, str(config_path.parent))
        return config_path

    async def use_config_meta(
        self,
        checks: Sequence[ConfigCheckType] = (),
    ) -> ConfigMeta:
        """Load and return the configuration metadata, running the specified validation checks.

        Args:
            checks: Validation checks to run against the configuration.

        Returns:
            The loaded `ConfigMeta` instance.

        Raises:
            CLICommandFailed: If the configuration fails to load or validate.
        """
        try:
            return await ConfigMeta.load(self.use_config_path(), checks=checks)
        except Error as error:
            error = to_json(error, indent=2)
            raise CLICommandFailed(f"Failed to load configuration. {error}")

    async def use_config(self, checks: Sequence[ConfigCheckType] = ()) -> Config:
        """Load and return the full project configuration, running the specified validation checks.

        Args:
            checks: Validation checks to run against the configuration.

        Returns:
            The loaded `Config` instance.

        Raises:
            CLICommandFailed: If the configuration fails to load or validate.
        """
        try:
            return await Config.load(self.use_config_path(), checks=checks)
        except Error as error:
            error = to_json(error, indent=2)
            raise CLICommandFailed(f"Failed to load configuration. {error}")

    async def use_loaded_project(self, checks: Sequence[ConfigCheckType] = ()) -> LoadedProject:
        """Load and return the project with validated configuration metadata.

        Args:
            checks: Validation checks to run against the configuration.

        Returns:
            A `LoadedProject` with resolved config path and loaded metadata.
        """
        config_path = self.use_config_path()
        config_meta = await self.use_config_meta(checks)
        return LoadedProject(config_path, config_meta)

    def write(
        self,
        value: object,
        file: IO[str] = sys.stderr,
        *,
        end: str = "\n",
        flush: bool = False,
        color: bool | None = None,
    ) -> None:
        """Write a value to the output stream, inheriting the command's color preference.

        Args:
            value: The value to print.
            file: The output stream. Defaults to stderr.
            end: The string appended after the value. Defaults to newline.
            flush: Whether to flush the stream after writing.
            color: Override for color output. Falls back to the command's `color` setting.
        """
        if color is None:
            color = self.color

        _write(value, file=file, end=end, flush=flush, color=color)

    async def put(self, data: object, file: IO[str] = sys.stdout) -> None:
        """Write one result object to the output stream as JSON.

        Args:
            data: The result to output. None writes nothing.
            file: The output stream. Defaults to stdout.
        """
        if data is not None:
            self.write(_json_stringify(data), file=file)

    @asynccontextmanager
    async def use_database(
        self,
        *,
        require_initialized: bool = True,
        require_connect: bool = True,
    ):
        """Open a database connection from the project config and yield it as a context manager.

        Args:
            require_initialized: If True, verify the database has been initialized before yielding.
            require_connect: If True, test the connection before yielding.

        Yields:
            A connected `Database` instance.

        Raises:
            CLICommandFailed: If the connection fails or the database is uninitialized when
                required.
        """
        from ceres.database import Database

        config = await self.use_config_meta()
        database = Database(config.database)

        if require_connect:
            if not await database.ping():
                raise CLICommandFailed("Failed to connect to database.")

            if require_initialized:
                if not await database.initialized():
                    raise CLICommandFailed("Database appears uninitialized, exiting.")

                try:
                    await database.assert_schema_current()
                except Error as error:
                    message = getattr(error, "message", None)
                    raise CLICommandFailed(
                        message
                        or "Database schema is out of date. Run `ceres database migrate` to update it."
                    )

        async with database:
            yield database


def _json_stringify(value: object) -> str:
    """Serialize a value to a JSON string."""
    return to_json(value)


class CLICommandGroup(CLICommand):
    """A CLI command that delegates execution to an active subcommand."""

    @override
    async def __run__(self) -> None:
        """Find the active subcommand and execute it."""
        subcommand = get_subcommand(self, cli_exit_on_error=True)
        if isinstance(subcommand, CLICommand):
            await subcommand.__run__()


class CLICommandExit(SettingsError):
    """Exception that signals the CLI should exit with a specific status code and optional message."""

    def __init__(self, status: int = 0, message: str | None = None) -> None:
        """Initialize the exit exception.

        Args:
            status: The process exit code. 0 indicates success.
            message: An optional message to display before exiting.
        """
        if message is not None:
            try:
                content = from_json(message)
                message = to_json(content, indent=2)
            except Exception:
                if not isinstance(message, str):
                    try:
                        message = to_json(message, indent=2)
                    except Exception:
                        message = str(message)

        self.message: str | None = message
        self.status: int = status

    @override
    def __str__(self) -> str:
        """Return the exit message, prefixed with "Error: " for non-zero exit codes."""
        text = (self.message or "").strip()
        if text and self.status != 0:
            if not text.startswith("Error: "):
                text = f"Error: {text}"

        return text


class CLICommandFailed(CLICommandExit):
    """Exception indicating a CLI command failed with a non-zero exit status."""

    def __init__(self, message: str) -> None:
        """Initialize with exit status 1 and the given error message.

        Args:
            message: A description of the failure.
        """
        super().__init__(1, message)


@contextmanager
def temporary_signal_handler(signums: Sequence[int], handler: Callable[..., Any]) -> Iterator[None]:
    """Temporarily install a signal handler for the given signals, restoring originals on exit.

    Args:
        signums: The signal numbers to intercept.
        handler: The handler function to install for each signal.

    Yields:
        Nothing. The original handlers are restored when the context exits.
    """
    import signal

    originals: dict[int, Any] = {}

    for signum in signums:
        if original := signal.getsignal(signum):
            originals[signum] = original

        signal.signal(signum, handler)

    try:
        yield
    finally:
        for signum, original in originals.items():
            signal.signal(signum, original)
