from __future__ import annotations

import json
import os
import sys
import time
import warnings
from abc import abstractmethod
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import NoneType
from typing import (
    IO,
    Annotated,
    Any,
    AsyncContextManager,
    AsyncIterable,
    Callable,
    Collection,
    Literal,
    Mapping,
    Self,
    Sequence,
    TypeAlias,
    TypeVar,
    overload,
    override,
)
from uuid import UUID

from aiohttp import ClientError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
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

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.project import LoadedProject, Project
from ceres.data import DataObject, DeferBuild, FromYAML, MaybeSequence, NonEmpty, jsonify
from ceres.result import Ok

with lazy_imports(__name__):
    from ceres._internal.cli.client import Client
    from ceres._internal.entity import BaseEntity
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
                if issubclass(parser, (bool, int, float)):
                    continue

        try:
            return TypeAdapter(parser).validate_python(text)  # type: ignore
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


def __validate_non_empty(value: Any) -> Any:
    if util.is_true_collection(value) and len(value) == 0:
        raise ValueError("Cannot be empty.")

    return value


Confirm = Annotated[CliImplicitFlag[bool], Field(description="Ask before executing.")]

_TFields = TypeVar("_TFields", bound=Mapping[str, Any])
Assign: TypeAlias = Annotated[
    NonEmpty[FromYAML[_TFields]],
    NoDecode,
    Field(description="Field(s) to assign, passed as a non-empty JSON or YAML object."),
]


chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    os.chdir = __disabled_chdir__


