from __future__ import annotations

from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import Engine as SyncEngine
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from ...config import SQLiteDatabaseConfig
from .adapter import DatabaseAdapter


class SQLiteDatabaseAdapter(DatabaseAdapter[SQLiteDatabaseConfig]):
    def create_async_engine(self) -> AsyncEngine:
        engine = super().create_async_engine()
        self._setup_listeners(engine.sync_engine)
        return engine

    def create_sync_engine(self) -> SyncEngine:
        engine = super().create_sync_engine()
        self._setup_listeners(engine)
        return engine

    def get_async_engine_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.config.path.resolve()}"

    def get_sync_engine_url(self) -> str:
        return f"sqlite:///{self.config.path.resolve()}"

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
            **(self.config.engine or {}),
        }

    def _setup_listeners(self, engine: SyncEngine) -> None:
        @event.listens_for(engine, "connect")
        def connect(connection: SQLiteConnection, *args: Any) -> None:
            # Disable the "sqlite3" handling of automatic "BEGIN" statements.
            connection.isolation_level = None
            # Enable foreign key handling defalt.
            # cursor = dbapi_connection.cursor()
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "begin")
        def begin(connection: Connection) -> None:
            # Add our own "BEGIN" statement when requested.
            connection.exec_driver_sql("BEGIN")
