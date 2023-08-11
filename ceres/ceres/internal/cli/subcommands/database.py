from pathlib import Path

from pydantic import ByteSize
from typer import Argument, Option

from ceres.config import Config, DatabaseKind
from ceres.database import Database
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException
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
    database = Database(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    print("<PENDING>")
    await schema(config=config)
    print("</PENDING>")

    if await database.tables():
        confirm = "Database is not empty, execute above commands anyway?"
    else:
        confirm = "Database appears uninitialized. Execute above commands now?"

    if get_yes_no(confirm):
        await database.init()
    else:
        write("Database has not been modified.")

    await database.dispose()


@database.command()
async def clone(
    path: Path = Argument(
        help="Path to clone database to.",
        resolve_path=True,
        dir_okay=False,
        writable=True,
    ),
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Copy the project database into a functional SQLite file. Only supported for SQLite databases.
    """
    database = Database(config.database)

    if database.kind != DatabaseKind.SQLITE:
        raise CLIDatabaseUnreachableException(
            "Database cloning is currently only supported for SQLite."
        )

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if not await database.tables():
        raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    start = utc()

    write(f"Cloning database to '{path}'...")
    await database.clone(path)

    duration = utc() - start
    size = ByteSize(path.stat().st_size).human_readable()

    write(f"Cloned database to {path} in {show_td(duration)}. Database size is {size}.")


@database.command()
async def dump(
    path: Path = Argument(
        help="Path to dump data to.",
        resolve_path=True,
        dir_okay=False,
        writable=True,
    ),
    update: bool = Option(False, help="Update an existing dump file."),
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Dump all data in the project database as a simplified SQLite file. Only supported for SQLite.
    """
    database = Database(config.database)

    if database.kind != DatabaseKind.SQLITE:
        raise CLIDatabaseUnreachableException(
            "Database dumping is currently only supported for SQLite."
        )

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    if not await database.tables():
        raise CLIDatabaseUnreachableException("Database appears uninitialized, exiting.")

    start = utc()

    write(f"Dumping database to '{path}'...")
    await database.dump(path, update=update)

    duration = utc() - start
    size = ByteSize(path.stat().st_size).human_readable()

    write(f"Dumped database to {path} in {show_td(duration)}. File size is {size}.")


@database.command()
async def schema(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Show DDL commands used to create required tables in the project database.
    """
    database = Database(config.database)

    for statement in database.ddl:
        write(statement)
