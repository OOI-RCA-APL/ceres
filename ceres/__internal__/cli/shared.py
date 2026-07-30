import os
import sys
import time
import warnings
from abc import abstractmethod
from collections.abc import (
    AsyncIterable,
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Sized,
)
from contextlib import AbstractAsyncContextManager, asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta
from enum import StrEnum
from os import PathLike
from pathlib import Path
from types import NoneType
from typing import (
    IO,
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    Self,
    cast,
    overload,
    override,
)
from uuid import UUID

from aiohttp import ClientError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    FilePath,
    Json,
    NewPath,
    TypeAdapter,
    ValidationError,
    create_model,
    model_validator,
)
from pydantic_settings import (
    CliImplicitFlag,
    CliSubCommand,
    NoDecode,
    SettingsError,
    get_subcommand,
)
from pydantic_settings.sources import CliPositionalArg

from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.lazy import __lazy_imports__
from ceres.__internal__.project import LoadedProject, Project
from ceres.__internal__.utilities.case import ucamelcase
from ceres.__internal__.utilities.collections import seq
from ceres.data import (
    DataModel,
    DataObject,
    FromYAML,
    MaybeSequence,
    adapt,
    from_json,
    to_dict,
    to_json,
    validate_json,
)
from ceres.database import DatabaseType
from ceres.entity import EntityType
from ceres.error import Error

with __lazy_imports__(__name__):
    from ceres.__internal__.cli.client import Client
    from ceres.config import Config, ConfigCheckType, ConfigMeta
    from ceres.engine import Engine


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

        text = input(f"{prompt} ({default_indicator}): ").lower()
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


@overload
def get_input[T](
    prompt: str,
    parser: type[T],
    default: T | None = None,
    *,
    hidden: bool = False,
) -> T: ...


@overload
def get_input(
    prompt: str,
    parser: Any,
    default: Any | None = None,
    *,
    hidden: bool = False,
) -> Any: ...


def get_input(
    prompt: str,
    parser: Any,
    default: Any | None = None,
    *,
    hidden: bool = False,
) -> Any:
    """Prompt the user for input and validate it against the given type.

    Repeat the prompt until the user provides a valid value or accepts the default.

    Args:
        prompt: The label to display before the input cursor.
        parser: A type or type expression used to validate the input via Pydantic.
        default: A default value returned when the user submits an empty string.
        hidden: If True, hide the input (useful for passwords).

    Returns:
        The validated input value.
    """
    from getpass import getpass

    prompter = getpass if hidden else input

    while True:
        if default:
            text = prompter(f"{prompt} ({default}): ")
        else:
            text = prompter(f"{prompt}: ")

        if text == "":
            if default is not None:
                return default

            if isinstance(parser, type):
                if issubclass(parser, bool | int | float):
                    continue

        try:
            return TypeAdapter(parser).validate_python(text)
        except ValidationError:
            pass


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


Confirm = Annotated[CliImplicitFlag[bool], Field(description="Ask before executing.")]


def _validate_non_empty(value: object) -> object:
    """Validate that a sized value is not empty, raising an assertion error otherwise."""
    if isinstance(value, Sized):
        assert len(value) > 0, "cannot not be empty"

    return value


type NonEmpty[T] = Annotated[T, AfterValidator(_validate_non_empty)]

type Assign[T: Mapping[str, Any] = Mapping[str, Any]] = Annotated[
    NonEmpty[FromYAML[T]],
    NoDecode,
    Field(description="Field(s) to assign, passed as a non-empty JSON or YAML object."),
]


chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    """Replacement for `os.chdir` that emits a warning instead of changing directories."""
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    """Replace `os.chdir` with a no-op that warns, preventing further directory changes."""
    os.chdir = __disabled_chdir__


class CLIDataFormat(StrEnum):
    """Supported output data formats for CLI data commands."""

    JSON = "json"
    CSV = "csv"


