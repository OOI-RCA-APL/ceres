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
from ceres.result import Ok

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
    if os.getenv("NO_COLOR") is not None:
        return False
    if os.getenv("FORCE_COLOR") is not None:
        return True

    return None


_color_enabled_by_variables: bool | None = _compute_color_enabled_by_variables()
_color_enabled_checked = time.time()


def _get_color_enabled_by_variables() -> bool | None:
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
    import rich.box
    from rich.table import Table

    table = Table(title=title, box=rich.box.ROUNDED, title_justify="left")
    yield table
    write(table, file)


def strbool(value: bool) -> str:
    return "Yes" if value else "No"


Confirm = Annotated[CliImplicitFlag[bool], Field(description="Ask before executing.")]


def _validate_non_empty(value: object) -> object:
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
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    os.chdir = __disabled_chdir__


class CLIDataFormat(StrEnum):
    JSON = "json"
    CSV = "csv"


class CLIDataConflict(StrEnum):
    ERROR = "error"
    IGNORE = "ignore"
    UPDATE = "update"


class CLICommand(DataModel):
    model_config = ConfigDict(defer_build=True)

    config_path: Path | None = Field(default=None, alias="config")
    """
    Use a specific Ceres configuration file, possibly outside the current working directory.
    """

    color: bool | None = None
    """Enable or disable colorized output."""

    @model_validator(mode="after")
    def _globals(self) -> Self:
        subcommands = self.get_subcommands()
        for command in subcommands:
            if self.color is None and command.color is not None:
                self.color = command.color
            if self.config_path is None and command.config_path is not None:
                self.config_path = command.config_path

        return self

    @abstractmethod
    async def __run__(self) -> None: ...

    @overload
    def use_config_path(self, required: Literal[True] = True) -> Path: ...

    @overload
    def use_config_path(self, required: Literal[False]) -> Path | None: ...

    def use_config_path(self, required: bool = True) -> Path | None:
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
        match await ConfigMeta.load(self.use_config_path(), checks=checks):
            case Ok(config):
                return config
            case fail:
                raise CLICommandFailed(f"Failed to load configuration. {to_json(fail, indent=2)}")

    async def use_config(self, checks: Sequence[ConfigCheckType] = ()) -> Config:
        match await Config.load(self.use_config_path(), checks=checks):
            case Ok(config):
                return config
            case fail:
                raise CLICommandFailed(f"Failed to load configuration. {to_json(fail, indent=2)}")

    async def use_project(self) -> Project:
        config_path = self.use_config_path()
        return Project(config_path)

    async def use_loaded_project(self, checks: Sequence[ConfigCheckType] = ()) -> LoadedProject:
        config_path = self.use_config_path()
        config_meta = await self.use_config_meta(checks)
        return LoadedProject(config_path, config_meta)

    async def use_client(self) -> Client:
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

        async with database:
            yield database

    async def use_temporary_engine(self):
        config_path = self.use_config_path()
        engine = Engine()
        await engine.load(config_path, silent=True)
        return engine

    def read[T: DataObject | BaseModel](self, data_object_class: type[T]) -> T:
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
        if output is None:
            output = []

        for value in to_dict(self).values():
            if isinstance(value, CLICommand):
                output.append(value)

        return output


class _CallbackWriter:
    __slots__ = ("callback",)

    def __init__(self, callback: Callable[[str], None]) -> None:
        self.callback = callback

    def write(self, text: str) -> None:
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
    if isinstance(value, str):
        return True

    return type(value) in _CSV_ATOMIC_STRINGIFIERS


def _csv_stringify(value: object) -> str | None:
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
    return to_json(value)


_EMPTY_DICT = {}


def _extract(obj: object, fields: Mapping[str, str] | None = None) -> Mapping[str, object]:
    if fields is None:
        __dict__ = getattr(obj, "__dict__")
        if __dict__ is not None:
            return __dict__

        __slots__ = getattr(obj, "__slots__")
        if __slots__ is not None:
            return {slot: getattr(obj, slot) for slot in __slots__}

        return _EMPTY_DICT

    cls: dict[str, object] = getattr(obj.__class__, "__dict__")
    return {
        alias: getattr(obj, field, None) if field not in cls else None
        for field, alias in fields.items()
    }


def _resolve_fields(fields: Sequence[str] | Mapping[str, str] | None) -> Mapping[str, str] | None:
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
    if data_format is not None:
        return data_format
    if path.suffix in (".json", ".jsonl", ".ndjson", ".txt"):
        return CLIDataFormat.JSON
    elif path.suffix == ".csv":
        return CLIDataFormat.CSV

    raise CLICommandFailed(f"Cannot infer data format from extension: {path.suffix!r}")


class CLICommandGroup(CLICommand):
    @override
    async def __run__(self) -> None:
        subcommand = get_subcommand(self, cli_exit_on_error=True)
        if isinstance(subcommand, CLICommand):
            await subcommand.__run__()


class CLICommandExit(SettingsError):
    def __init__(self, status: int = 0, message: str | None = None) -> None:
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
        text = (self.message or "").strip()
        if text and self.status != 0:
            if not text.startswith("Error: "):
                text = f"Error: {text}"

        return text


class CLICommandFailed(CLICommandExit):
    def __init__(self, message: str) -> None:
        super().__init__(1, message)


class CLIClientError(CLICommandFailed, ClientError):
    pass


class CLIDataOutputCommand(CLICommand):
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
        if file is None:
            if self.output is not None:
                try:
                    file = open(self.output, "w")
                except FileNotFoundError:
                    raise CLICommandFailed(f"Output file '{str(self.output)!r}' not found.")
                except OSError:
                    raise CLICommandFailed(f"Failed to open output file '{str(self.output)!r}'.")

        if file is None:
            file = sys.stdout

        assert file is not None

        data_format = data_format or self.data_format
        if self.output is not None:
            data_format = _resolve_data_format(self.output, data_format)

        if fields is None and self.field is not None:
            fields = seq(self.field)

        fields = _resolve_fields(fields)

        await super().put(
            data,
            file,
            end=end,
            flush=flush,
            color=color,
            data_format=data_format,
            fields=fields,
        )


class CLIDataOutputSelectionCommand(CLIDataOutputCommand):
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


def create_entity_select_command(Entity: type[Entity]):
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
                await self.put(database.__manager__(Entity).where(filter).select())

    return SelectCommand


def create_entity_count_command(Entity: type[Entity]):
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
                    case DatabaseType.SQLITE:
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
