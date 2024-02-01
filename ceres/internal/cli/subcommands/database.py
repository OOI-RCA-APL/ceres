from pathlib import Path
from typing import Annotated

from click import Choice

from ceres.config import Config
from ceres.database.enums import DataFormat, ItemType
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException, CLIException
from ceres.internal.cli.plumbing import CLIArgument, CLIOption, CLIRouter
from ceres.internal.cli.shared import (
    ConfigOption,
    Dummy,
    get_database,
    get_yes_no,
    write,
)
from ceres.internal.utilities import show_td
from ceres.timing import utc

router = CLIRouter(
    name="database",
    help="Manage the project database.",
)


@router.command()
async def init(*, config: Annotated[Config, ConfigOption(checks=[])] = Dummy()) -> None:
    """
    Initialize the database, creating tables and indexes as needed.
    """
    database = await get_database(config)

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


@router.command()
async def dump(
    path: Annotated[
        Path,
        CLIArgument(
            Path,
            dir_okay=False,
            resolve_path=True,
            writable=True,
            help="File path to write to.",
        ),
    ],
    *,
    item_type: Annotated[
        list[ItemType],
        CLIOption(
            list[ItemType],
            click_type=Choice([current.value for current in ItemType]),
            help=(
                """
            Data type(s) to dump.
            * For **--format csv**, a single **--item-type** is *required*.
            * For **--format sqlite**, if **--item-type** is *omitted*, *all* item types will be
            dumped to the SQLite database. If **--item-type** is specified *one or more times*,
            *only* those item types will be dumped.
            """
            ),
        ),
    ] = [],
    format: Annotated[
        DataFormat | None,
        CLIOption(
            DataFormat | None,
            help="File format to dump as. This is inferred from the file extension if possible.",
        ),
    ] = None,
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Dump data from the database into a CSV or SQLite file.
    """
    format = _guess_format(format, path)

    if format == DataFormat.CSV:
        if not item_type:
            raise CLIException("Dumping to CSV requires '--item-type' to be specified.")
        elif len(item_type) != 1:
            raise CLIException("Dumping to CSV requires exactly one '--item-type' to be specified.")

    item_type = list(ItemType) if not item_type else [ItemType(current) for current in item_type]

    database = await get_database(config, initialized=True)
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


@router.command()
async def load(
    path: Annotated[
        Path,
        CLIArgument(
            Path,
            dir_okay=False,
            resolve_path=True,
            readable=True,
            help="File path to read data from.",
        ),
    ],
    *,
    item_type: Annotated[
        list[ItemType],
        CLIOption(
            list[ItemType],
            click_type=Choice([current.value for current in ItemType]),
            help=(
                """
            Data type(s) to load.
            * For **--format csv**, a single **--item-type** is *required*.
            * For **--format sqlite**, if **--item-type** is *omitted*, *all* item types will be
            loaded from the SQLite database. If **--item-type** is specified *one or more times*,
            *only* those item types will be loaded.
            """
            ),
        ),
    ] = [],
    format: Annotated[
        DataFormat | None,
        CLIOption(
            DataFormat | None,
            help="File format to read as. This is inferred from the file extension if possible.",
        ),
    ] = None,
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Load data into the database from a CSV or SQLite file.
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

    database = await get_database(config, initialized=True)
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


@router.command()
async def clear(config: Annotated[Config, ConfigOption(checks=[])] = Dummy()) -> None:
    """
    Remove all data from the database. Tables and indexes are not removed, only truncated.
    """
    database = await get_database(config, initialized=True)

    if not get_yes_no("Clear all data from the project database?", default=False):
        write("Database has not been modified. Exiting.")
        return

    start = utc()

    await database.clear()

    duration = utc() - start
    write(f"Cleared all data from database in {show_td(duration)}.")


@router.command()
async def ddl(*, config: Annotated[Config, ConfigOption(checks=[])] = Dummy()) -> None:
    """
    Show DDL commands used to initialize the database.
    """
    database = await get_database(config)

    for statement in database.ddl:
        write(statement)


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
