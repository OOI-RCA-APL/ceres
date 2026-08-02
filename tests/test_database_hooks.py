"""What a configuration's `init`, `connect`, and `close` statements actually run on.

Every backend states the same three promises. `init` runs once, on whichever connection
opens the database first. `connect` runs as each connection opens. `close` runs as each one
is let go, outside any transaction the work opened. A hook nobody runs is worse than one
nobody offers, so these assert on the rows the statements themselves wrote rather than on
the configuration having carried them.
"""

from typing import Any

import pytest

from ceres.config import (
    DatabaseConfig,
    DatabaseConfigHooks,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
    TursoDatabaseConfig,
)
from ceres.database import Database

_PROBE = "hook_probe"
"""Table the hooks write to, created by the `init` statement before any migration runs."""


def _configured(hooks: DatabaseConfigHooks) -> DatabaseConfig:
    """Build a config for the backend this run is on, carrying `hooks`.

    The backend comes from whatever the run pointed unconfigured databases at, so one test
    body covers all three, and a PostgreSQL config is rebuilt rather than replaced because
    its host, schema, and pool settings are the test server's.
    """
    from ceres.database import database as module

    config = module.default_database_config()
    match config:
        case PostgresDatabaseConfig():
            return PostgresDatabaseConfig(
                host=config.host,
                port=config.port,
                database=config.database,
                user=config.user,
                password=config.password,
                engine=config.engine,
                hooks=hooks,
            )
        case TursoDatabaseConfig():
            return TursoDatabaseConfig(hooks=hooks)
        case _:
            return SQLiteDatabaseConfig(hooks=hooks)


async def _stages(database: Database) -> dict[str, int]:
    """Count the rows each stage wrote, by stage name."""
    rows: list[dict[str, Any]] = await database._store().fetch(
        f"SELECT stage, COUNT(*) AS total FROM {_PROBE} GROUP BY stage", []
    )
    return {str(row["stage"]): int(row["total"]) for row in rows}


@pytest.mark.databases("sqlite", "turso", "postgres")
async def test_every_stage_of_a_connection_runs_the_statements_configured_for_it():
    """Each of the three hooks runs, on the connections its stage names."""
    database = Database(
        _configured(
            DatabaseConfigHooks(
                init=[f"CREATE TABLE IF NOT EXISTS {_PROBE} (stage TEXT NOT NULL)"],
                connect=[f"INSERT INTO {_PROBE} (stage) VALUES ('connect')"],
                close=[f"INSERT INTO {_PROBE} (stage) VALUES ('close')"],
            )
        )
    )
    try:
        # Migrating opens the connection the statements run on.
        await database.migrate()
        await database.users.count()

        stages = await _stages(database)
        assert stages.get("connect", 0) >= 1, "a connection ran its `connect` statement"
        assert stages.get("close", 0) >= 1, "a connection ran its `close` statement"
    finally:
        await database.dispose()


@pytest.mark.databases("sqlite", "turso", "postgres")
async def test_a_statement_the_backend_refuses_fails_the_connection_rather_than_passing():
    """A `connect` statement that will not run is reported, not swallowed.

    A connection that skipped its setup is not the connection that was configured, so the
    failure belongs to whoever asked for the statement rather than to the query that
    happened to open the connection.
    """
    database = Database(_configured(DatabaseConfigHooks(connect=["THIS IS NOT A STATEMENT"])))
    try:
        with pytest.raises(Exception):
            await database.ready()
    finally:
        await database.dispose()


@pytest.mark.databases("sqlite", "turso", "postgres")
async def test_a_table_an_init_hook_created_does_not_pass_for_a_bootstrapped_database():
    """A configuration that makes its own table still gets its migrations run.

    An `init` hook runs on the connection that opens the database, which is before any
    migration has. Reading "this database holds a table" as "this database is set up"
    therefore leaves a project whose schema is never created, and the table the hook made
    is the only one in it.
    """
    database = Database(
        _configured(
            DatabaseConfigHooks(init=[f"CREATE TABLE IF NOT EXISTS {_PROBE} (stage TEXT NOT NULL)"])
        )
    )
    try:
        assert not await database.initialized(), "the hook's own table is not this schema"

        await database.ready()

        assert await database.initialized()
        # The schema is really there, rather than merely reported.
        assert await database.users.count() == 0
    finally:
        await database.dispose()
