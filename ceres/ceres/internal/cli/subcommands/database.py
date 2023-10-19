from pathlib import Path

from click import Choice
from pydantic import ByteSize
from typer import Argument, Option

from ceres.config import Config
from ceres.database.enums import DataFormat, ItemType
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException, CLIException
from ceres.internal.cli.shared import AsyncTyper, ConfigOption, get_yes_no, write
from ceres.internal.utilities import show_td
from ceres.timing import utc

database = AsyncTyper(
    name="database",
    no_args_is_help=True,
    help="Manage the project database.",
)


@database.command()
async def init(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Create all required tables in the project database.
    """
    database = await _get_database(config)

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
    path: Path = Argument(
        dir_okay=False,
        resolve_path=True,
        writable=True,
        help="File path to write to.",
    ),
    *,
    item_type: list[ItemType] = Option(
        [],
        click_type=Choice([current.value for current in ItemType]),
        help="Data type to dump to file.",
    ),
    format: DataFormat = Option(None, help="Format to dump data as."),
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Dump data in the project database to file.
    """
    format = _guess_format(format, path)

    if format == DataFormat.CSV:
        if not item_type:
            raise CLIException("Dumping to CSV requires '--item-type' to be specified.")
        elif len(item_type) != 1:
            raise CLIException("Dumping to CSV requires exactly one '--item-type' to be specified.")

    item_type = list(ItemType) if not item_type else [ItemType(current) for current in item_type]

    database = await _get_database(config, initialized=True)
    start = utc()

    match format:
        case DataFormat.CSV:
            write("Dumping data to CSV...")
            await database.dump_csv(path, item_type[0])
        case DataFormat.SQLITE:
            write("Dumping data to SQLite...")
            await database.dump_sqlite(path, item_type)

    duration = utc() - start
    write(f"Dump completed in {show_td(duration)}.")


@database.command()
async def load(
    path: Path = Argument(
        dir_okay=False,
        resolve_path=True,
        readable=True,
        help="File path to read data from.",
    ),
    *,
    item_type: list[ItemType] = Option(
        [],
        click_type=Choice([current.value for current in ItemType]),
        help="Data type(s) to load from file.",
    ),
    format: DataFormat = Option(None, help="Data format to read the file as."),
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Load data into the project database.
    """
    format = _guess_format(format, path)
    if format == DataFormat.CSV:
        if not item_type:
            raise CLIException("Loading from CSV requires '--item-type' to be specified.")
        elif len(item_type) != 1:
            raise CLIException(
                "Loading from CSV requires exactly one '--item-type' to be specified."
            )

    item_type = list(ItemType) if not item_type else [ItemType(current) for current in item_type]

    database = await _get_database(config, initialized=True)
    start = utc()

    match format:
        case DataFormat.CSV:
            write("Loading data from CSV...")
            await database.load_csv(path, item_type[0])
        case DataFormat.SQLITE:
            write("Loading data from SQLite...")
            await database.load_sqlite(path, item_type)

    duration = utc() - start
    write(f"Load completed in {show_td(duration)}.")


@database.command()
async def clear(config: Config = ConfigOption(checks=[])) -> None:
    """
    Clear all data from the project database.
    """
    database = await _get_database(config, initialized=True)

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
    database = await _get_database(config)

    for statement in database.ddl:
        write(statement)


async def _get_database(config: Config, *, initialized: bool = False):
    from ceres.database.database import Database

    database = Database(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if initialized:
        if not await database.initialized():
            raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    return database


def _guess_format(format: DataFormat | None, path: Path) -> DataFormat:
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


def _get_size(path: Path) -> str:
    return ByteSize(path.stat().st_size).human_readable()