class CLICommand(DataObject, DeferBuild):
    model_config = ConfigDict(
        defer_build=True,
        use_attribute_docstrings=True,
    )

    config_path: Path | None = Field(default=None, alias="config")
    """
    Explicit path to a ceres configuration file.
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

    async def __execute__(self) -> None:
        return await self.__run__()

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
                raise CLICommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")

    async def use_config(self, checks: Sequence[ConfigCheckType] = ()) -> Config:
        match await Config.load(self.use_config_path(), checks=checks):
            case Ok(config):
                return config
            case fail:
                raise CLICommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")

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

        if isinstance(data, AsyncContextManager):
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

    @asynccontextmanager
    async def use_database_session(
        self,
        *,
        require_initialized: bool = True,
        require_connect: bool = True,
    ):
        async with self.use_database(
            require_initialized=require_initialized,
            require_connect=require_connect,
        ) as database:
            async with database.session() as session:
                yield session

    async def use_temporary_engine(self):
        config_path = self.use_config_path()
        engine = Engine()
        await engine.load(config_path, silent=True)
        return engine

    def read[T: BaseModel](self, model: type[T]) -> T:
        return model.model_validate(self.model_dump(include=set(model.model_fields)))

    def get_subcommands(self, output: list[CLICommand] | None = None) -> list[CLICommand]:
        if output is None:
            output = []

        for value in util.dictify(self).values():
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
    int: jsonify,
    float: jsonify,
    bool: jsonify,
    bytes: lambda value: value.decode("latin-1"),
    bytearray: lambda value: value.decode("latin-1"),
    datetime: lambda value: jsonify(value)[1:-1],
    timedelta: lambda value: jsonify(value)[1:-1],
    date: lambda value: jsonify(value)[1:-1],
    UUID: lambda value: str(value),
}

_CSV_STRINGIFIERS: dict[type, Callable[[Any], str]] = {
    **_CSV_ATOMIC_STRINGIFIERS,
    list: jsonify,
    dict: jsonify,
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
        return jsonify(value)

    return str(value)


def _json_stringify(value: object) -> str:
    return jsonify(value)


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


class CLICommandGroup(CLICommand):
    @override
    async def __run__(self) -> Any:
        subcommand = get_subcommand(self, cli_exit_on_error=True)
        if subcommand is not None:
            return await subcommand.__execute__()


class CLICommandFailed(SettingsError):
    def __init__(self, message: Any) -> None:
        try:
            content = json.loads(message)
            if isinstance(content, dict):
                content.pop("__error__", None)

            message = json.dumps(content)
        except Exception:
            message = str(message)

        self.message = message
        super().__init__(message)

    @override
    def __str__(self) -> str:
        text = super().__str__()
        if not text.startswith("Error: "):
            text = f"Error: {text}"

        return text


class CLIClientError(CLICommandFailed, ClientError):
    pass


_T = TypeVar("_T")


class CLIDataFormat(StrEnum):
    JSON = "json"
    CSV = "csv"


class CLIDataCommand(CLICommand):
    data_format: CLIDataFormat = CLIDataFormat.JSON
    field: MaybeSequence[str] | None = None

    @override
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
            data_format = self.data_format

        if fields is None and self.field is not None:
            fields = util.as_sequence(self.field)

        mapping: dict[str, str] | None = None

        if fields is not None:
            mapping = {}
            for i, field in enumerate(fields):
                if ":" in field:
                    field, alias = field.split(":", 1)
                    mapping[field] = alias
                else:
                    mapping[field] = field

        await super().put(
            data,
            file,
            end=end,
            flush=flush,
            color=color,
            data_format=data_format,
            fields=mapping,
        )


def create_entity_select_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class SelectCommand(CLIDataCommand, Entity.Filter):
        f"""
        Retrieve {plural}.
        """

        @override
        async def __run__(self) -> None:
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                await self.put(util.get_entity_manager(database, Entity).where(filter).select())

    return SelectCommand


def create_entity_count_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class CountCommand(CLICommand, Entity.Filter):
        f"""
        Count {plural}.
        """

        @override
        async def __run__(self) -> None:
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                await self.put(
                    await util.get_entity_manager(database, Entity).where(filter).count()
                )

    return CountCommand


def create_entity_create_command(Entity: type[BaseEntity]):
    singular = util.get_entity_singular(Entity)

    class CreateCommand(CLIDataCommand, Entity.Create):
        f"""
        Create a new {singular}.
        """

        @override
        async def __run__(self) -> None:
            data = self.read(Entity.Create)
            async with self.use_database() as database:
                await self.put(await util.get_entity_manager(database, Entity).create(data))

    return CreateCommand


def create_entity_update_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class UpdateCommand(CLIDataCommand, Entity.Filter):
        f"""
        Update {plural}. Return the number updated.
        """

        assign: Assign[Entity.Update]  # type: ignore
        confirm: Confirm = True
        collect: bool = False

        @override
        async def __run__(self) -> None:
            async with self.use_database() as database:
                filter = self.read(Entity.Filter)
                manager = util.get_entity_manager(database, Entity)
                if self.confirm:
                    count = await manager.where(filter).count()
                    get_confirmation(f"Update {count} {plural}?", abort=True)

                result = manager.where(filter).update(self.assign)
                await self.put(result if self.collect else await result)

    return UpdateCommand


def create_entity_delete_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class DeleteCommand(CLIDataCommand, Entity.Filter):
        f"""
        Delete {plural}. Return the number deleted.
        """

        confirm: Confirm = True
        collect: bool = False

        @override
        async def __run__(self) -> None:
            async with self.use_database() as database:
                filter = self.read(Entity.Filter)
                manager = util.get_entity_manager(database, Entity)
                if self.confirm:
                    count = await manager.where(filter).count()
                    get_confirmation(f"Delete {count} {plural}?", abort=True)

                result = manager.where(filter).delete()
                await self.put(result if self.collect else await result)

    return DeleteCommand


def create_entity_follow_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)
    route = util.get_entity_route_name(Entity)

    class FollowCommand(CLIDataCommand, Entity.Filter):
        f"""
        Follow new {plural}.
        """

        @override
        async def __run__(self) -> None:
            client = await self.use_client()
            filter = self.read(Entity.Filter)
            return await self.put(client.follow(route, params=filter, result=Entity))

    return FollowCommand


EntitySubCommandMapping = Mapping[str, type[CLICommand]]

_COMMAND_CREATORS = {
    "select": create_entity_select_command,
    "follow": create_entity_follow_command,
    "count": create_entity_count_command,
    "create": create_entity_create_command,
    "update": create_entity_update_command,
    "delete": create_entity_delete_command,
}


def create_entity_command(
    Entity: type[BaseEntity],
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

    fields: Any = {key: (CliSubCommand[value], ...) for key, value in mapping.items()}
    plural = util.get_entity_plural(Entity)

    return create_model(
        f"{Entity.__name__}sCommand",
        **fields,
        __base__=CLICommandGroup,
        __doc__=f"Manage {plural}.",
    )
