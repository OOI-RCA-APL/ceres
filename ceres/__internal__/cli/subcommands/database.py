import sys
from typing import override

import anyio
from pydantic_settings import CliSubCommand

from ceres.__internal__.cli.shared import (
    CLICommand,
    CLICommandExit,
    CLICommandFailed,
    CLICommandGroup,
    get_confirmation,
    temporary_signal_handler,
)
from ceres.database.migrations import MIGRATIONS
from ceres.timing import sdelta, utc


class InitCommand(CLICommand):
    """
    Initialize the database, creating tables and indexes as needed.
    """

    @override
    async def __run__(self) -> None:
        """Show pending DDL statements, prompt for confirmation, and initialize the database."""
        async with self.use_database(require_initialized=False) as database:
            try:
                async with database.connect():
                    pass
            except Exception:
                raise CLICommandFailed("Failed to connect to database.")

            self.write("<PENDING>", color=False)
            for statement in database.ddl:
                self.write(statement)
            self.write("</PENDING>", color=False)

            if await database.initialized():
                confirmation = "Database is not empty, execute above commands anyway?"
            else:
                confirmation = "Database appears uninitialized. Execute above commands now?"

            if get_confirmation(confirmation):
                await database.init()
            else:
                self.write("Database has not been modified.")


class DDLCommand(CLICommand):
    """
    Show DDL commands used to initialize the database.
    """

    @override
    async def __run__(self) -> None:
        """Print the DDL statements used for database initialization to stdout."""
        async with self.use_database(require_initialized=False, require_connect=False) as database:
            for statement in database.ddl:
                self.write(statement, sys.stdout, color=False)


class ShellCommand(CLICommand):
    """
    Open an interactive database shell (psql or sqlite3) for the project database.
    """

    @override
    async def __run__(self) -> None:
        """Launch the appropriate database shell as a subprocess, forwarding stdio."""
        import os
        from shutil import which

        from ceres.database import DatabaseType, PostgresDatabase, SQLiteDatabase

        async with self.use_database() as database:
            command: list[str] = []
            env: dict[str, str] = {**os.environ}

            match database.type:
                case DatabaseType.POSTGRES:
                    assert isinstance(database, PostgresDatabase)
                    command = [
                        "psql",
                        "--host",
                        database.config.host,
                        *(
                            ["--port", str(database.config.port)]
                            if database.config.port is not None
                            else ()
                        ),
                        "--user",
                        database.config.user,
                        database.config.database,
                    ]

                    if database.config.password is not None:
                        env["PGPASSWORD"] = database.config.password.get_secret_value()

                case DatabaseType.SQLITE:
                    assert isinstance(database, SQLiteDatabase)
                    command = ["sqlite3", str(database.path)]
                    command.extend(["-cmd", f".output {os.devnull}"])
                    for statement in database._get_connect_commands():
                        command.extend(["-cmd", statement])
                    for statement in database.config.hooks.init or ():
                        command.extend(["-cmd", statement])

                    command.extend(["-cmd", ".output"])

            executable = command[0]
            if which(executable) is None:
                raise CLICommandFailed(
                    f"Executable {executable!r} was not found in system path. It must be installed "
                    "to use this command."
                )

            from signal import SIGTERM

            process = await anyio.open_process(
                command,
                env=env,
                stdin=sys.stdin,
                stderr=sys.stderr,
                stdout=sys.stdout,
            )

            with temporary_signal_handler([SIGTERM], lambda: process.terminate()):
                status = await process.wait()

        raise CLICommandExit(status)


class ClearCommand(CLICommand):
    """
    Remove all data from the database. Tables and indexes are not removed, only truncated.
    """

    @override
    async def __run__(self) -> None:
        """Prompt for confirmation, then truncate all tables in the project database."""
        async with self.use_database() as database:
            if not get_confirmation("Clear all data from the project database?"):
                self.write("Database has not been modified. Exiting.")
                return

            start = utc()

            await database.clear()

            duration = utc() - start
            self.write(f"Cleared all data from database in {sdelta(duration, decimals=2)}.")


class MigrateCommand(CLICommand):
    """
    Apply pending database migrations.
    """

    @override
    async def __run__(self) -> None:
        """List pending migrations, prompt for confirmation, and apply them in order."""
        async with self.use_database() as database:
            unknown = await database.unknown_migrations()
            if unknown:
                raise CLICommandFailed(
                    "Database contains migrations unknown to this version of ceres: "
                    f"{', '.join(str(id) for id in unknown)}."
                )

            pending = await database.pending_migrations()
            if not pending:
                self.write("Database is up to date.")
                return

            for migration in pending:
                self.write(f"{migration.id}: {migration.description}")

            if get_confirmation("Apply the above migrations now?"):
                applied = await database.migrate()
                self.write(f"Applied {len(applied)} migration(s).")
            else:
                self.write("Database has not been modified.")


class MigrationsCommand(CLICommand):
    """
    Show applied and pending database migrations.
    """

    @override
    async def __run__(self) -> None:
        """Print each known migration with its applied/pending status."""
        async with self.use_database() as database:
            applied = set(await database.applied_migrations())
            unknown = await database.unknown_migrations()

            for migration in MIGRATIONS:
                status = "applied" if migration.id in applied else "pending"
                self.write(f"{migration.id}: {migration.description} ({status})")

            for id in unknown:
                self.write(f"{id}: unknown (database is newer than this version)")


class DatabaseCommand(CLICommandGroup):
    """
    Manage the project database.
    """

    init: CliSubCommand[InitCommand]
    ddl: CliSubCommand[DDLCommand]
    shell: CliSubCommand[ShellCommand]
    clear: CliSubCommand[ClearCommand]
    migrate: CliSubCommand[MigrateCommand]
    migrations: CliSubCommand[MigrationsCommand]