class CLIDataConflict(StrEnum):
    """Strategies for handling primary key conflicts during data loading."""

    ERROR = "error"
    IGNORE = "ignore"
    UPDATE = "update"


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

    async def use_project(self) -> Project:
        """Create and return a `Project` instance from the resolved config path."""
        config_path = self.use_config_path()
        return Project(config_path)

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

    async def use_client(self) -> Client:
        """Create and return a `Client` connected to the running CLI server."""
        project = await self.use_loaded_project()
        return Client(project)

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

    async def put(
        self,
        data: object,
        file: IO[str] = sys.stdout,
        *,
        end: str = "\n",
        flush: bool = False,
        color: bool | None = None,
        data_format: CLIDataFormat | None = None,
        fields: Sequence[str] | Mapping[str, str] | None = None,
    ) -> None:
        """Write structured data to the output stream in the specified format.

        Handle scalars, async iterables, and async context managers that yield iterables. When
        `data_format` is CSV and the value is not atomic, extract fields and write a header row
        before data rows.

        Args:
            data: The data to output. May be a scalar, async iterable, or async context manager.
            file: The output stream. Defaults to stdout.
            end: The string appended after each value. Defaults to newline.
            flush: Whether to flush the stream after writing.
            color: Override for color output.
            data_format: The serialization format. Defaults to JSON.
            fields: Optional field names (or name-to-alias mappings) to include in output.
        """
        if data_format is None:
            data_format = CLIDataFormat.JSON
        if fields is not None and not isinstance(fields, Mapping):
            fields = {field: field for field in fields}

        def write(value: object) -> None:
            self.write(value, file=file, end=end, flush=flush, color=color)

        match data_format:
            case CLIDataFormat.JSON:

                def output(value: object) -> None:
                    if value is None:
                        return

                    if fields is not None:
                        value = _extract(value, fields)

                    write(_json_stringify(value))
            case CLIDataFormat.CSV:
                import csv

                writer = csv.writer(_CallbackWriter(write), lineterminator="")
                started = False

                def output(value: object) -> None:
                    nonlocal started

                    if value is None:
                        return

                    if _is_csv_atomic(value) and fields is None:
                        write(_csv_stringify(value))
                    else:
                        value = _extract(value, fields)
                        if not started:
                            writer.writerow(value.keys())

                        writer.writerow([_csv_stringify(current) for current in value.values()])

                    started = True

        if isinstance(data, AbstractAsyncContextManager):
            async with data as values:
                if isinstance(values, AsyncIterable):
                    async for current in values:
                        output(current)
        elif isinstance(data, AsyncIterable):
            async for current in data:
                output(current)
        else:
            output(data)

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
            try:
                async with database.connect():
                    pass
            except Exception as exception:
                raise CLICommandFailed(f"Failed to connect to database: {exception}")

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

    async def use_temporary_engine(self):
        """Create a silently-loaded engine instance for one-off operations."""
        config_path = self.use_config_path()
        engine = Engine()
        await engine.load(config_path, silent=True)
        return engine

    def read[T: DataObject | BaseModel](self, data_object_class: type[T]) -> T:
        """Convert this command's fields into an instance of the given data object class.

        Create an intermediate model that ignores extra fields (present on the command but absent
        from the target class) and validate through it to produce a clean instance.

        Args:
            data_object_class: The target Pydantic model or data object class.

        Returns:
            A validated instance of `data_object_class` populated from this command's data.
        """
        # We do this hackery here with an intermediate class because commands inheriting from
        # `BaseEntityFilter` can contain instances of themselves in their `and__` and `or__` fields.
        # All of these instances are instances of the command type, rather than the filter type, and
        # so need to be converted to `model_cls` too. All these instances contain extra fields
        # `model_cls` does not have, and in the usual case that `model_cls` does not allow extra
        # inputs, we need to create an intermediate model class that does in order to strip extra
        # fields out, but preserve the defaults the command class has set on itself.
        config = ConfigDict(extra="ignore")
        if not issubclass(data_object_class, BaseModel):

            class IgnoreExtra(data_object_class, config=config):
                pass
        else:

            class IgnoreExtra(data_object_class):
                model_config = config

        # If only we could pass `extra = "ignore"` to the validation method itself, but we can't.
        intermediate = validate_json(IgnoreExtra, to_json(self))
        # Convert the `IgnoreExtra` instance with exactly matching fields into `model_cls`.
        return validate_json(data_object_class, to_json(intermediate))

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


