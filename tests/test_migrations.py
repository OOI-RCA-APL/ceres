"""Cover the migration runner itself, against SQLite specifically.

These tests read `sqlite_master` and write legacy schemas in SQLite's own types so they name
SQLite rather than taking whatever backend the run defaults to. `test_migrations_postgres.py`
replays the same migrations against PostgreSQL.
"""

import asyncio

import pytest

from ceres.config import SQLiteDatabaseConfig
from ceres.database import Database
from ceres.database.migrations import load_migrations
from ceres.error import DatabaseMigrationError, DatabaseVersionError


@pytest.fixture
async def database():
    database = Database(SQLiteDatabaseConfig())
    try:
        yield database
    finally:
        await database.dispose()


def _write(directory, filename, content="SELECT 1;"):
    (directory / filename).write_text(content)


async def _names(database: Database, kind: str) -> set[str]:
    """The names of every `kind` ("table" or "index") the schema holds."""
    rows = await database._store().fetch("SELECT name FROM sqlite_master WHERE type = ?", [kind])
    return {str(row["name"]) for row in rows}


async def _columns(database: Database, table: str) -> list[str]:
    """The column names of `table`, in declaration order."""
    rows = await database._store().fetch(f"PRAGMA table_info({table})", [])
    return [str(row["name"]) for row in rows]


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
    assert migrations[0].render("sqlite") is None
    assert migrations[0].render("postgresql") is not None


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
    assert {"users", "workspaces", "messages", "migrations"} <= await _names(database, "table")


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

    assert {"first", "second"} <= await _names(database, "table")


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

    assert {"one", "two"} <= await _names(database, "table")
    assert "ix_two" in await _names(database, "index")


