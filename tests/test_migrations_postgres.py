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
from ceres_core import Store

from ceres.database.migrations import MIGRATIONS
from tests import postgres
from tests.postgres import POSTGRES_URL

SCHEMA = f"ceres_migration_test_{os.getpid()}"
"""Throwaway schema every statement runs in, so the deployment's own tables are never touched.

The process ID is part of the name because the fixture drops the schema on the way in and out, and
two suite runs against one server would otherwise pull it out from under each other.
"""


def _store(schema: str | None = None) -> Store:
    """Open a store on the test server, optionally with `schema` first on the search path.

    `public` stays on the path behind it so extensions installed there, such as `pg_trgm`
    and its operator classes, resolve while the tables themselves land in the throwaway
    schema.
    """
    settings = [] if schema is None else [("search_path", f"{schema},public")]
    return Store.postgres(**postgres._parts(), settings=settings)


async def _reachable() -> bool:
    try:
        await _store().fetch("SELECT 1 AS one", [])
        return True
    except Exception:
        return False


async def _apply_migrations(store: Store, starting_from: int = 1, through: int | None = None):
    """Apply migrations in order, bounded by `starting_from` and `through` inclusive."""
    for migration in MIGRATIONS:
        if migration.id < starting_from:
            continue
        if through is not None and migration.id > through:
            return

        sql = migration.render("postgres")
        if sql is None:
            continue

        await store.execute_script(sql)


@pytest.fixture
async def store():
    if not await _reachable():
        pytest.skip(f"no PostgreSQL server at {POSTGRES_URL}")

    admin = _store()
    await admin.execute_script(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;\nCREATE SCHEMA {SCHEMA};")
    try:
        yield _store(SCHEMA)
    finally:
        await admin.execute_script(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;")


async def test_every_migration_applies(store) -> None:
    await _apply_migrations(store)

    rows = await store.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = $1", [SCHEMA]
    )
    tables = {str(row["table_name"]) for row in rows}

    assert "workspaces" in tables
    assert "users" in tables


async def test_workspace_columns_match_the_orm_types(store) -> None:
    """Identifier columns must be `uuid`, matching the primary keys they reference."""
    await _apply_migrations(store)

    rows = await store.fetch(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = $1 AND table_name = 'workspaces'",
        [SCHEMA],
    )
    columns = {
        str(row["column_name"]): (str(row["data_type"]), str(row["is_nullable"])) for row in rows
    }

    assert columns["owner_id"] == ("uuid", "YES")
    assert columns["scope"] == ("text", "NO")
    assert columns["show_when_logged_out"] == ("boolean", "NO")


async def test_placement_migration_converts_and_preserves_data(store) -> None:
    """A pre-placement global workspace becomes engine-placed, and referencing rows survive."""
    await _apply_migrations(store, through=4)

    await store.execute_script(
        "INSERT INTO users (id, username, email, password, admin, disabled) VALUES "
        "('11111111-1111-1111-1111-111111111111', 'alice', 'a@a', 'x', false, false);\n"
        "INSERT INTO workspaces (id, name, data) VALUES "
        "('22222222-2222-2222-2222-222222222222', 'legacy global', '{}');\n"
        "INSERT INTO workspaces (id, name, scope, data) VALUES "
        "('33333333-3333-3333-3333-333333333333', 'rig view', '@rig', '{}');\n"
        "INSERT INTO workspace_edits (user_id, workspace_id, data) VALUES "
        "('11111111-1111-1111-1111-111111111111', "
        "'22222222-2222-2222-2222-222222222222', '{\"layout\": []}');"
    )

    await _apply_migrations(store, starting_from=5)

    rows = await store.fetch("SELECT name, scope FROM workspaces", [])
    placements = {str(row["name"]): str(row["scope"]) for row in rows}
    assert placements == {"legacy global": "~", "rig view": "@rig"}

    rows = await store.fetch("SELECT count(*) AS count FROM workspace_edits", [])
    assert rows[0]["count"] == 1


async def test_placement_column_rejects_a_null(store) -> None:
    await _apply_migrations(store)

    with pytest.raises(Exception, match="null value"):
        await store.execute(
            "INSERT INTO workspaces (id, name, scope, data) VALUES "
            "('44444444-4444-4444-4444-444444444444', 'legacy', NULL, '{}')",
            [],
        )
