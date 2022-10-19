from __future__ import annotations

from rich import print
from typer import Typer

from ....config import Config
from ...database.manager import DatabaseManager
from ...utilities import syncify
from ..common import CONFIG_OPTION, get_yes_no
from ..exceptions import CLIDatabaseUnreachableException


async def init(config: Config = CONFIG_OPTION) -> None:
    database = DatabaseManager.create(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    print("Pending commands to execute: ")
    for statement in database.ddl:
        print(f"> {statement}")

    if await database.tables():
        confirm = "Database is not empty, execute above commands anyway?"
    else:
        confirm = "Database appears to be uninitialized. Initialize now?"

    if get_yes_no(confirm):
        await database.init()
    else:
        print("Database has not been modified.")

    await database.dispose()


database = Typer(no_args_is_help=True)
database.command(help="Initialize project database.")(syncify(init))
