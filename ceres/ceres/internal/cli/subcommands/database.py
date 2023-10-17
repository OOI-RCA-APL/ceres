from pathlib import Path

from pydantic import ByteSize
from typer import Argument, Option

from ceres.config import Config
from ceres.database.enums import DataFormat, DataType
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException, CLIException
from ceres.internal.cli.shared import AsyncTyper, ConfigOption, get_yes_no, write
from ceres.internal.utilities import show_td
from ceres.timing import utc

database = AsyncTyper(
    name="database",
    no_args_is_help=True,
    help="Manage the project database.",
)


def _get_database(config: Config):
    from ceres.database.database import Database

    return Database(config.database)


@database.command()
async def init(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Create all required tables in the project database.
    """
    database = _get_database(config)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    print("<PENDING>")
    await ddl(config=config)
    print("</PENDING>")

    if await database.initialized():
        confirm = "Database is not empty, execute above commands anyway?"
    else:
        confirm = "Database appears uninitialized. Execute above commands now?"

    if get_yes_no(confirm):
        await database.init()
    else:
        write("Database has not been modified.")

    await database.dispose()


@database.command()
async def dump(
    data_type: DataType = Argument(help="Data type to dump to file."),
    path: Path = Argument(
        resolve_path=True,
        writable=True,
        help="Path to dump data to.",
    ),
    *,
    format: DataFormat = Option(None, help="Format to dump data as."),
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Dump data in the project database to file.
    """

    format = _infer_data_format(format, path)
    database = _get_database(config)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if not await database.initialized():
        raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    start = utc()
    match format:
        case DataFormat.CSV:
            write("Dumping data to CSV...")
        case DataFormat.SQLITE:
            write("Dumping data to SQLite...")

    await database.dump(data_type, path, format)

    duration = utc() - start

    match format:
        case DataFormat.CSV:
            write(f"Dump to CSV completed in {show_td(duration)}.")
        case DataFormat.SQLITE:
            size = ByteSize(path.stat().st_size).human_readable()
            write(f"Dumped {size} to SQLite in {show_td(duration)}.")


@database.command()
async def load(
    data_type: DataType = Argument(help="Data type to load from file."),
    path: Path = Argument(
        resolve_path=True,
        writable=True,
        help="Path to load data from.",
    ),
    *,
    format: DataFormat = Option(None, help="Data format to read the file as."),
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Load data into the project database.
    """
    format = _infer_data_format(format, path)
    database = _get_database(config)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if not await database.initialized():
        raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    start = utc()
    match format:
        case DataFormat.CSV:
            write("Loading data from CSV...")
        case DataFormat.SQLITE:
            write("Loading data from SQLite...")

    await database.load(data_type, path, format)

    duration = utc() - start

    match format:
        case DataFormat.CSV:
            write(f"Load from CSV completed in {show_td(duration)}.")
        case DataFormat.SQLITE:
            size = ByteSize(path.stat().st_size).human_readable()
            write(f"Load of {size} of data from SQLite completed in {show_td(duration)}.")


@database.command()
async def clear(config: Config = ConfigOption(checks=[])) -> None:
    """
    Clear all data from the project database.
    """
    database = _get_database(config)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if not await database.initialized():
        raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    if not get_yes_no("Clear all data from the project database?", default=False):
        write("Database has not been modified. Exiting.")
        return

    start = utc()

    await database.clear()

    duration = utc() - start
    write(f"Cleared all data from database in {show_td(duration)}.")


@database.command()
async def ddl(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Show DDL commands used to create required tables in the project database.
    """
    database = _get_database(config)

    for statement in database.ddl:
        write(statement)


def _infer_data_format(format: DataFormat | None, path: Path) -> DataFormat:
    if format is not None:
        return format
    if path.suffix == ".csv":
        return DataFormat.CSV
    if path.suffix in (".db", ".sqlite", ".sqlite3"):
        return DataFormat.SQLITE

    raise CLIException(
        f"Could not infer data format from file extension: {path.suffix!r}. "
        + "Try specifying the '--format' option."
    )
