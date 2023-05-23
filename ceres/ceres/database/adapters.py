import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import gettempdir
from typing import Any, Generic, TypeVar, final
from uuid import UUID

from sqlalchemy import QueuePool, event
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig

ConfigT = TypeVar("ConfigT", bound=DatabaseConfig, covariant=True)


class DatabaseAdapter(Generic[ConfigT], ABC):
    def __init__(self, id: UUID, config: ConfigT) -> None:
        self.__id = id
        self.__config = config

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def config(self) -> ConfigT:
        return self.__config

    @abstractmethod
    def get_engine_url(cls) -> str:
        ...

    @abstractmethod
    def get_engine_config(self) -> dict[str, Any]:
        ...

    def create_engine(self) -> AsyncEngine:
        return create_async_engine(
            self.get_engine_url(),
            **self.get_engine_config(),
        )


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
            "poolclass": QueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_recycle": 60,  # Recreate connections after one minute.
            **self.config.engine,
        }

    def create_engine(self) -> AsyncEngine:
        engine = super().create_engine()

        @event.listens_for(engine.sync_engine, "first_connect")
        def first_connect(connection: SQLiteConnection, *args: Any) -> None:
            # Enable incremental "auto_vacuum" mode when the first connection to the database is
            # made. This can only be done before database tables are created and is disabled by
            # default, so we do it here just in case "incremental_vacuum" is needed later on.
            # https://www.sqlite.org/pragma.html#pragma_auto_vacuum
            # https://www.sqlite.org/pragma.html#pragma_incremental_vacuum
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")

        @event.listens_for(engine.sync_engine, "connect")
        def connect(connection: SQLiteConnection, *args: Any) -> None:
            # Enable a 30 second busy timeout.
            connection.execute("PRAGMA busy_timeout = 30000")
            # Clear the isolation level to stop "pysqlite" from:
            #   1. Automatically emitting "BEGIN"
            #   2. Automatically emitting "COMMIT" before any DDL
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.isolation_level = None
            # Enable foreign key handling by default.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#foreign-key-support
            connection.execute("PRAGMA foreign_keys = ON")

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        @event.listens_for(engine.sync_engine, "close")
        def close(connection: SQLiteConnection, *args: Any) -> None:
            # Run optimize every time we close a database connection.
            # https://www.sqlite.org/lang_analyze.html
            try:
                connection.execute("PRAGMA analysis_limit = 500")
                connection.execute("PRAGMA optimize")
            except OperationalError:
                pass

        return engine

    def __get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"


@final
class PostgresDatabaseAdapter(DatabaseAdapter[PostgresDatabaseConfig]):
    def get_engine_url(self) -> str:
        return (
            "postgresql+psycopg://"
            + f"{self.config.user}:{self.config.password.get_secret_value()}"
            + f"@{self.config.host}:{self.config.port}/{self.config.database}"
        )

    def get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": QueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Recreate connections after five minutes.
            **self.config.engine,
        }