async def test_assert_schema_current_raises_on_pending(database, monkeypatch, tmp_path):
    _write(tmp_path, "0001-pending.sql", "CREATE TABLE pending (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

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

    rows = await database._store().fetch("SELECT id FROM migrations", [])
    assert [row["id"] for row in rows] == [1]


async def test_migration_2_transforms_old_schema(database):
    from ceres.database.migrations import MIGRATIONS

    baseline = next(migration for migration in MIGRATIONS if migration.id == 1)
    store = database._store()

    # Create workspaces with the pre-collapse check constraint first so the baseline
    # script's `CREATE TABLE IF NOT EXISTS` leaves it alone. This reproduces a database
    # that predates the baseline snapshot, where `general_*` still allowed the wider
    # 'operators' and 'admins' values migration 2 is responsible for narrowing.
    await store.execute_script(
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
        ");"
    )
    await store.execute_script(baseline.render("sqlite"))
    await store.execute_script(
        "INSERT INTO users (id, username, email, password, role, disabled) VALUES "
        "('u1', 'alice', 'a@a', 'x', 'admin', 0), "
        "('u2', 'bob', 'b@b', 'x', 'operator', 0), "
        "('u3', 'carol', 'c@c', 'x', 'viewer', 0);\n"
        "INSERT INTO workspaces (id, name, general_viewership, general_editorship, "
        "general_managership, data) VALUES "
        "('w1', 'open', 'anyone', 'operators', 'admins', '{}');\n"
        "INSERT INTO settings (user_id, name, value) VALUES ('u1', 'theme', '\"dark\"');\n"
        "INSERT INTO workspace_memberships (user_id, workspace_id, role) VALUES "
        "('u1', 'w1', 'viewer');"
    )

    await database.migrate()

    rows = await store.fetch("SELECT id, admin FROM users", [])
    assert {str(row["id"]): row["admin"] for row in rows} == {"u1": 1, "u2": 0, "u3": 0}
    assert "role" not in await _columns(database, "users")

    # The users table rebuild (required to drop `role` alongside its check constraint) must
    # preserve rows in tables that reference users by foreign key.
    settings = await store.fetch(
        "SELECT user_id, name, value FROM settings WHERE user_id = 'u1'", []
    )
    assert [(row["user_id"], row["name"], row["value"]) for row in settings] == [
        ("u1", "theme", '"dark"')
    ]

    # The workspaces table is rebuilt three separate times across the migration sequence, to
    # narrow its check constraints, to make the placement column required, and to drop the
    # general access columns. The row has to survive every one of them.
    workspaces = await store.fetch("SELECT id, name, scope FROM workspaces WHERE id = 'w1'", [])
    assert [(row["id"], row["name"], row["scope"]) for row in workspaces] == [("w1", "open", "~")]

    # The general access columns and the memberships table are gone by the end of the
    # sequence so a database that predates the baseline still lands on the current schema.
    columns = await _columns(database, "workspaces")
    assert "general_viewership" not in columns
    assert "owner_id" in columns

    assert "workspace_memberships" not in await _names(database, "table")


async def test_a_table_rebuild_puts_back_the_foreign_keys_it_turned_off(database):
    """SQLite rebuilds a table by copying it, with foreign keys off across the swap.

    That pragma does nothing inside a transaction someone else opened so a runner that
    wrapped the whole script in one would leave the rebuilt tables without the constraints
    the migration meant to carry over. It would do it without failing, and the rows would
    still be there so the constraints themselves have to be checked.
    """
    await database.migrate()

    rows = await database._store().fetch(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL",
        [],
    )
    schema = {row["name"]: row["sql"] for row in rows}

    # Both of these are rebuilt by a later migration, and both point back at `users`.
    assert "REFERENCES users" in schema["group_memberships"]
    assert "REFERENCES users" in schema["user_permissions"]


def test_migrations_include_migration_3():
    from ceres.database.migrations import MIGRATIONS

    assert len(MIGRATIONS) == 8
    migration = next(migration for migration in MIGRATIONS if migration.id == 3)
    assert migration.render("sqlite") is not None
    assert migration.render("postgres") is not None


async def test_migration_3_converts_root_grants_and_deletes_root_state(database):
    from ceres.database.migrations import MIGRATIONS

    baseline = next(migration for migration in MIGRATIONS if migration.id == 1)
    store = database._store()

    await store.execute_script(baseline.render("sqlite"))
    await store.execute_script(
        "INSERT INTO users (id, username, email, password, role, disabled) VALUES "
        "('u1', 'alice', 'a@a', 'x', 'admin', 0);\n"
        "INSERT INTO user_permissions (user_id, target_type, target, level) VALUES "
        "('u1', 'component', '@', 'operate');\n"
        "INSERT INTO variables (address, name, value) VALUES ('@', 'enabled', 'true');"
    )

    await database.migrate()

    grants = await store.fetch(
        "SELECT target_type, target, level FROM user_permissions WHERE user_id = 'u1'", []
    )
    assert [(row["target_type"], row["target"], row["level"]) for row in grants] == [
        ("all", "", "operate")
    ]

    rows = await store.fetch("SELECT COUNT(*) AS count FROM variables WHERE address = '@'", [])
    assert rows[0]["count"] == 0


async def test_a_reporter_is_told_which_migration_is_running(database, monkeypatch, tmp_path):
    """Progress is drawn from these calls so they have to name each migration in order.

    A migration runs as one script so there is no progress to report from inside one.
    What a caller can draw is which is running and how far through the list it is, and
    that is exactly what `starting` carries.
    """
    _write(tmp_path, "0001-first.sql", "CREATE TABLE first (id INTEGER PRIMARY KEY);")
    _write(tmp_path, "0002-second.sql", "CREATE TABLE second (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

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


async def test_a_migration_that_fails_is_never_reported_as_finished(
    database, monkeypatch, tmp_path
):
    """A bar that filled on a failed migration would say the opposite of what happened."""
    _write(tmp_path, "0001-broken.sql", "CREATE TABLE broken (this is not sql);")
    monkeypatch.setattr("ceres.database.migrations.MIGRATIONS", load_migrations(tmp_path))

    told: list[str] = []

    class Reporter:
        def starting(self, migration, index, total):
            told.append("starting")

        def finished(self, migration):
            told.append("finished")

    with pytest.raises(DatabaseMigrationError):
        await database.migrate(Reporter())

    assert told == ["starting"], "the migration was announced but never completed"
