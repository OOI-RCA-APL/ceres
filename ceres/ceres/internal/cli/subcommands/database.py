from __future__ import annotations

import rich
from typer import Typer

from ....config import Config
from ...database.manager import DatabaseManager
from ...utilities import syncify
from ..common import ConfigOption, get_yes_no
from ..exceptions import CLIDatabaseUnreachableException


async def init(config: Config = ConfigOption(checks=[])) -> None:
    database = DatabaseManager(config.database)

    try:
        async with database.connect():
            pass
    except Exception:
        raise CLIDatabaseUnreachableException("Failed to connect to database.")

    print("<PENDING>")
    await schema(config)
    print("</PENDING>")

    if await database.tables():
        confirm = "Database is not empty, execute above commands anyway?"
    else:
        confirm = "Database appears uninitialized. Execute above commands now?"

    if get_yes_no(confirm):
        await database.init()
    else:
        rich.print("Database has not been modified.")

    await database.dispose()


async def schema(config: Config = ConfigOption(checks=[])) -> None:
    database = DatabaseManager(config.database)

    for statement in database.ddl:
        rich.print(f"{statement};")


database = Typer(no_args_is_help=True)
database.command(help="Create all required tables in the project database.")(syncify(init))
database.command(help="Show DDL commands used to create required tables in the project database.")(
    syncify(schema)
)
