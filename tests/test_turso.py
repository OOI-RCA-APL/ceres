"""Cover the Turso backend, which is SQLite's file format with concurrent writers.

Turso is compiled into Ceres rather than installed alongside it, so these never skip.
"""

import asyncio

import pytest

from ceres.config import SQLiteDatabaseConfig, TursoDatabaseConfig
from ceres.database import Database, TursoDatabase
from ceres.user import User


async def test_a_turso_config_builds_a_turso_database(tmp_path):
    database = Database(TursoDatabaseConfig(path=tmp_path / "ceres.db"))
    try:
        assert isinstance(database, TursoDatabase)
        assert await database.ping()
    finally:
        await database.dispose()


async def test_migrations_apply_the_sqlite_scripts(tmp_path):
    """Turso has no migration scripts of its own and runs SQLite's."""
    database = Database(TursoDatabaseConfig(path=tmp_path / "ceres.db"))
    try:
        applied = await database.migrate()
        assert applied

        rows = await database._store().fetch(
            "SELECT count(*) AS count FROM sqlite_schema "
            "WHERE type = 'table' AND name = 'workspaces'",
            [],
        )
        assert rows[0]["count"] == 1
    finally:
        await database.dispose()


async def test_a_file_turso_wrote_is_still_a_sqlite_file(tmp_path):
    """Left at its defaults this backend is a drop-in for SQLite, on the same file.

    `mvcc` is the one setting that breaks that, and it is off unless a deployment asks.
    """
    path = tmp_path / "ceres.db"
    database = Database(TursoDatabaseConfig(path=path))
    try:
        await database.migrate()
        await database.users.create(
            User.Create(username="alice", email="a@example.com", password="hunter2hunter2")
        )
    finally:
        await database.dispose()

    reopened = Database(SQLiteDatabaseConfig(path=path))
    try:
        assert [user.username for user in await reopened.users.where()] == ["alice"]
    finally:
        await reopened.dispose()


async def test_mvcc_journaling_still_reads_and_writes(tmp_path):
    """A database asking for MVCC migrates, writes, and reads back.

    This says the journaling mode is accepted and the schema works under it. That two
    write transactions genuinely overlap under it is a `ceres-database` test, where a
    transaction can be held open across another's write.
    """
    database = Database(TursoDatabaseConfig(path=tmp_path / "ceres.db", mvcc=True))
    try:
        await database.migrate()
        await database._store().execute_script("CREATE TABLE probe (k TEXT PRIMARY KEY, v TEXT);")

        store = database._store()
        await asyncio.gather(
            store.execute("INSERT INTO probe VALUES ('a', '1')", []),
            store.execute("INSERT INTO probe VALUES ('b', '2')", []),
        )

        rows = await store.fetch("SELECT count(*) AS count FROM probe", [])
        assert rows[0]["count"] == 2
    finally:
        await database.dispose()


async def test_a_write_conflict_is_a_failure_the_writer_requeues_on():
    """A flush that loses a race at commit keeps its records for the next one.

    A record flush now asks for a transaction that may overlap other writers, which trades
    blocking for a refusal at commit. The engine calls that "Write-write conflict", a
    wording neither constraint pattern recognizes, so it reaches the writer as the plain
    value error the store raised. This asserts that error is one the flush requeues on,
    because a failure outside that set would drop the records instead.
    """
    from ceres.__internal__.database.errors import wrap_database_errors
    from ceres.__internal__.database.writer import write_failures

    with pytest.raises(Exception) as raised:  # noqa: B017, PT011, PT012
        with wrap_database_errors():
            raise ValueError("Write-write conflict")

    assert isinstance(raised.value, write_failures()), (
        "a flush that lost a race puts its records back rather than dropping them"
    )
