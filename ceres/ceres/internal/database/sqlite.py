from __future__ import annotations

from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...config import DatabaseConfig, DatabaseKind
from .manager import DatabaseManager


class SQLiteDatabaseManager(DatabaseManager):
    @classmethod
    def _create_engine(cls, config: DatabaseConfig) -> AsyncEngine:
        if config.kind != DatabaseKind.SQLITE:
            raise ValueError(config.kind)

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{config.path.resolve()}",
            **{
                "pool_pre_ping": True,  # Check to see if a connection has closed before use.
                "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
            },
            **(config.engine or {}),
        )

        @event.listens_for(engine.sync_engine, "connect")  # type: ignore
        def connect(connection: SQLiteConnection, *args: Any) -> None:
            # Disable the "sqlite3" handling of automatic "BEGIN" statements.
            connection.isolation_level = None
            # Enable foreign key handling defalt.
            # cursor = dbapi_connection.cursor()
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine.sync_engine, "begin")  # type: ignore
        def begin(connection: Connection) -> None:
            # Add our own "BEGIN" statement when requested.
            connection.exec_driver_sql("BEGIN")

        return engine

    def _create_ddl_statements(self) -> list[str]:
        return [
            """
            CREATE TABLE IF NOT EXISTS units (
                id TEXT NOT NULL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            ) STRICT
            """,
            """
            CREATE TABLE IF NOT EXISTS connections (
                id TEXT NOT NULL PRIMARY KEY,
                unit_id TEXT NOT NULL REFERENCES units,
                name text NOT NULL
            ) STRICT
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uk_connections__unit_id__name
                ON connections (unit_id, name)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_connections__unit_id
                ON connections (unit_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT NOT NULL PRIMARY KEY,
                connection_id TEXT NOT NULL REFERENCES connections,
                timestamp TEXT NOT NULL,
                direction TEXT NOT NULL,
                content TEXT NOT NULL,
                CHECK (direction in ('send', 'receive'))
            ) STRICT
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_messages__connection_id
                ON messages (connection_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_messages__timestamp
                ON messages (timestamp)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_messages__content
                ON messages (content)
            """,
        ]

    def _create_tables_query(str) -> str:
        return """
            SELECT name FROM sqlite_schema
                WHERE type='table'
                ORDER BY name
            """