class _CallbackWriter:
    """Adapter that wraps a callback function to look like a writable file object."""

    __slots__ = ("callback",)

    def __init__(self, callback: Callable[[str], None]) -> None:
        """Initialize with the callback to invoke on each write.

        Args:
            callback: A function that accepts a string to write.
        """
        self.callback = callback

    def write(self, text: str) -> None:
        """Forward the text to the wrapped callback."""
        self.callback(text)


_CSV_ATOMIC_STRINGIFIERS: dict[type, Callable[[Any], str]] = {
    NoneType: lambda value: "",
    str: lambda value: value,
    int: to_json,
    float: to_json,
    bool: to_json,
    bytes: lambda value: value.decode("latin-1"),
    bytearray: lambda value: value.decode("latin-1"),
    datetime: lambda value: to_json(value)[1:-1],
    timedelta: lambda value: to_json(value)[1:-1],
    date: lambda value: to_json(value)[1:-1],
    UUID: lambda value: str(value),
}

_CSV_STRINGIFIERS: dict[type, Callable[[Any], str]] = {
    **_CSV_ATOMIC_STRINGIFIERS,
    list: to_json,
    dict: to_json,
    tuple: to_json,
    set: to_json,
    frozenset: to_json,
}


def _is_csv_atomic(value: object) -> bool:
    """Return True if the value can be represented as a single CSV cell without extraction."""
    if isinstance(value, str):
        return True

    return type(value) in _CSV_ATOMIC_STRINGIFIERS


