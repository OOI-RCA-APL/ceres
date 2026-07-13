import pytest
from sqlalchemy import text

from ceres.database import Database
from ceres.database.migrations import Migration
from ceres.error import DatabaseMigrationError


@pytest.fixture
async def database():
    database = Database()
    try:
        yield database
    finally:
        await database.dispose()


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


async def test_migrate_applies_pending_in_order(database, monkeypatch):
    applied_order: list[int] = []

    async def upgrade_one(connection):
        applied_order.append(1)

    async def upgrade_two(connection):
        applied_order.append(2)

    fake_migrations = [
        Migration(id=1, description="First test migration", upgrade=upgrade_one),
        Migration(id=2, description="Second test migration", upgrade=upgrade_two),
    ]
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", fake_migrations)

    applied = await database.migrate()
    assert applied == [1, 2]
    assert applied_order == [1, 2]
    assert await database.pending_migrations() == []


async def test_assert_schema_current_raises_on_pending(database, monkeypatch):
    async def upgrade(connection):
        pass

    monkeypatch.setattr(
        "ceres.database.migrations.MIGRATIONS",
        [Migration(id=1, description="Pending test migration", upgrade=upgrade)],
    )
    await database.migrate()
    async with database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM migrations"))

    with pytest.raises(DatabaseMigrationError) as context:
        await database.assert_schema_current()

    assert "ceres database migrate" in context.value.message


async def test_assert_schema_current_raises_on_unknown(database, monkeypatch):
    await database.migrate()
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO migrations (id, applied_at) VALUES (9999, '2026-01-01')")
        )

    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", [])
    with pytest.raises(DatabaseMigrationError) as context:
        await database.assert_schema_current()

    assert "newer" in context.value.message
