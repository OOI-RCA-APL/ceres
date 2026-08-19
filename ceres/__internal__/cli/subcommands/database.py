import sys
from typing import TYPE_CHECKING, override

import anyio
from pydantic_settings import CliSubCommand

from ceres.__internal__.cli.shared import (
    CLICommand,
    CLICommandExit,
    CLICommandFailed,
    CLICommandGroup,
    get_confirmation,
    temporary_signal_handler,
    write_progress,
)
from ceres.database.database import MIGRATIONS
from ceres.timing import sdelta, utc

if TYPE_CHECKING:
    from rich.progress import Progress, TaskID

    from ceres.__internal__.core import Migration


class MigrationProgress:
    """Name the migration running now, and say how far through the list it is.

    One line for the whole run rather than one per migration because a migration runs as
    a single script and nothing can see inside one. All that can honestly be said is which
    is running and how many have landed so the spinner carries that work is happening and
    the count carries the position. The spinner becomes a check when the last one lands.

    Satisfies `MigrationReporter` structurally so the database layer never imports the
    CLI to know how to be watched.
    """

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._task: TaskID | None = None
        self._landed = 0

    def starting(self, migration: Migration, index: int, total: int) -> None:
        """Name the migration now running and move the count on to it."""
        label = f"{migration.id:04d} {migration.name}"
        note = f"({index + 1}/{total})"

        if self._task is None:
            self._task = self._progress.add_task(label, total=total, note=note)
        else:
            self._progress.update(self._task, description=label, note=note)

    def finished(self, migration: Migration) -> None:
        """Count the migration that just landed, which turns the spinner on the last one.

        Nothing draws this number, but the task has to reach its total for the spinner to
        become a check, and a migration that fails never gets counted.
        """
        self._landed += 1
        if self._task is not None:
            self._progress.update(self._task, completed=self._landed)


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
        import gc
        import os
        from shutil import which

        from ceres.database import DatabaseType, PostgresDatabase, SQLiteDatabase, TursoDatabase

        # The shell is for inspecting and repairing the database so it must open regardless of
        # whether the schema is initialized or current.
        async with self.use_database(require_initialized=False) as database:
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

                case DatabaseType.SQLITE | DatabaseType.TURSO:
                    assert isinstance(database, SQLiteDatabase)
                    if isinstance(database, TursoDatabase) and database.config.mvcc:
                        raise CLICommandFailed(
                            "MVCC journaling makes the database file unreadable to "
                            "'sqlite3'. Use Turso's own shell against it instead, for "
                            f"example: tursodb {database.path}"
                        )

                    command = ["sqlite3", str(database.path)]
                    command.extend(["-cmd", f".output {os.devnull}"])
                    # What the store sets on every connection it opens so the shell sees the
                    # database the way the running engine does. A shell without foreign keys
                    # on would let a statement through that the engine would refuse.
                    for statement in ("PRAGMA foreign_keys = ON", "PRAGMA busy_timeout = 30000"):
                        command.extend(["-cmd", statement])
                    for statement in database.config.hooks.connect or ():
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

            # The shell opens the database itself so release this process's own hold on
            # it first. Turso's driver keeps an exclusive lock on the file until its
            # connection objects deallocate, not merely close, and the shell cannot open
            # the file under it so the pool is disposed and collection is forced.
            await database.dispose()
            gc.collect()

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

    yes: bool = False
    """
    Apply without prompting for confirmation.
    """

    @override
    async def __run__(self) -> None:
        """List pending migrations, prompt for confirmation, and apply them in order."""
        async with self.use_database(require_initialized=False) as database:
            unknown = await database.get_unknown_migrations()
            if unknown:
                raise CLICommandFailed(
                    "Database contains migrations unknown to this version of ceres: "
                    f"{', '.join(str(id) for id in unknown)}."
                )

            pending = await database.get_pending_migrations()
            if not pending:
                self.write("Database is up to date.")
                return

            # A database nothing has been applied to is being created rather than
            # migrated so the run reads as one step rather than a named list. Checked
            # via the applied set rather than `initialized()` because reading the
            # applied set creates the table that records it.
            bootstrapping = not await database.get_applied_migrations()

            if bootstrapping:
                question = "Create the project database?"
            else:
                for migration in pending:
                    self.write(f"{migration.id}: {migration.name}")

                question = "Apply the above migrations now?"

            if not self.yes and not get_confirmation(question):
                self.write("Database has not been modified.")
                return

            if bootstrapping:
                applied = await database.migrate()
                self.write(f"Created the database with {len(applied)} migration(s).")
            else:
                with write_progress() as progress:
                    applied = await database.migrate(MigrationProgress(progress))

                self.write(f"Applied {len(applied)} migration(s).")


class MigrationsCommand(CLICommand):
    """
    Show applied and pending database migrations.
    """

    @override
    async def __run__(self) -> None:
        """Print each known migration with its applied/pending status."""
        async with self.use_database(require_initialized=False) as database:
            applied = {migration.id for migration in await database.get_applied_migrations()}
            unknown = await database.get_unknown_migrations()

            for migration in MIGRATIONS:
                status = "applied" if migration.id in applied else "pending"
                self.write(f"{migration.id}: {migration.name} ({status})")

            for id in unknown:
                self.write(f"{id}: unknown (database is newer than this version)")


class DatabaseCommand(CLICommandGroup):
    """
    Manage the project database.
    """

    ddl: CliSubCommand[DDLCommand]
    shell: CliSubCommand[ShellCommand]
    clear: CliSubCommand[ClearCommand]
    migrate: CliSubCommand[MigrateCommand]
    migrations: CliSubCommand[MigrationsCommand]
