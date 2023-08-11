import sqlite3
import traceback
from abc import ABC, abstractmethod
from os import PathLike
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import NamedTemporaryFile, gettempdir
from typing import Any, Generic, TypeVar, final
from uuid import UUID

from sqlalchemy import QueuePool, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from typing_extensions import override

from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.internal.database.entities import Entity
from ceres.threading import spawn

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

    async def dump(self, path: PathLike[str], *, update: bool = False) -> None:
        raise NotImplementedError()

    async def load(self, path: PathLike[str]) -> None:
        raise NotImplementedError()

    async def clone(self, path: PathLike[str]) -> None:
        raise NotImplementedError()


@final
class SQLiteDatabaseAdapter(DatabaseAdapter[SQLiteDatabaseConfig]):
    def get_engine_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.__get_path()}"

    def __del__(self) -> None:
        if self.config.path is not None or not self.__get_temporary_path().exists():
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
        self.__add_essential_listeners(engine)

        # https://docs.sqlalchemy.org/en/latest/core/events.html#sqlalchemy.events.PoolEvents.first_connect
        @event.listens_for(engine.sync_engine, "first_connect")
        def first_connect(connection: SQLiteConnection, *args: object) -> None:
            # Enable incremental "auto_vacuum" mode when the first connection to the database is
            # made. This can only be done before database tables are created and is disabled by
            # default, so we do it here just in case "incremental_vacuum" is needed later on.
            # https://www.sqlite.org/pragma.html#pragma_auto_vacuum
            # https://www.sqlite.org/pragma.html#pragma_incremental_vacuum
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.close
        @event.listens_for(engine.sync_engine, "close")
        def close(connection: SQLiteConnection, *args: object) -> None:
            # Run optimize every time we close a database connection.
            # https://www.sqlite.org/lang_analyze.html
            try:
                connection.execute("PRAGMA analysis_limit = 500")
                connection.execute("PRAGMA optimize")
            except OperationalError:
                pass

        return engine

    def __add_essential_listeners(self, engine: AsyncEngine) -> None:
        # https://docs.sqlalchemy.org/en/latest/core/events.html#sqlalchemy.events.DialectEvents.do_connect
        @event.listens_for(engine.sync_engine, "do_connect")
        def do_connect(*args: object) -> None:
            # Create the directory containing the database file if it doesn't already exist.
            if self.config.path is not None:
                try:
                    self.config.path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    traceback.print_exc()

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.connect
        @event.listens_for(engine.sync_engine, "connect")
        def connect(connection: SQLiteConnection, *args: object) -> None:
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

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.ConnectionEvents.begin
        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    @override
    async def clone(self, path: PathLike[str]) -> None:
        path = Path(path).absolute()

        if path.exists():
            path.unlink()

        def execute() -> None:
            with sqlite3.connect(self.__get_path()) as source_connection:
                with sqlite3.connect(path) as temporary_connection:
                    source_connection.backup(temporary_connection)

        await spawn(execute)

    @override
    async def dump(self, path: PathLike[str], *, update: bool = False) -> None:
        path = Path(path).absolute()

        if not update:
            if path.exists():
                path.unlink()

        with NamedTemporaryFile(prefix="ceres", suffix=".sqlite.temporary") as temporary_file:
            temporary_path = Path(temporary_file.name)
            await self.clone(temporary_path)

            source_engine = create_async_engine(f"sqlite+aiosqlite:///{temporary_path}")
            destination_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
            self.__add_essential_listeners(source_engine)
            self.__add_essential_listeners(destination_engine)

            async with destination_engine.begin() as destination_connection:
                for cls in Entity.get_entity_classes():
                    dump_cls = cls.get_entity_dump_cls()
                    if dump_cls is None:
                        continue

                    for statement in dump_cls.get_entity_ddl(destination_engine.sync_engine):
                        await destination_connection.execute(text(statement))

                await destination_connection.commit()

            async with source_engine.begin() as source_connection:
                await source_connection.execute(
                    text("ATTACH DATABASE :path AS output"), {"path": str(path)}
                )

                await source_connection.execute(
                    text(
                        """
                        INSERT INTO output.components (address, enabled)
                        SELECT address, enabled
                        FROM components
                        """
                    )
                )

                await source_connection.execute(
                    text(
                        """
                        INSERT INTO output.messages (id, address, timestamp, direction, content)
                        SELECT main.messages.id, address, timestamp, direction, content
                        FROM main.messages
                        JOIN main.bins ON main.messages.bin_id = main.bins.id
                        """
                    )
                )

                await source_connection.execute(
                    text(
                        """
                        INSERT INTO output.alerts (id, address, timestamp, level, code, info)
                        SELECT main.alerts.id, address, timestamp, level, code, info
                        FROM main.alerts
                        JOIN main.bins ON main.alerts.bin_id = main.bins.id
                        """
                    )
                )

                await source_connection.execute(
                    text(
                        """
                        INSERT INTO output.log_entries (id, address, timestamp, level, content)
                        SELECT main.log_entries.id, address, timestamp, level, content
                        FROM main.log_entries
                        JOIN main.bins ON main.log_entries.bin_id = main.bins.id
                        """
                    )
                )

                await source_connection.commit()

    @override
    async def load(self, path: PathLike[str]) -> None:
        destination_engine = self.create_engine()
        source_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        self.__add_essential_listeners(source_engine)

        async with destination_engine.begin() as destination_connection:
            for cls in Entity.get_entity_classes():
                for statement in cls.get_entity_ddl(destination_engine.sync_engine):
                    await destination_connection.execute(text(statement))

            await destination_connection.commit()

        async with source_engine.begin() as source_connection:
            await source_connection.execute(
                text("ATTACH DATABASE :path AS output"), {"path": str(self.__get_path())}
            )

            await source_connection.execute(
                text(
                    """
                    INSERT OR REPLACE INTO output.components (address, enabled)
                    SELECT address, enabled
                    FROM main.components
                    """
                )
            )

            await source_connection.execute(
                text(
                    """
                    INSERT OR REPLACE INTO output.bins (address)
                    SELECT address FROM main.components
                    UNION SELECT DISTINCT address FROM main.messages
                    UNION SELECT DISTINCT address FROM main.alerts
                    UNION SELECT DISTINCT address FROM main.log_entries
                    """
                )
            )

            await source_connection.execute(
                text(
                    """
                    INSERT OR REPLACE INTO output.messages (id, bin_id, timestamp, direction, content)
                    SELECT main.messages.id, output.bins.id, timestamp, direction, content
                    FROM main.messages
                    JOIN output.bins ON main.messages.address = output.bins.address
                    """  # noqa: E501
                )
            )

            await source_connection.execute(
                text(
                    """
                    INSERT OR REPLACE INTO output.alerts (id, bin_id, timestamp, level, code, info)
                    SELECT main.alerts.id, output.bins.id, timestamp, level, code, info
                    FROM main.alerts
                    JOIN output.bins ON main.alerts.address = output.bins.address
                    """
                )
            )

            await source_connection.execute(
                text(
                    """
                    INSERT OR REPLACE INTO output.log_entries (id, bin_id, timestamp, level, content)
                    SELECT main.log_entries.id, output.bins.id, timestamp, level, content
                    FROM main.log_entries
                    JOIN output.bins ON main.log_entries.address = output.bins.address
                    """  # noqa: E501
                )
            )

            await source_connection.commit()

    def __get_path(self) -> Path:
        # If a path is provided, create an database at the provided path.
        if self.config.path is not None:
            return self.config.path.absolute()

        # Otherwise create a temporary on-disk database.
        return self.__get_temporary_path()

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
