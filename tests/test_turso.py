"""Cover the Turso backend, which is SQLite's file format with concurrent writers.

Turso is compiled into Ceres rather than installed alongside it, so these never skip.
"""

import asyncio

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

    This says the journaling mode is accepted and the schema works under it. It does not
    say two write transactions overlap, because nothing opens one yet. The native store
    begins every transaction plainly, so `mvcc` currently buys concurrent statements
    rather than concurrent transactions.
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
