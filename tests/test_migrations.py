import asyncio

import pytest
from sqlalchemy import text

from ceres.database import Database
from ceres.database.migrations import load_migrations
from ceres.error import DatabaseMigrationError


@pytest.fixture
async def database():
    database = Database()
    try:
        yield database
    finally:
        await database.dispose()


def _write(directory, filename, content="SELECT 1;"):
    (directory / filename).write_text(content)


def test_load_migrations_parses_ids_names_and_dialects(tmp_path):
    _write(tmp_path, "0001-init.sqlite.sql")
    _write(tmp_path, "0001-init.postgres.sql")
    _write(tmp_path, "0002-remove-user-roles.sql")

    migrations = load_migrations(tmp_path)
    assert [migration.id for migration in migrations] == [1, 2]
    assert migrations[0].name == "init"
    assert migrations[0].description == "Init"
    assert set(migrations[0].scripts) == {"sqlite", "postgresql"}
    assert set(migrations[1].scripts) == {None}


def test_load_migrations_rejects_duplicate_ids(tmp_path):
    _write(tmp_path, "0001-one.sql")
    _write(tmp_path, "0001-other.sql")

    with pytest.raises(ValueError):
        load_migrations(tmp_path)


def test_load_migrations_rejects_shared_and_dialect_mix(tmp_path):
    _write(tmp_path, "0001-one.sql")
    _write(tmp_path, "0001-one.sqlite.sql")

    with pytest.raises(ValueError):
        load_migrations(tmp_path)


def test_migration_without_dialect_script_is_noop(tmp_path):
    _write(tmp_path, "0001-postgres-only.postgres.sql")

    migrations = load_migrations(tmp_path)
    assert migrations[0].script_for("sqlite") is None
    assert migrations[0].script_for("postgresql") is not None


def test_load_migrations_rejects_unrecognized_filename(tmp_path):
    _write(tmp_path, "not-a-migration.sql")

    with pytest.raises(ValueError):
        load_migrations(tmp_path)


def test_load_migrations_returns_empty_list_for_empty_directory(tmp_path):
    assert load_migrations(tmp_path) == []


async def test_migrate_bootstraps_empty_database(database):
    applied = await database.migrate()
    assert 1 in applied

    # The baseline creates every entity table.
    async with database.engine.begin() as connection:
        tables = {
            row[0]
            for row in await connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }

    assert {"users", "workspaces", "messages", "migrations"} <= tables


async def test_migrate_is_idempotent(database):
    await database.migrate()
    assert await database.migrate() == []
    assert await database.pending_migrations() == []


async def test_migrate_applies_pending_in_order(database, monkeypatch, tmp_path):
    _write(tmp_path, "0001-first.sql", "CREATE TABLE first (id INTEGER PRIMARY KEY);")
    _write(tmp_path, "0002-second.sql", "CREATE TABLE second (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    applied = await database.migrate()
    assert applied == [1, 2]
    assert await database.pending_migrations() == []

    async with database.engine.begin() as connection:
        tables = {
            row[0]
            for row in await connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }

    assert {"first", "second"} <= tables


async def test_migrate_executes_multi_statement_scripts(database, monkeypatch, tmp_path):
    _write(
        tmp_path,
        "0001-multi.sql",
        "CREATE TABLE one (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE two (id INTEGER PRIMARY KEY);\n"
        "CREATE INDEX ix_two ON two (id);",
    )
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    await database.migrate()

    async with database.engine.begin() as connection:
        tables = {
            row[0]
            for row in await connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
        indexes = {
            row[0]
            for row in await connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index'")
            )
        }

    assert {"one", "two"} <= tables
    assert "ix_two" in indexes


async def test_assert_schema_current_raises_on_pending(database, monkeypatch, tmp_path):
    _write(tmp_path, "0001-pending.sql", "CREATE TABLE pending (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    await database.migrate()
    async with database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM migrations"))

    with pytest.raises(DatabaseMigrationError) as context:
        await database.assert_schema_current()

    assert "ceres database migrate" in context.value.message


async def test_assert_schema_current_raises_on_unknown(database):
    await database.migrate()
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO migrations (id, applied_at) VALUES (9999, '2026-01-01')")
        )

    with pytest.raises(DatabaseMigrationError) as context:
        await database.assert_schema_current()

    assert "newer" in context.value.message


async def test_migrate_is_safe_under_concurrent_calls(database, monkeypatch, tmp_path):
    _write(tmp_path, "0001-concurrent.sql", "CREATE TABLE concurrent (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    # Force a yield point between "check what's pending" and "apply it" so two concurrent
    # `migrate()` calls are likely to interleave without the instance-level lock.
    original_pending_migrations = database.pending_migrations

    async def delayed_pending_migrations():
        pending = await original_pending_migrations()
        await asyncio.sleep(0.01)
        return pending

    monkeypatch.setattr(database, "pending_migrations", delayed_pending_migrations)

    first_applied, second_applied = await asyncio.gather(database.migrate(), database.migrate())

    # Exactly one of the two callers applied the migration, the other found nothing pending.
    assert sorted(first_applied + second_applied) == [1]
    assert await database.pending_migrations() == []

    async with database.engine.begin() as connection:
        result = await connection.execute(text("SELECT id FROM migrations"))
        assert [row[0] for row in result] == [1]
