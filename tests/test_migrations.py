import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ceres.database import Database
from ceres.database.migrations import load_migrations
from ceres.error import DatabaseVersionError


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
    assert await database.get_pending_migrations() == []


async def test_migrate_applies_pending_in_order(database, monkeypatch, tmp_path):
    _write(tmp_path, "0001-first.sql", "CREATE TABLE first (id INTEGER PRIMARY KEY);")
    _write(tmp_path, "0002-second.sql", "CREATE TABLE second (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    applied = await database.migrate()
    assert applied == [1, 2]
    assert await database.get_pending_migrations() == []

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

    with pytest.raises(DatabaseVersionError) as context:
        await database.assert_schema_current()

    assert "ceres database migrate" in context.value.message


async def test_assert_schema_current_raises_on_unknown(database):
    await database.migrate()
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO migrations (id, applied_at) VALUES (9999, '2026-01-01')")
        )

    with pytest.raises(DatabaseVersionError) as context:
        await database.assert_schema_current()

    assert "newer" in context.value.message


async def test_migrate_is_safe_under_concurrent_calls(database, monkeypatch, tmp_path):
    _write(tmp_path, "0001-concurrent.sql", "CREATE TABLE concurrent (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    # Force a yield point between "check what's pending" and "apply it" so two concurrent
    # `migrate()` calls are likely to interleave without the instance-level lock.
    original_pending_migrations = database.get_pending_migrations

    async def delayed_pending_migrations():
        pending = await original_pending_migrations()
        await asyncio.sleep(0.01)
        return pending

    monkeypatch.setattr(database, "get_pending_migrations", delayed_pending_migrations)

    first_applied, second_applied = await asyncio.gather(database.migrate(), database.migrate())

    # Exactly one of the two callers applied the migration, the other found nothing pending.
    assert sorted(first_applied + second_applied) == [1]
    assert await database.get_pending_migrations() == []

    async with database.engine.begin() as connection:
        result = await connection.execute(text("SELECT id FROM migrations"))
        assert [row[0] for row in result] == [1]


async def test_migration_2_transforms_old_schema(database):
    from ceres.database.migrations import MIGRATIONS

    baseline = next(migration for migration in MIGRATIONS if migration.id == 1)
    async with database.engine.begin() as connection:
        # Create workspaces with the pre-collapse check constraint first, so the baseline
        # script's `CREATE TABLE IF NOT EXISTS` leaves it alone. This reproduces a database
        # that predates the baseline snapshot, where `general_*` still allowed the wider
        # 'operators' and 'admins' values migration 2 is responsible for narrowing.
        await connection.execute(
            text(
                "CREATE TABLE workspaces ("
                "id CHAR(32) NOT NULL, "
                "name TEXT NOT NULL, "
                "general_viewership VARCHAR DEFAULT 'private' NOT NULL, "
                "general_editorship VARCHAR DEFAULT 'private' NOT NULL, "
                "general_managership VARCHAR DEFAULT 'private' NOT NULL, "
                "data JSON DEFAULT '{}' NOT NULL, "
                "CONSTRAINT pk_workspaces PRIMARY KEY (id), "
                "CONSTRAINT ck_workspaces__general_viewership "
                "CHECK (general_viewership IN ('anyone', 'operators', 'admins', 'private')), "
                "CONSTRAINT ck_workspaces__general_editorship "
                "CHECK (general_editorship IN ('anyone', 'operators', 'admins', 'private')), "
                "CONSTRAINT ck_workspaces__general_managership "
                "CHECK (general_managership IN ('anyone', 'operators', 'admins', 'private'))"
                ")"
            )
        )

        await database._execute_script(connection, baseline.script_for("sqlite"))
        await connection.execute(
            text(
                "INSERT INTO users (id, username, email, password, role, disabled) VALUES "
                "('u1', 'alice', 'a@a', 'x', 'admin', 0), "
                "('u2', 'bob', 'b@b', 'x', 'operator', 0), "
                "('u3', 'carol', 'c@c', 'x', 'viewer', 0)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO workspaces (id, name, general_viewership, general_editorship, "
                "general_managership, data) VALUES "
                "('w1', 'open', 'anyone', 'operators', 'admins', '{}')"
            )
        )
        await connection.execute(
            text("INSERT INTO settings (user_id, name, value) VALUES ('u1', 'theme', '\"dark\"')")
        )
        await connection.execute(
            text(
                "INSERT INTO workspace_memberships (user_id, workspace_id, role) VALUES "
                "('u1', 'w1', 'viewer')"
            )
        )

    await database.migrate()

    async with database.engine.begin() as connection:
        users = {
            row[0]: row[1] for row in await connection.execute(text("SELECT id, admin FROM users"))
        }
        assert users == {"u1": 1, "u2": 0, "u3": 0}

        columns = [row[1] for row in await connection.execute(text("PRAGMA table_info(users)"))]
        assert "role" not in columns

        workspace = (
            await connection.execute(
                text(
                    "SELECT general_viewership, general_editorship, general_managership "
                    "FROM workspaces WHERE id = 'w1'"
                )
            )
        ).one()
        assert tuple(workspace) == ("anyone", "private", "private")

        # The users table rebuild (required to drop `role` alongside its check
        # constraint) must preserve rows in tables that reference users by foreign key.
        setting = (
            await connection.execute(
                text("SELECT user_id, name, value FROM settings WHERE user_id = 'u1'")
            )
        ).one()
        assert tuple(setting) == ("u1", "theme", '"dark"')

        # The workspaces table rebuild (required to narrow its check constraints alongside
        # the data) must preserve rows in tables that reference workspaces by foreign key.
        membership = (
            await connection.execute(
                text(
                    "SELECT user_id, workspace_id, role FROM workspace_memberships "
                    "WHERE workspace_id = 'w1'"
                )
            )
        ).one()
        assert tuple(membership) == ("u1", "w1", "viewer")

    # The rebuilt workspaces table must enforce the narrowed check constraints, not just the
    # narrowed data, so pre-baseline databases reject wide values going forward too.
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO workspaces (id, name, general_viewership) VALUES "
                    "('w2', 'stale', 'operators')"
                )
            )
