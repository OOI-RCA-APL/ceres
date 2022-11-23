import rich

from ....config import Config
from ...database.manager import DatabaseManager
from ..exceptions import CLIDatabaseUnreachableException
from ..shared import AsyncTyper, ConfigOption, get_yes_no

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
    database = DatabaseManager(config.database)

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
        rich.print("Database has not been modified.")

    await database.dispose()


@database.command()
async def schema(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Show DDL commands used to create required tables in the project database.
    """
    database = DatabaseManager(config.database)

    for statement in database.ddl:
        rich.print(f"{statement};")