def _csv_stringify(value: object) -> str | None:
    """Convert a value to its CSV string representation, or return None for None values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value

    stringify = _CSV_STRINGIFIERS.get(type(value))
    if stringify is not None:
        return stringify(value)
    if isinstance(value, Collection):
        return to_json(value)

    return str(value)


def _json_stringify(value: object) -> str:
    """Serialize a value to a JSON string."""
    return to_json(value)


_EMPTY_DICT = {}


def _extract(obj: object, fields: Mapping[str, str] | None = None) -> Mapping[str, object]:
    """Extract a mapping of field values from an object, optionally filtering and aliasing fields.

    Args:
        obj: The object to extract fields from.
        fields: An optional mapping of field names to output aliases. When None, return all
            instance attributes.

    Returns:
        A mapping of (possibly aliased) field names to their values.
    """
    if fields is None:
        # A data object declares its fields on the model, and its values can live in
        # native storage rather than instance attributes, so the model is the
        # authority on what a row holds.
        model_fields = getattr(type(obj), "__pydantic_fields__", None)
        if model_fields:
            return {name: getattr(obj, name) for name in model_fields}

        __dict__ = getattr(obj, "__dict__", None)
        if __dict__:
            return __dict__

        __slots__ = getattr(obj, "__slots__", None)
        if __slots__ is not None:
            return {slot: getattr(obj, slot) for slot in __slots__}

        return _EMPTY_DICT

    cls: dict[str, object] = getattr(obj.__class__, "__dict__")
    return {
        alias: getattr(obj, field, None) if field not in cls else None
        for field, alias in fields.items()
    }


def _resolve_fields(fields: Sequence[str] | Mapping[str, str] | None) -> Mapping[str, str] | None:
    """Normalize a field specification into a name-to-alias mapping.

    Parse colon-separated `field:alias` strings in sequences. Pass through mappings unchanged.

    Args:
        fields: A sequence of field specs, a mapping, or None.

    Returns:
        A mapping of field names to aliases, or None if the input is None.
    """
    if fields is not None and not isinstance(fields, Mapping):
        mapping: dict[str, str] = {}
        for i, field in enumerate(fields):
            if ":" in field:
                field, alias = field.split(":", 1)
                mapping[field] = alias
            else:
                mapping[field] = field

        return mapping

    return fields


def _resolve_data_format(path: Path, data_format: CLIDataFormat | None = None) -> CLIDataFormat:
    """Return the data format, inferring it from the file extension if not explicitly provided.

    Args:
        path: The file path whose extension is used for inference.
        data_format: An explicitly specified format that takes precedence over inference.

    Returns:
        The resolved `CLIDataFormat`.

    Raises:
        CLICommandFailed: If the format cannot be inferred from the file extension.
    """
    if data_format is not None:
        return data_format
    if path.suffix in (".json", ".jsonl", ".ndjson", ".txt"):
        return CLIDataFormat.JSON
    elif path.suffix == ".csv":
        return CLIDataFormat.CSV

    raise CLICommandFailed(f"Cannot infer data format from extension: {path.suffix!r}")


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


class CLIClientError(CLICommandFailed, ClientError):
    """Error raised when an HTTP or WebSocket request to the CLI server fails."""

    pass


class CLIDataOutputCommand(CLICommand):
    """CLI command that writes structured output to a file or stdout."""

    output: FilePath | NewPath | None = None
    """
    Output file to write data to. Data format will be inferred from the provided file extension. If
    unspecified, data is written to stdout.
    """

    data_format: CLIDataFormat | None = None
    """
    Specify the data output format, as either "json" (JSONL) or "csv". Defaults to "json", unless
    `--output` is specified, in which case the format can be inferred from the file extension.
    """

    field: MaybeSequence[str] | None = None
    """
    Specify entity field name(s) to include in output data. If unspecified, all fields are output.
    Specifying a colon after a field name in the format `--field <field>:<alias>` will rename the
    field in the output data to the provided alias.
    """

    @override
    async def put(
        self,
        data: object,
        file: IO[str] | None = None,
        *,
        end: str = "\n",
        flush: bool = False,
        color: bool | None = None,
        data_format: CLIDataFormat | None = None,
        fields: Sequence[str] | Mapping[str, str] | None = None,
    ) -> None:
        """Write data using the command's configured output file, format, and field selection."""
        # A file this call opens must close with it, or its final buffer never
        # reaches disk.
        opened: IO[str] | None = None
        if file is None:
            if self.output is not None:
                try:
                    opened = open(self.output, "w")
                except FileNotFoundError:
                    raise CLICommandFailed(f"Output file '{str(self.output)!r}' not found.")
                except OSError:
                    raise CLICommandFailed(f"Failed to open output file '{str(self.output)!r}'.")

                file = opened

        if file is None:
            file = sys.stdout

        assert file is not None

        data_format = data_format or self.data_format
        if self.output is not None:
            data_format = _resolve_data_format(self.output, data_format)

        if fields is None and self.field is not None:
            fields = seq(self.field)

        fields = _resolve_fields(fields)

        try:
            await super().put(
                data,
                file,
                end=end,
                flush=flush,
                color=color,
                data_format=data_format,
                fields=fields,
            )
        finally:
            if opened is not None:
                opened.close()

    def native_dump_format(self) -> CLIDataFormat | None:
        """The format a native one-pass dump can render, `None` when entities must
        materialize.

        A field projection needs Python attribute access, and colorized output routes
        through Rich, so only an uncolored, unprojected dump can ship as one
        pre-rendered pass.
        """
        if self.field is not None or getattr(self, "fields", None) is not None:
            return None

        data_format = self.data_format
        if self.output is not None:
            data_format = _resolve_data_format(self.output, data_format)

        color = self.color
        if color is None:
            color = _get_color_enabled_by_variables()

        if color is None:
            color = self.output is None and sys.stdout.isatty()

        if color:
            return None

        return data_format or CLIDataFormat.JSON

    def plain_json_output(self) -> bool:
        """Whether output is plain JSON lines, with no field selection and no color."""
        return self.native_dump_format() is CLIDataFormat.JSON

    def put_text(self, text: str) -> None:
        """Write already-rendered output through the command's configured destination."""
        if self.output is not None:
            try:
                file = open(self.output, "w")
            except FileNotFoundError:
                raise CLICommandFailed(f"Output file '{str(self.output)!r}' not found.")
            except OSError:
                raise CLICommandFailed(f"Failed to open output file '{str(self.output)!r}'.")

            with file:
                file.write(text)
        else:
            sys.stdout.write(text)


