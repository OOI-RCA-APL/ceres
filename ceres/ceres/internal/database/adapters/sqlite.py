from sqlite3 import Connection as SQLiteConnection
from typing import Any, final

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from ....config import SQLiteDatabaseConfig
from ..adapter import DatabaseAdapter


@final
class SQLiteDatabaseAdapter(DatabaseAdapter[SQLiteDatabaseConfig]):
    def get_engine_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.config.path.resolve()}"

    def create_engine(self) -> AsyncEngine:
        engine = super().create_engine()

        @event.listens_for(engine.sync_engine, "connect")
        def connect(connection: SQLiteConnection, *args: Any) -> None:
            # Clear the isolation level to stop "pysqlite" from:
            #   1. Automatically emitting "BEGIN"
            #   2. Automatically emitting "COMMIT" before any DDL
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            # connection.isolation_level = None
            # Enable foreign key handling by default.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#foreign-key-support
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN")

        return engine
