from typing import Any

import pytest

from ceres.config import TursoDatabaseConfig
from ceres.database import Database, TursoDatabase
from ceres.error import DatabaseLoadError

pytest.importorskip("turso", reason="'pyturso' has no wheel for this platform")


async def test_a_turso_config_builds_a_turso_database(tmp_path):
    database = Database(TursoDatabaseConfig(path=tmp_path / "ceres.db"))
    try:
        assert isinstance(database, TursoDatabase)
        assert database.url.startswith("sqlite+aioturso://")
    finally:
        await database.dispose()


async def test_writes_serialize_by_default(tmp_path):
    """Nothing overlaps until a deployment asks for it.

    Two writers on a database left at its defaults behave the way they would on SQLite, so the
    optimistic behavior cannot surprise anyone who did not opt in.
    """
    database = Database(TursoDatabaseConfig(path=tmp_path / "ceres.db"))
    try:
        await database.migrate()

        async with database.engine.begin() as first:
            await first.exec_driver_sql("CREATE TABLE probe (k TEXT PRIMARY KEY, v TEXT)")

        with database.concurrent_transactions():
            async with database.engine.begin() as connection:
                await connection.exec_driver_sql("INSERT INTO probe VALUES ('a', '1')")

        async with database.engine.connect() as connection:
            result = await connection.exec_driver_sql("SELECT count(*) FROM probe")
            assert result.scalar() == 1
    finally:
        await database.dispose()


async def test_enabling_mvcc_lets_two_writers_overlap(tmp_path):
    """Two connections hold open write transactions at once and both commit.

    This is the reason the backend exists. The same pair against SQLite fails with
    `database is locked`, because only one writer may hold the lock.
    """
    config = TursoDatabaseConfig(path=tmp_path / "ceres.db", mvcc=True)
    database = Database(config)
    try:
        await database.migrate()

        async with database.engine.begin() as connection:
            await connection.exec_driver_sql("CREATE TABLE probe (k TEXT PRIMARY KEY, v TEXT)")

        with database.concurrent_transactions():
            first = await database.engine.connect()
            second = await database.engine.connect()
            try:
                await first.exec_driver_sql("INSERT INTO probe VALUES ('a', '1')")
                await second.exec_driver_sql("INSERT INTO probe VALUES ('b', '2')")
                await first.commit()
                await second.commit()
            finally:
                await first.close()
                await second.close()

        async with database.engine.connect() as connection:
            result = await connection.exec_driver_sql("SELECT count(*) FROM probe")
            assert result.scalar() == 2
    finally:
        await database.dispose()


async def test_migrations_apply_the_sqlite_scripts(tmp_path):
    """Turso has no migration scripts of its own and runs SQLite's."""
    database = Database(TursoDatabaseConfig(path=tmp_path / "ceres.db"))
    try:
        applied = await database.migrate()
        assert applied

        async with database.engine.connect() as connection:
            result = await connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_schema WHERE type = 'table' AND name = 'workspaces'"
            )
            assert result.scalar() == 1
    finally:
        await database.dispose()


def test_a_missing_package_explains_itself(monkeypatch):
    """Asking for the backend on a platform without the package names the way out."""
    import builtins

    original = builtins.__import__

    def fail(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("turso"):
            raise ImportError(name)

        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail)

    with pytest.raises(DatabaseLoadError) as error:
        Database(TursoDatabaseConfig())

    assert "pyturso" in error.value.message