class CLIDataOutputSelectionCommand(CLIDataOutputCommand):
    """CLI data output command that additionally accepts positional field selection arguments."""

    fields: CliPositionalArg[list[str] | None] = None
    """
    Specify entity field name(s) to include in output data. If unspecified, all fields are output.
    Specifying a colon after a field name in the format `<field>:<alias>` will rename the field in
    the output data to the provided alias. Fields provided here and with `--field` option(s) are
    merged, with `--field` option(s) taking precedence over these positional arguments.
    """

    @override
    async def put(
        self,
        data: object,
        file: IO[str] | None = None,
        *,
        end: str = "\n",
        flush: bool = False,
        color: bool | None = None,
        data_format: CLIDataFormat | None = None,
        fields: Sequence[str] | Mapping[str, str] | None = None,
    ) -> None:
        """Write data, merging positional field selections with `--field` options."""
        if fields is None:
            fields = {
                **(_resolve_fields(self.fields) or {}),
                **(_resolve_fields(self.field) or {}),
            } or None

        await super().put(
            data,
            file,
            end=end,
            flush=flush,
            color=color,
            data_format=data_format,
            fields=fields,
        )


async def dump_records_natively(
    database: Any,
    Entity: type[Any],
    query: Any,
    data_format: CLIDataFormat = CLIDataFormat.JSON,
) -> str | None:
    """Render a record query as JSON or CSV lines in one native pass, `None` when it
    cannot.

    The query compiles here and executes through the native fetcher, so rows never
    become Python objects and records render once, in Rust. Only the record tables
    on a native backend qualify, and a query carrying a transform needs Python objects
    and takes the materializing path instead.
    """
    from ceres.__internal__.app.shared import RECORD_TABLES

    table = RECORD_TABLES.get(Entity.__entity_naming__.table)
    if table is None or query._get_transform() is not None:
        return None

    fetcher = database._record_fetcher()
    if fetcher is None:
        return None

    sql, parameters = await query.compiled()
    try:
        batch = await fetcher.fetch_sql(table, sql, parameters)
    except TypeError, ValueError:
        # The native engine can lag the Python one in corner cases. The dump stays
        # correct through the materializing path, just slower.
        return None

    if data_format is CLIDataFormat.CSV:
        return batch.to_csv_lines()

    return batch.to_json_lines().decode()


def create_entity_select_command(Entity: type[Entity]):
    """Create a CLI subcommand class that retrieves and outputs entities matching a filter."""
    naming = Entity.__entity_naming__

    class SelectCommand(CLIDataOutputSelectionCommand, cast("type", Entity.Filter)):
        f"""
        Retrieve {naming.plural}.
        """
        fields: CliPositionalArg[list[str] | None] = None

        @override
        async def __run__(self) -> None:
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                query = database.__manager__(Entity).where(filter)

                # A plain JSON or CSV dump of a record table renders natively in one
                # pass, which is what makes a select over a large table fast.
                data_format = self.native_dump_format()
                if data_format is not None:
                    dumped = await dump_records_natively(database, Entity, query, data_format)
                    if dumped is not None:
                        self.put_text(dumped)
                        return

                await self.put(query.select())

    return SelectCommand


def create_entity_count_command(Entity: type[Entity]):
    """Create a CLI subcommand class that counts entities matching a filter."""
    naming = Entity.__entity_naming__

    class CountCommand(CLICommand, cast("type", Entity.Filter)):
        f"""
        Count {naming.plural}.
        """

        @override
        async def __run__(self) -> None:
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                await self.put(await database.__manager__(Entity).where(filter).count())

    return CountCommand


def create_entity_any_command(Entity: type[Entity]):
    """Create a CLI subcommand class that checks if any entities match a filter."""
    naming = Entity.__entity_naming__

    class AnyCommand(CLICommand, cast("type", Entity.Filter)):
        f"""
        Check if one or more {naming.plural} match the provided filter.
        """

        @override
        async def __run__(self) -> None:
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                exists = await database.__manager__(Entity).where(filter).any()
                await self.put(exists)
                raise CLICommandExit(0 if exists else 1)

    return AnyCommand


