import sys
from typing import override

from pydantic_settings import CliSubCommand

from ceres._internal import util
from ceres._internal.cli.shared import (
    CLICommand,
    CLICommandFailed,
    CLICommandGroup,
    get_confirmation,
)
from ceres.timing import utc


class InitCommand(CLICommand):
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
                raise CLICommandFailed("Failed to connect to database.")

            print("<PENDING>")
            for statement in database.ddl:
                self.write(statement)
            print("</PENDING>")

            if await database.initialized():
                confirmation = "Database is not empty, execute above commands anyway?"
            else:
                confirmation = "Database appears uninitialized. Execute above commands now?"

            if get_confirmation(confirmation):
                await database.init()
            else:
                self.write("Database has not been modified.")


class ClearCommand(CLICommand):
    """
    Remove all data from the database. Tables and indexes are not removed, only truncated.
    """

    @override
    async def __run__(self) -> None:
        async with self.use_database() as database:
            if not get_confirmation("Clear all data from the project database?"):
                self.write("Database has not been modified. Exiting.")
                return

            start = utc()

            await database.clear()

            duration = utc() - start
            self.write(f"Cleared all data from database in {util.show_td(duration)}.")


class DDLCommand(CLICommand):
    """
    Show DDL commands used to initialize the database.
    """

    @override
    async def __run__(self) -> None:
        async with self.use_database(require_initialized=False, require_connect=False) as database:
            for statement in database.ddl:
                self.write(statement, sys.stdout, color=False)


class DatabaseCommand(CLICommandGroup):
    """
    Manage the project database.
    """

    init: CliSubCommand[InitCommand]
    clear: CliSubCommand[ClearCommand]
    ddl: CliSubCommand[DDLCommand]
