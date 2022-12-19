import traceback
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import gettempdir
from typing import Any, final

from sqlalchemy import NullPool, event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from ....config import SQLiteDatabaseConfig
from ..adapter import DatabaseAdapter


@final
class SQLiteDatabaseAdapter(DatabaseAdapter[SQLiteDatabaseConfig]):
    def get_engine_url(self) -> str:
        # If a path is provided, create an database at the provided path.
        if self.config.path:
            return f"sqlite+aiosqlite:///{self.config.path.resolve()}"

        # Otherwise create a temporary on-disk database.
        return f"sqlite+aiosqlite:///{self.__get_temporary_path()}"

    def __del__(self) -> None:
        if self.config.path or not self.__get_temporary_path().exists():
            return

        try:
            for path in Path(gettempdir()).glob(f"*{self.id}*"):
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    traceback.print_exc()
        except Exception:
            traceback.print_exc()

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": NullPool,
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

    def __get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"