def create_entity_create_command(Entity: type[Entity]):
    """Create a CLI subcommand class that creates a new entity from provided fields."""
    naming = Entity.__entity_naming__

    class CreateCommand(CLIDataOutputCommand, cast("type", Entity.Create.Model)):
        f"""
        Create a new {naming.singular}.
        """

        @override
        async def __run__(self) -> None:
            data = self.read(Entity.Create)
            async with self.use_database() as database:
                await self.put(await database.__manager__(Entity).create(data))

    return CreateCommand


def create_entity_update_command(Entity: type[Entity]):
    """Create a CLI subcommand class that updates entities matching a filter with assigned values."""
    naming = Entity.__entity_naming__

    class UpdateCommand(CLIDataOutputCommand, cast("type", Entity.Filter)):
        f"""
        Update {naming.plural}. Return the number updated.
        """

        assign: Assign[Entity.Update]
        f"""Values to assign to matched {naming.plural}. Specified as a JSON or YAML object."""
        confirm: Confirm = True
        """Confirm before updating."""
        collect: bool = False
        """Stream updated entities to stdout. Ordering is not preserved."""

        @override
        async def __run__(self) -> None:
            async with self.use_database() as database:
                filter = self.read(Entity.Filter)
                manager = database.__manager__(Entity)
                if self.confirm:
                    count = await manager.where(filter).count()
                    get_confirmation(f"Update {count} {naming.plural}?", abort=True)

                result = manager.where(filter).update(self.assign)
                await self.put(result if self.collect else await result)

    return UpdateCommand


def create_entity_delete_command(Entity: type[Entity]):
    """Create a CLI subcommand class that deletes entities matching a filter."""
    naming = Entity.__entity_naming__

    class DeleteCommand(CLIDataOutputCommand, cast("type", Entity.Filter)):
        f"""
        Delete {naming.plural}. Return the number deleted.
        """

        confirm: Confirm = True
        """Confirm before deleting."""
        collect: bool = False
        """Stream deleted entities to stdout. Ordering is not preserved."""

        @override
        async def __run__(self) -> None:
            async with self.use_database() as database:
                filter = self.read(Entity.Filter)
                manager = database.__manager__(Entity)
                if self.confirm:
                    count = await manager.where(filter).count()
                    get_confirmation(f"Delete {count} {naming.plural}?", abort=True)

                result = manager.where(filter).delete()
                await self.put(result if self.collect else await result)

    return DeleteCommand


def create_entity_follow_command(Entity: type[Entity]):
    """Create a CLI subcommand class that streams new entities over a WebSocket connection."""
    naming = Entity.__entity_naming__

    class FollowCommand(CLIDataOutputSelectionCommand, cast("type", Entity.Filter)):
        f"""
        Follow new {naming.plural}.
        """

        @override
        async def __run__(self) -> None:
            client = await self.use_client()
            filter = self.read(Entity.Filter)
            return await self.put(client.stream(naming.route, params=filter, result=Entity))

    return FollowCommand


if TYPE_CHECKING:
    from ceres.entity import Entity


