from pathlib import Path
from tempfile import gettempdir

from ceres.config import SQLiteDatabaseConfig
from ceres.database import Database
from ceres.user import User


async def test_in_memory_database_migrates_and_persists_schema_across_operations():
    """Schema and data survive across sequential operations on the same in-memory instance."""
    database = Database(SQLiteDatabaseConfig.in_memory())
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


async def test_in_memory_databases_are_isolated_from_each_other():
    """A row created in one in-memory database is absent from a separate instance."""
    first = Database(SQLiteDatabaseConfig.in_memory())
    second = Database(SQLiteDatabaseConfig.in_memory())
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


async def test_in_memory_database_creates_no_temporary_file():
    """No file appears in the temporary directory for an in-memory database."""
    database = Database(SQLiteDatabaseConfig.in_memory())
    try:
        await database.migrate()
        assert list(Path(gettempdir()).glob(f"*{database.id}*")) == []
    finally:
        await database.dispose()
