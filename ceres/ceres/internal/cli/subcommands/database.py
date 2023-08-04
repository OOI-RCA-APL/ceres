from ceres.config import Config
from ceres.database import Database
from ceres.internal.cli.exceptions import CLIDatabaseUnreachableException
from ceres.internal.cli.shared import AsyncTyper, ConfigOption, get_yes_no, write

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
async def schema(*, config: Config = ConfigOption(checks=[])) -> None:
    """
    Show DDL commands used to create required tables in the project database.
    """
    database = Database(config.database)

    for statement in database.ddl:
        write(statement)
