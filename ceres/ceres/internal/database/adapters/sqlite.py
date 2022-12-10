from sqlite3 import Connection as SQLiteConnection
from typing import Any, final
from uuid import uuid4

from sqlalchemy import NullPool, QueuePool, event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from ....config import SQLiteDatabaseConfig
from ..adapter import DatabaseAdapter


@final
class SQLiteDatabaseAdapter(DatabaseAdapter[SQLiteDatabaseConfig]):
    def __init__(self, config: SQLiteDatabaseConfig) -> None:
        super().__init__(config)
        self._memory_id = uuid4()  # Create a unique ID for in-memory database, if needed.

    def get_engine_url(self) -> str:
        # If a path is provided, create an on-disk database.
        if self.config.path:
            return f"sqlite+aiosqlite:///{self.config.path.resolve()}"

        # Otherwise create a named in-memory database.
        return f"sqlite+aiosqlite:///file:{self._memory_id}?mode=memory&cache=shared&uri=true"

    def get_engine_config(self) -> dict[str, Any]:
        # If a path is provided, we're using an on-disk database. In this case, use a 'NullPool' to
        # create a new connection for every session.
        if self.config.path:
            return {
                "poolclass": NullPool,
                **self.config.engine,
            }

        # Otherwise, use a 'QueuePool' to constantly maintain connections to the in-memory database.
        # If we used 'NullPool', which is the SQLAlchemy's default for SQLite, SQLite would free the
        # entire database every time the connection count went back down to zero.
        return {
            "poolclass": QueuePool,
            "pool_size": 24,  # Pool up to this number of connections.
            "max_overflow": -1,  # Allow more connections to be created when necessary.
            **self.config.engine,
        }

    def create_engine(self) -> AsyncEngine:
        engine = super().create_engine()

        @event.listens_for(engine.sync_engine, "connect")
        def connect(connection: SQLiteConnection, *args: Any) -> None:
            # Clear the isolation level to stop "pysqlite" from:
            #   1. Automatically emitting "BEGIN"
            #   2. Automatically emitting "COMMIT" before any DDL
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.isolation_level = None
            # Enable foreign key handling by default.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#foreign-key-support
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN")

        return engine
