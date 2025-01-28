from __future__ import annotations

import os
import sys
import warnings
from abc import abstractmethod
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import (
    IO,
    Annotated,
    Any,
    Literal,
    Mapping,
    Sequence,
    TypeAlias,
    TypeVar,
    Unpack,
    overload,
    override,
)

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model
from pydantic_settings import CliImplicitFlag, CliSubCommand, SettingsError, get_subcommand

from ceres._internal import util
from ceres._internal.entity import BaseEntity
from ceres._internal.lazy import lazy_imports
from ceres._internal.project import LoadedProject, Project
from ceres.config import Config, ConfigCheckType, ConfigMeta
from ceres.data import DataObject, DeferBuild, FromYaml, NonEmpty, SerializeArgs, jsonify
from ceres.result import Ok


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
        raise CliCommandFailed("Aborted.")

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


def write(
    *args: object,
    sep: str = " ",
    end: str = "\n",
    file: IO[str] | None = None,
    flush: bool = False,
    to: Literal["stdout", "stderr"] = "stderr",
    color: bool | None = None,
):
    if file is None:
        file = sys.stdout if to == "stdout" else sys.stderr

    interactive = file.isatty() if file else None
    if color is None:
        color = interactive

    if color:
        import rich

        printer = rich.print
    else:
        printer = print

    printer(
        *args,
        sep=sep,
        end=end,
        file=file,
        flush=flush,
    )


def write_json(
    value: Any,
    *,
    sep: str = " ",
    end: str = "\n",
    file: IO[str] | None = None,
    flush: bool = False,
    to: Literal["stdout", "stderr"] = "stderr",
    color: bool | None = None,
    **kwargs: Unpack[SerializeArgs],
):
    if "indent" not in kwargs:
        kwargs["indent"] = 2

    write(
        jsonify(value, **kwargs),
        sep=sep,
        end=end,
        file=file,
        flush=flush,
        to=to,
        color=color,
    )


@contextmanager
def write_table(title: str | None = None, *, to: Literal["stdout", "stderr"] = "stderr"):
    import rich.box
    from rich.table import Table

    table = Table(title=title, box=rich.box.ROUNDED, title_justify="left")
    yield table
    write(table, to=to)


def strbool(value: bool) -> str:
    return "Yes" if value else "No"


def __validate_non_empty(value: Any) -> Any:
    if util.is_true_collection(value) and len(value) == 0:
        raise ValueError("Cannot be empty.")

    return value


Confirm = Annotated[CliImplicitFlag[bool], Field(description="Ask before executing.")]

_TFields = TypeVar("_TFields", bound=Mapping[Any, Any])
Assign: TypeAlias = Annotated[
    NonEmpty[FromYaml[_TFields]],
    Field(description="Field(s) to assign, passed as a non-empty JSON or YAML object."),
]


with lazy_imports(__name__):
    import json

    from ceres._internal.cli.client import Client
    from ceres.data import jsonify
    from ceres.engine import Engine

chdir = os.chdir


def __disabled_chdir__(*args: Any, **kwargs: Any) -> None:
    warnings.warn("Changing directory is disabled while running Ceres.")


def disable_chdir() -> None:
    os.chdir = __disabled_chdir__


