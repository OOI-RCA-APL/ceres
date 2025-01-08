from pathlib import Path
from typing import Sequence, override

from pydantic import FilePath, NewPath
from pydantic_settings import CliPositionalArg, CliSubCommand

from ceres._internal.cli.shared import (
    CliCommand,
    CliCommandFailed,
    CliCommandGroup,
    get_confirmation,
    write,
)
from ceres._internal.lazy import lazy_imports
from ceres.database.enums import DataFormat
from ceres.entity import EntityType
from ceres.timing import utc

with lazy_imports(__name__):
    from ceres._internal import util


class InitCommand(CliCommand):
    """
    Initialize the database, creating tables and indexes as needed.
    """

    @override
    async def __run__(self) -> None:
        async with self.use_database(require_initialized=False) as database:
            try:
                async with database.connect():
                    pass
            except Exception:
                raise CliCommandFailed("Failed to connect to database.")

            print("<PENDING>")
            for statement in database.ddl:
                write(statement, to="stdout")
            print("</PENDING>")

            if await database.initialized():
                confirmation = "Database is not empty, execute above commands anyway?"
            else:
                confirmation = "Database appears uninitialized. Execute above commands now?"

            if get_confirmation(confirmation):
                await database.init()
            else:
                write("Database has not been modified.")


class DumpCommand(CliCommand):
    """
    Dump data from the database into a CSV or SQLite file.
    """

    path: CliPositionalArg[FilePath | NewPath]
    """File path to write to."""

    entity_type: Sequence[EntityType] = []
    """
    Data type(s) to dump.
    * For **--format csv**, a single **--entity-type** is *required*.
    * For **--format sqlite**, if **--entity-type** is *omitted*, *all* entity types will be dumped
    to the SQLite database. If **--entity-type** is specified *one or more times*,
    *only* those entity types will be dumped.
    """

    format: DataFormat | None
    """File format to dump as. This is inferred from the file extension if possible."""

    @override
    async def __run__(self) -> None:
        format = _guess_format(self.format, self.path)

        if format == DataFormat.CSV:
            if not self.entity_type:
                raise CliCommandFailed("Dumping to CSV requires '--entity-type' to be specified.")
            elif len(self.entity_type) != 1:
                raise CliCommandFailed(
                    "Dumping to CSV requires exactly one '--entity-type' to be specified."
                )

        entity_type = self.entity_type or list(EntityType)
        start = utc()

        async with self.use_database() as database:
            match format:
                case DataFormat.CSV:
                    write("Dumping data to CSV...")
                    await database.dump_csv(self.path, entity_type[0])
                case DataFormat.SQLITE:
                    write("Dumping data to SQLite...")
                    await database.dump_sqlite(self.path, entity_type)

        duration = utc() - start
        write(f"Dump completed in {util.show_td(duration)}.")


class LoadCommand(CliCommand):
    """
    Load data into the database from a CSV or SQLite file.
    """

    path: CliPositionalArg[FilePath | NewPath]
    """File path to read data from."""

    entity_type: Sequence[EntityType] = []
    """
    Data type(s) to load.
    * For **--format csv**, a single **--entity-type** is *required*.
    * For **--format sqlite**, if **--entity-type** is *omitted*, *all* entity types will be
    loaded from the SQLite database. If **--entity-type** is specified *one or more times*, *only*
    those entity types will be loaded.
    """

    format: DataFormat | None
    """File format to read as. This is inferred from the file extension if possible."""

    @override
    async def __run__(self) -> None:
        format = _guess_format(self.format, self.path)
        if format == DataFormat.CSV:
            if not self.entity_type:
                raise CliCommandFailed("Loading from CSV requires '--entity-type' to be specified.")
            elif len(self.entity_type) != 1:
                raise CliCommandFailed(
                    "Loading from CSV requires exactly one '--entity-type' to be specified."
                )

        entity_type = self.entity_type or list(EntityType)
        start = utc()

        async with self.use_database() as database:
            match format:
                case DataFormat.CSV:
                    write("Loading data from CSV...")
                    await database.load_csv(self.path, entity_type[0])
                case DataFormat.SQLITE:
                    write("Loading data from SQLite...")
                    await database.load_sqlite(self.path, entity_type)

        duration = utc() - start
        write(f"Load completed in {util.show_td(duration)}.")


class ClearCommand(CliCommand):
    """
    Remove all data from the database. Tables and indexes are not removed, only truncated.
    """

    @override
    async def __run__(self) -> None:
        async with self.use_database() as database:
            if not get_confirmation("Clear all data from the project database?"):
                write("Database has not been modified. Exiting.")
                return

            start = utc()

            await database.clear()

            duration = utc() - start
            write(f"Cleared all data from database in {util.show_td(duration)}.")


class DdlCommand(CliCommand):
    """
    Show DDL commands used to initialize the database.
    """

    @override
    async def __run__(self) -> None:
        async with self.use_database(require_initialized=False, require_connect=False) as database:
            for statement in database.ddl:
                write(statement, to="stdout", color=False)


def _guess_format(format: DataFormat | None, path: Path) -> DataFormat:
    if format is not None:
        return format
    if path.suffix == ".csv":
        return DataFormat.CSV
    if path.suffix in (".db", ".sqlite", ".sqlite3"):
        return DataFormat.SQLITE

    raise CliCommandFailed(
        f"Could not infer data format from file extension: {path.suffix!r}. "
        + "Try specifying the '--format' option."
    )


class DatabaseCommand(CliCommandGroup):
    """
    Manage the project database.
    """

    init: CliSubCommand[InitCommand]
    dump: CliSubCommand[DumpCommand]
    load: CliSubCommand[LoadCommand]
    clear: CliSubCommand[ClearCommand]
    ddl: CliSubCommand[DdlCommand]
