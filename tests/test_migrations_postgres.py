"""Replay every migration against a real PostgreSQL server.

Production runs on PostgreSQL while the rest of the suite defaults to SQLite, so SQL that is only
valid on one backend can pass every other test. Migration 5 originally declared `owner_id` as
`CHAR(32)`, which SQLite accepts and PostgreSQL rejects against its `uuid` primary keys, and
nothing caught it. These tests close that gap for the migrations themselves, and `tests.postgres`
covers everything the running engine does afterwards.

Each test runs inside a throwaway schema so it never touches the deployment's own tables, and the
whole module skips when no server is reachable, keeping the suite runnable offline.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ceres.database.migrations import MIGRATIONS
from tests.postgres import POSTGRES_URL

SCHEMA = f"ceres_migration_test_{os.getpid()}"
"""Throwaway schema every statement runs in, so the deployment's own tables are never touched.

The process ID is part of the name because the fixture drops the schema on the way in and out, and
two suite runs against one server would otherwise pull it out from under each other.
"""


async def _reachable() -> bool:
    engine = create_async_engine(POSTGRES_URL)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _execute_script(connection, sql: str) -> None:
    """Run a multi-statement script the way `PostgresDatabase._execute_script` does.

    asyncpg refuses multiple commands in a prepared statement, so migration scripts have to go
    through the simple query protocol on the raw driver connection.
    """
    raw = await connection.get_raw_connection()
    assert raw.driver_connection is not None
    await raw.driver_connection.execute(sql)


async def _apply_migrations(connection, starting_from: int = 1, through: int | None = None) -> None:
    """Apply migrations in order, bounded by `starting_from` and `through` inclusive."""
    for migration in MIGRATIONS:
        if migration.id < starting_from:
            continue
        if through is not None and migration.id > through:
            return

        sql = migration.render("postgres")
        if sql is None:
            continue

        await _execute_script(connection, sql)


@pytest.fixture
async def connection():
    if not await _reachable():
        pytest.skip(f"no PostgreSQL server at {POSTGRES_URL}")

    engine = create_async_engine(POSTGRES_URL)
    try:
        async with engine.begin() as current:
            await current.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
            await current.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            # `public` stays on the path so extensions installed there, such as pg_trgm and its
            # operator classes, resolve while the tables themselves land in the throwaway schema.
            await current.execute(text(f"SET search_path TO {SCHEMA}, public"))
            yield current

        async with engine.begin() as current:
            await current.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
    finally:
        await engine.dispose()


async def test_every_migration_applies(connection) -> None:
    await _apply_migrations(connection)

    tables = {
        row[0]
        for row in await connection.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"),
            {"schema": SCHEMA},
        )
    }

    assert "workspaces" in tables
    assert "users" in tables


async def test_workspace_columns_match_the_orm_types(connection) -> None:
    """Identifier columns must be `uuid`, matching the primary keys they reference."""
    await _apply_migrations(connection)

    columns = {
        row[0]: (row[1], row[2])
        for row in await connection.execute(
            text(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'workspaces'"
            ),
            {"schema": SCHEMA},
        )
    }

    assert columns["owner_id"] == ("uuid", "YES")
    assert columns["scope"] == ("text", "NO")
    assert columns["show_when_logged_out"] == ("boolean", "NO")


async def test_placement_migration_converts_and_preserves_data(connection) -> None:
    """A pre-placement global workspace becomes engine-placed, and referencing rows survive."""
    await _apply_migrations(connection, through=4)

    await connection.execute(
        text(
            "INSERT INTO users (id, username, email, password, admin, disabled) VALUES "
            "('11111111-1111-1111-1111-111111111111', 'alice', 'a@a', 'x', false, false)"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO workspaces (id, name, data) VALUES "
            "('22222222-2222-2222-2222-222222222222', 'legacy global', '{}')"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO workspaces (id, name, scope, data) VALUES "
            "('33333333-3333-3333-3333-333333333333', 'rig view', '@rig', '{}')"
        )
    )
    await connection.execute(
        text(
            "INSERT INTO workspace_edits (user_id, workspace_id, data) VALUES "
            "('11111111-1111-1111-1111-111111111111', "
            "'22222222-2222-2222-2222-222222222222', '{\"layout\": []}')"
        )
    )

    await _apply_migrations(connection, starting_from=5)

    placements = {
        row[0]: row[1]
        for row in await connection.execute(text("SELECT name, scope FROM workspaces"))
    }
    assert placements == {"legacy global": "~", "rig view": "@rig"}

    edits = (await connection.execute(text("SELECT count(*) FROM workspace_edits"))).scalar_one()
    assert edits == 1


async def test_placement_column_rejects_a_null(connection) -> None:
    await _apply_migrations(connection)

    with pytest.raises(Exception, match="null value"):
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, name, scope, data) VALUES "
                "('44444444-4444-4444-4444-444444444444', 'legacy', NULL, '{}')"
            )
        )
