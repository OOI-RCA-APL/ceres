from __future__ import annotations

from sqlite3 import Connection as SQLiteConnection
from typing import Any

from sqlalchemy import Engine as SyncEngine
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ...config import DatabaseConfig, DatabaseKind
from .manager import DatabaseManager


class SQLiteDatabaseManager(DatabaseManager):
    @classmethod
    def _create_async_engine(cls, config: DatabaseConfig) -> AsyncEngine:
        if config.kind != DatabaseKind.SQLITE:
            raise ValueError(config.kind)

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{config.path.resolve()}",
            **cls._get_engine_config(config),
        )

        cls._setup_engine(engine.sync_engine)
        return engine

    @classmethod
    def _create_sync_engine(cls, config: DatabaseConfig) -> SyncEngine:
        if config.kind != DatabaseKind.SQLITE:
            raise ValueError(config.kind)

        engine = create_sync_engine(
            f"sqlite:///{config.path.resolve()}",
            **cls._get_engine_config(config),
        )

        cls._setup_engine(engine)
        return engine

    @classmethod
    def _get_engine_config(cls, config: DatabaseConfig) -> dict[str, Any]:
        return {
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Drop unused connections after 5 minutes.
            **(config.engine or {}),
        }

    @classmethod
    def _setup_engine(cls, engine: SyncEngine) -> None:
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