class CliCommand(DataObject, DeferBuild):
    model_config = ConfigDict(
        defer_build=True,
        use_attribute_docstrings=True,
    )

    config_path: Path | None = Field(default=None, alias="config")
    """
    Explicit path to a ceres configuration file.
    """

    async def __execute__(self) -> Any:
        return await self.__run__()

    @abstractmethod
    async def __run__(self) -> Any: ...

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

            raise CliCommandFailed(
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
                raise CliCommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")

    async def use_config(self, checks: Sequence[ConfigCheckType]) -> Config:
        match await Config.load(self.use_config_path(), checks=checks):
            case Ok(config):
                return config
            case fail:
                raise CliCommandFailed(f"Failed to load configuration. {jsonify(fail, indent=2)}")

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
                raise CliCommandFailed(f"Failed to connect to database: {exception}")

            if require_initialized:
                if not await database.initialized():
                    raise CliCommandFailed("Database appears uninitialized, exiting.")

        async with database:
            yield database

    async def use_temporary_engine(self):
        config_path = self.use_config_path()
        engine = Engine()
        await engine.load(config_path, silent=True)
        return engine

    def read[T: BaseModel](self, model: type[T]) -> T:
        return model.model_validate(self.model_dump(include=set(model.model_fields)))


class CliCommandGroup(CliCommand):
    @override
    async def __run__(self) -> Any:
        subcommand = get_subcommand(self, cli_exit_on_error=True)
        if subcommand is not None:
            return await subcommand.__execute__()


class CliCommandFailed(SettingsError):
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


_T = TypeVar("_T")


def create_entity_get_command(Entity: type[BaseEntity]):
    singular = util.get_entity_singular(Entity)

    class GetCommand(CliCommand, Entity.Filter):
        f"""
        Retrieve one {singular}.
        """

        @override
        async def __run__(self):
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                return await util.get_entity_manager(database, Entity).get(filter)

    return GetCommand


def create_entity_get_all_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class GetAllCommand(CliCommand, Entity.Filter):
        f"""
        Retrieve multiple {plural}.
        """

        @override
        async def __run__(self):
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                return await util.get_entity_manager(database, Entity).get_all(filter)

    return GetAllCommand


def create_entity_count_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class CountCommand(CliCommand, Entity.Filter):
        f"""
        Count {plural}.
        """

        @override
        async def __run__(self):
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                return await util.get_entity_manager(database, Entity).count(filter)

    return CountCommand


def create_entity_create_command(Entity: type[BaseEntity]):
    singular = util.get_entity_singular(Entity)

    class CreateCommand(CliCommand, Entity.Create):
        f"""
        Create a new {singular}.
        """

        @override
        async def __run__(self):
            data = self.read(Entity.Create)
            async with self.use_database() as database:
                return await util.get_entity_manager(database, Entity).create(data)

    return CreateCommand


def create_entity_update_command(Entity: type[BaseEntity]):
    singular = util.get_entity_singular(Entity)

    class UpdateCommand(CliCommand, Entity.Filter):
        f"""
        Update one {singular}. Return if found.
        """

        assign: Assign[Entity.Update]  # type: ignore

        @override
        async def __run__(self):
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                return await util.get_entity_manager(database, Entity).update(filter, self.assign)

    return UpdateCommand


def create_entity_update_all_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class UpdateAllCommand(CliCommand, Entity.Filter):
        f"""
        Update multiple {plural}. Return the number updated.
        """

        assign: Assign[Entity.Update]  # type: ignore
        confirm: Confirm = True

        @override
        async def __run__(self):
            async with self.use_database() as database:
                filter = self.read(Entity.Filter)
                manager = util.get_entity_manager(database, Entity)
                if self.confirm:
                    count = await manager.count(filter)
                    get_confirmation(f"Update {count} particles?", abort=True)

                return await manager.update_all(filter, self.assign)

    return UpdateAllCommand


def create_entity_delete_command(Entity: type[BaseEntity]):
    singular = util.get_entity_singular(Entity)

    class DeleteCommand(CliCommand, Entity.Filter):
        f"""
        Delete one {singular}. Return if found.
        """

        @override
        async def __run__(self):
            filter = self.read(Entity.Filter)
            async with self.use_database() as database:
                return await util.get_entity_manager(database, Entity).delete(filter)

    return DeleteCommand


def create_entity_delete_all_command(Entity: type[BaseEntity]):
    plural = util.get_entity_plural(Entity)

    class DeleteAllCommand(CliCommand, Entity.Filter):
        f"""
        Delete multiple {plural}. Return the number deleted.
        """

        confirm: Confirm = True

        @override
        async def __run__(self):
            async with self.use_database() as database:
                filter = self.read(Entity.Filter)
                manager = util.get_entity_manager(database, Entity)
                if self.confirm:
                    count = await manager.count(filter)
                    get_confirmation(f"Delete {count} particles?", abort=True)

                return await manager.delete_all(filter)

    return DeleteAllCommand


EntitySubCommandMapping = Mapping[str, type[CliCommand]]


def create_entity_command(
    Entity: type[BaseEntity],
    overrides: EntitySubCommandMapping | None = None,
) -> type[CliCommandGroup]:
    mapping = dict(overrides or {})
    if "get" not in mapping:
        mapping["get"] = create_entity_get_command(Entity)
    if "get_all" not in mapping:
        mapping["get_all"] = create_entity_get_all_command(Entity)
    if "count" not in mapping:
        mapping["count"] = create_entity_count_command(Entity)
    if "create" not in mapping:
        mapping["create"] = create_entity_create_command(Entity)
    if "update" not in mapping:
        mapping["update"] = create_entity_update_command(Entity)
    if "update_all" not in mapping:
        mapping["update_all"] = create_entity_update_all_command(Entity)
    if "delete" not in mapping:
        mapping["delete"] = create_entity_delete_command(Entity)
    if "delete_all" not in mapping:
        mapping["delete_all"] = create_entity_delete_all_command(Entity)

    fields: Any = {key: (CliSubCommand[value], ...) for key, value in mapping.items()}
    plural = util.get_entity_plural(Entity)

    return create_model(
        f"{Entity.__name__}sCommand",
        **fields,
        __base__=CliCommandGroup,
        __doc__=f"Manage {plural}.",
    )
