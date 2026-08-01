from pathlib import Path
from tempfile import gettempdir

import pytest

from ceres.config import SQLiteDatabaseConfig
from ceres.database import Database
from ceres.user import User


async def test_a_temporary_database_migrates_and_persists_schema_across_operations():
    """Schema and data survive across sequential operations on the same instance."""
    database = Database(SQLiteDatabaseConfig())
    try:
        applied = await database.migrate()
        assert 1 in applied

        created = await database.users.create(
            User.Create(username="alice", email="alice@test.com", password="hashed")
        )
        fetched = await database.users.get(created.id)
        assert fetched is not None
        assert fetched.username == "alice"
    finally:
        await database.dispose()


async def test_temporary_databases_are_isolated_from_each_other():
    """A row created in one temporary database is absent from a separate instance."""
    first = Database(SQLiteDatabaseConfig())
    second = Database(SQLiteDatabaseConfig())
    try:
        await first.migrate()
        await second.migrate()

        await first.users.create(
            User.Create(username="alice", email="alice@test.com", password="hashed")
        )

        assert await first.users.where(username="alice").first() is not None
        assert await second.users.where(username="alice").first() is None
    finally:
        await first.dispose()
        await second.dispose()


async def test_a_temporary_database_puts_its_files_in_the_temporary_directory():
    """A path nobody configured is still a real file, and disposal takes it away again."""
    database = Database(SQLiteDatabaseConfig())
    identifier = database.id
    await database.migrate()
    assert list(Path(gettempdir()).glob(f"*{identifier}*")) != []

    await database.dispose()
    assert list(Path(gettempdir()).glob(f"*{identifier}*")) == []


def test_the_in_memory_path_is_refused():
    """`:memory:` names a database nothing outside its one connection can join.

    Taken literally it would be a file with that name, which reads as a working database
    right up until someone looks for the data somewhere else, so the configuration refuses
    it and points at the temporary on-disk database an omitted path already gives.
    """
    with pytest.raises(ValueError) as raised:
        SQLiteDatabaseConfig(path=":memory:")

    assert "must name a file" in str(raised.value)


async def test_use_only_checks_initialized_once_per_instance(monkeypatch):
    """A second `use()` call does not re-run schema introspection on an already bootstrapped
    instance."""
    database = Database(SQLiteDatabaseConfig())
    try:
        calls = 0
        original_initialized = database.initialized

        async def counting_initialized() -> bool:
            nonlocal calls
            calls += 1
            return await original_initialized()

        monkeypatch.setattr(database, "initialized", counting_initialized)

        async with await database.use():
            pass

        assert calls == 1

        async with await database.use():
            pass

        assert calls == 1
    finally:
        await database.dispose()
