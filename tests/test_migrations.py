"""Cover the `Database` migration surface over the native runner.

The runner itself, the naming convention, and the migration scripts' behavior are pinned by
the Rust tests in `ceres-database`. What belongs here is the boundary: delegation through
the extension, the reporter protocol, the error types, and the registry the module holds.
`test_migrations_postgres.py` replays the migrations against PostgreSQL.
"""

import asyncio

import pytest

from ceres.__internal__.core import Migration
from ceres.config import SQLiteDatabaseConfig
from ceres.database import Database
from ceres.database.database import MIGRATIONS
from ceres.error import DatabaseMigrationError, DatabaseVersionError


@pytest.fixture
async def database():
    database = Database(SQLiteDatabaseConfig())
    try:
        yield database
    finally:
        await database.dispose()


def _migration(id: int, name: str, sql: str = "SELECT 1;") -> Migration:
    """A migration with one script shared across dialects."""
    return Migration(id, name, {None: sql})


async def _names(database: Database, kind: str) -> set[str]:
    """The names of every `kind` ("table" or "index") the schema holds."""
    rows = await database._store().fetch("SELECT name FROM sqlite_master WHERE type = ?", [kind])
    return {str(row["name"]) for row in rows}


def test_a_migration_without_a_dialect_script_is_a_noop():
    migration = Migration(1, "postgres-only", {"postgres": "SELECT 1;"})
    assert migration.render("sqlite") is None
    assert migration.render("postgresql") is not None


def test_a_migration_rejects_a_shared_and_dialect_mix():
    with pytest.raises(ValueError):
        Migration(1, "mixed", {None: "SELECT 1;", "sqlite": "SELECT 1;"})


def test_a_migration_rejects_an_unknown_dialect():
    with pytest.raises(ValueError):
        Migration(1, "unknown", {"mysql": "SELECT 1;"})


async def test_migrate_bootstraps_empty_database(database):
    applied = await database.migrate()
    assert 1 in applied

    # The baseline creates every entity table.
    assert {"users", "workspaces", "messages", "migrations"} <= await _names(database, "table")


async def test_migrate_is_idempotent(database):
    await database.migrate()
    assert await database.migrate() == []
    assert await database.get_pending_migrations() == []


async def test_migrate_applies_pending_in_order(database, monkeypatch):
    monkeypatch.setattr(
        "ceres.database.database.MIGRATIONS",
        [
            _migration(1, "first", "CREATE TABLE first (id INTEGER PRIMARY KEY);"),
            _migration(2, "second", "CREATE TABLE second (id INTEGER PRIMARY KEY);"),
        ],
    )

    applied = await database.migrate()
    assert applied == [1, 2]
    assert await database.get_pending_migrations() == []

    assert {"first", "second"} <= await _names(database, "table")


async def test_assert_schema_current_raises_on_pending(database, monkeypatch):
    monkeypatch.setattr(
        "ceres.database.database.MIGRATIONS",
        [_migration(1, "pending", "CREATE TABLE pending (id INTEGER PRIMARY KEY);")],
    )

    await database.migrate()
    await database._store().execute("DELETE FROM migrations", [])

    with pytest.raises(DatabaseVersionError) as context:
        await database.assert_schema_current()

    assert "ceres database migrate" in context.value.message


async def test_assert_schema_current_raises_on_unknown(database):
    await database.migrate()
    await database._store().execute(
        "INSERT INTO migrations (id, applied_at) VALUES (9999, '2026-01-01')", []
    )

    with pytest.raises(DatabaseVersionError) as context:
        await database.assert_schema_current()

    assert "newer" in context.value.message


async def test_migrate_is_safe_under_concurrent_calls(database, monkeypatch):
    monkeypatch.setattr(
        "ceres.database.database.MIGRATIONS",
        [_migration(1, "concurrent", "CREATE TABLE concurrent (id INTEGER PRIMARY KEY);")],
    )

    first_applied, second_applied = await asyncio.gather(database.migrate(), database.migrate())

    # Exactly one of the two callers applied the migration, the other found nothing pending.
    assert sorted(first_applied + second_applied) == [1]
    assert await database.get_pending_migrations() == []

    rows = await database._store().fetch("SELECT id FROM migrations", [])
    assert [row["id"] for row in rows] == [1]


def test_the_registry_holds_the_embedded_migrations():
    assert len(MIGRATIONS) == 9
    assert [migration.id for migration in MIGRATIONS] == list(range(1, 10))
    assert MIGRATIONS[0].render("sqlite") is not None


async def test_a_reporter_is_told_which_migration_is_running(database, monkeypatch):
    """Progress is drawn from these calls so they have to name each migration in order.

    A migration runs as one script so there is no progress to report from inside one.
    What a caller can draw is which is running and how far through the list it is, and
    that is exactly what `starting` carries.
    """
    monkeypatch.setattr(
        "ceres.database.database.MIGRATIONS",
        [
            _migration(1, "first", "CREATE TABLE first (id INTEGER PRIMARY KEY);"),
            _migration(2, "second", "CREATE TABLE second (id INTEGER PRIMARY KEY);"),
        ],
    )

    told: list[tuple[str, int, int, int]] = []

    class Reporter:
        def starting(self, migration, index, total):
            told.append(("starting", migration.id, index, total))

        def finished(self, migration):
            told.append(("finished", migration.id, -1, -1))

    assert await database.migrate(Reporter()) == [1, 2]
    assert told == [
        ("starting", 1, 0, 2),
        ("finished", 1, -1, -1),
        ("starting", 2, 0 + 1, 2),
        ("finished", 2, -1, -1),
    ]


async def test_a_migration_that_fails_is_never_reported_as_finished(database, monkeypatch):
    """A bar that filled on a failed migration would say the opposite of what happened."""
    monkeypatch.setattr(
        "ceres.database.database.MIGRATIONS",
        [_migration(1, "broken", "CREATE TABLE broken (this is not sql);")],
    )

    told: list[str] = []

    class Reporter:
        def starting(self, migration, index, total):
            told.append("starting")

        def finished(self, migration):
            told.append("finished")

    with pytest.raises(DatabaseMigrationError):
        await database.migrate(Reporter())

    assert told == ["starting"], "the migration was announced but never completed"