def create_entity_load_command(Entity: type[Entity]):
    """Create a CLI subcommand class that bulk-loads entities from a JSON or CSV file."""
    naming = Entity.__entity_naming__

    class LoadCommand(CLICommand):
        f"""
        Load {naming.plural} from file. Return the number loaded.
        """

        path: CliPositionalArg[FilePath]
        f"""File path to load {naming.plural} from."""

        data_format: CLIDataFormat | None = None
        """
        Specify the data format for the input file, as either "json" (JSONL) or "csv". If
        unspecified, this will be inferred from the file extension.
        """

        on_conflict: CLIDataConflict = CLIDataConflict.ERROR
        """
        Specify how to handle primary key conflicts in the event one occurs. If "error", raise an
        error, and roll back any previous entity inserts. If "ignore", just skip updating the
        existing entity and continue loading. If "update", update the existing entity with the
        incoming values and continue loading.
        """

        @override
        async def __run__(self) -> None:
            count = await self._load(
                self.path,
                EntityType.from_class(Entity),
                self.data_format,
                self.on_conflict,
            )
            self.write(count, sys.stdout)

        async def _load(
            self,
            path: str | PathLike,
            entity_type: EntityType,
            data_format: CLIDataFormat | None = None,
            on_conflict: CLIDataConflict = CLIDataConflict.ERROR,
        ) -> int:
            path = Path(path)
            data_format = _resolve_data_format(path, data_format)
            cls = entity_type.cls

            batch: list[Entity] = []
            batch_size = 1000
            count = 0

            async def flush() -> None:
                nonlocal count

                match database.type:
                    case DatabaseType.POSTGRES:
                        from sqlalchemy.dialects.postgresql import insert
                    case DatabaseType.SQLITE | DatabaseType.TURSO:
                        from sqlalchemy.dialects.sqlite import insert

                statement = insert(cls.Row).values([dict(entity) for entity in batch])
                match on_conflict:
                    case CLIDataConflict.ERROR:
                        pass
                    case CLIDataConflict.IGNORE:
                        statement = statement.on_conflict_do_nothing(
                            cls.Row.__table__.primary_key,
                        )
                    case CLIDataConflict.UPDATE:
                        statement = statement.on_conflict_do_update(
                            cls.Row.__table__.primary_key,
                            set_={
                                column: column
                                for column in cls.Row.__table__.columns
                                if column.name not in cls.Row.__table__.primary_key.columns
                            },
                        )

                await connection.execute(statement)
                count += len(batch)
                batch.clear()

            async with self.use_database() as database:
                with wrap_database_errors():
                    async with database.connect() as connection:
                        async with connection.begin():
                            try:
                                match data_format:
                                    case CLIDataFormat.JSON:
                                        adapter = adapt(Iterable[Json[cls]])

                                        for entity in adapter.validate_python(open(path)):
                                            batch.append(entity)
                                            if len(batch) >= batch_size:
                                                await flush()

                                        if batch:
                                            await flush()
                                    case CLIDataFormat.CSV:
                                        from csv import DictReader

                                        adapter = adapt(Iterable[cls])

                                        with open(path) as stream:
                                            reader = DictReader(stream)
                                            for entity in adapter.validate_python(reader):
                                                batch.append(entity)
                                                if len(batch) >= batch_size:
                                                    await flush()

                                        if batch:
                                            await flush()

                            except FileNotFoundError:
                                raise CLICommandFailed(
                                    f"Input file '{str(self.path)!r}' not found."
                                )
                            except OSError:
                                raise CLICommandFailed(f"Failed to read input file: {str(path)!r}")
                            except ValidationError as error:
                                raise CLICommandFailed(str(error.errors()))

                            await connection.commit()

            return count

    return LoadCommand


EntitySubCommandMapping = Mapping[str, type[CLICommand]]

_COMMAND_CREATORS = {
    "select": create_entity_select_command,
    "follow": create_entity_follow_command,
    "count": create_entity_count_command,
    "any": create_entity_any_command,
    "create": create_entity_create_command,
    "update": create_entity_update_command,
    "delete": create_entity_delete_command,
    "load": create_entity_load_command,
}


def create_entity_command(
    Entity: type[Entity],
    overrides: EntitySubCommandMapping | None = None,
    *,
    follow: bool = False,
) -> type[CLICommandGroup]:
    """Build a command group with standard CRUD subcommands for the given entity type.

    Generate select, count, any, create, update, delete, and load subcommands. Optionally include
    a follow (streaming) subcommand. Custom subcommand classes can be provided via `overrides`.

    Args:
        Entity: The entity class to generate commands for.
        overrides: A mapping of subcommand names to custom command classes that replace the
            generated defaults.
        follow: If True, include a follow subcommand for live streaming.

    Returns:
        A dynamically created `CLICommandGroup` subclass with the entity's subcommands.
    """
    mapping = dict(overrides or {})

    for name, creator in _COMMAND_CREATORS.items():
        if name == "follow" and not follow:
            continue
        if name not in mapping:
            mapping[name] = creator(Entity)

    fields: Any = {key: (CliSubCommand[cls], ...) for key, cls in mapping.items()}
    naming = Entity.__entity_naming__

    return create_model(
        f"{ucamelcase(naming.plural)}Command",
        **fields,
        __base__=CLICommandGroup,
        __doc__=f"Manage {naming.plural}.",
    )


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
