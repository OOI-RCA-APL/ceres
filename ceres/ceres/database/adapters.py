import shutil
import subprocess
import traceback
from abc import ABC, abstractmethod
from os import PathLike
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import NamedTemporaryFile, gettempdir
from typing import Any, Generic, TypeVar, final
from uuid import UUID, uuid4

from sqlalchemy import QueuePool, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from typing_extensions import LiteralString, override

from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.database.enums import DataFormat, TableOption
from ceres.directory import Directory
from ceres.internal.database.entities import Entity
from ceres.internal.utilities import sqlexpr, sqlstmt
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

    async def dump(self, table: TableOption, path: str | PathLike[str], format: DataFormat) -> None:
        match format:
            case DataFormat.CSV:
                return await self._dump_csv(table, path)
            case DataFormat.SQLITE:
                return await self._dump_sqlite(table, path)

    async def load(self, table: TableOption, path: str | PathLike[str], format: DataFormat) -> None:
        match format:
            case DataFormat.CSV:
                return await self._load_csv(table, path)
            case DataFormat.SQLITE:
                return await self._load_sqlite(table, path)

    @abstractmethod
    async def _dump_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        ...

    @abstractmethod
    async def _load_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        ...

    @abstractmethod
    async def _dump_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        ...

    @abstractmethod
    async def _load_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        ...


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
            "pool_recycle": 15 * 60,  # Recreate connections after fifteen minutes.
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
                connection.execute("PRAGMA analysis_limit = 1000")
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
            # Increase cache size to improve performance.
            connection.execute("PRAGMA cache_size = -64000")
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
    async def _load_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()

        destination_engine = self.create_engine()
        await Entity.create_all(destination_engine)
        await destination_engine.dispose()

        for table_name, path in _get_csv_dump_paths(table, path):
            try:
                subprocess.run(
                    [
                        "sqlite3",
                        str(self.__get_path()),
                        ".mode csv",
                        f".import '{path}' {table_name}",
                    ],
                    check=True,
                    capture_output=True,
                )
            except Exception as exception:
                raise RuntimeError(
                    f"failed to load CSV file '{path}' into table '{table}': {exception}"
                ) from exception

    @override
    async def _dump_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()
        _remove(path)

        if table == TableOption.ALL:
            path.mkdir(parents=True, exist_ok=True)

        for table_name, path in _get_csv_dump_paths(table, Path(path)):
            try:
                subprocess.run(
                    [
                        "sqlite3",
                        str(self.__get_path()),
                        ".mode csv",
                        f".output '{path}'",
                        f"SELECT * FROM {table_name};",
                    ],
                    check=True,
                    capture_output=True,
                )
            except Exception as exception:
                raise RuntimeError(
                    f"failed to dump table '{table}' to CSV file '{path}': {exception}"
                ) from exception

    async def __copy_sqlite(
        self,
        table: TableOption,
        source: Path,
        destination_engine: AsyncEngine,
        create: bool,
    ) -> None:
        async with destination_engine.connect() as destination_connection:
            if create:
                await destination_connection.execute(text("PRAGMA synchronous = OFF"))
                await destination_connection.execute(text("PRAGMA journal_mode = WAL"))
                await destination_connection.execute(text("PRAGMA foreign_keys = OFF"))
                await destination_connection.execute(text("PRAGMA cache_size = -128000"))

            await destination_connection.execute(
                text("ATTACH DATABASE :path AS source"), {"path": str(source)}
            )

            if table in (TableOption.ALL, TableOption.COMPONENTS):
                await destination_connection.execute(
                    text(
                        """
                        INSERT INTO main.components (address, enabled)
                        SELECT address, enabled
                        FROM source.components
                        """
                    )
                )

            if table in (
                TableOption.ALL,
                TableOption.MESSAGES,
                TableOption.ALERTS,
                TableOption.LOG_ENTRIES,
            ):
                await destination_connection.execute(
                    text(
                        """
                        INSERT INTO main.__bins (address)
                        SELECT address FROM source.__bins
                        WHERE address NOT IN (SELECT address FROM main.__bins)
                        """
                    )
                )

            if table in (TableOption.ALL, TableOption.MESSAGES):
                await destination_connection.execute(
                    text(
                        """
                        INSERT INTO main.__messages (id, bin_id, timestamp, direction, content)
                        SELECT source.messages.id, main.__bins.id, timestamp, direction, content
                        FROM source.messages
                        JOIN main.__bins ON source.messages.address = main.__bins.address
                        """  # noqa: E501
                    )
                )

            if table in (TableOption.ALL, TableOption.ALERTS):
                await destination_connection.execute(
                    text(
                        """
                        INSERT INTO main.__alerts (id, bin_id, timestamp, level, code, info)
                        SELECT source.alerts.id, main.__bins.id, timestamp, level, code, info
                        FROM source.alerts
                        JOIN main.__bins ON source.alerts.address = main.__bins.address
                        """
                    )
                )

            if table in (TableOption.ALL, TableOption.LOG_ENTRIES):
                await destination_connection.execute(
                    text(
                        """
                        INSERT INTO main.__log_entries (id, bin_id, timestamp, level, content)
                        SELECT source.log_entries.id, main.__bins.id, timestamp, level, content
                        FROM source.log_entries
                        JOIN main.__bins ON source.log_entries.address = main.__bins.address
                        """  # noqa: E501
                    )
                )

            await destination_connection.commit()

            if create:
                await destination_connection.execute(text("PRAGMA synchronous = FULL"))
                await destination_connection.execute(text("PRAGMA journal_mode = DELETE"))
                await destination_connection.commit()

    @override
    async def _dump_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()
        _remove(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if table == TableOption.ALL:

            def execute() -> None:
                subprocess.run(
                    [
                        "sqlite3",
                        str(self.__get_path()),
                        f".backup '{path}'",
                    ],
                    check=True,
                    capture_output=True,
                )

            await spawn(execute)
            return

        source_engine = self.create_engine()
        destination_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            await Entity.create_all(destination_engine)
            await self.__copy_sqlite(
                table,
                source=self.__get_path(),
                destination_engine=destination_engine,
                create=True,
            )
        finally:
            await source_engine.dispose()
            await destination_engine.dispose()

    @override
    async def _load_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()

        source_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        self.__add_essential_listeners(source_engine)

        destination_engine = self.create_engine()

        try:
            await Entity.create_all(destination_engine)
            await self.__copy_sqlite(
                table,
                source=path,
                destination_engine=destination_engine,
                create=False,
            )
        finally:
            await source_engine.dispose()
            await destination_engine.dispose()

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

    @override
    async def _dump_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()
        _remove(path)

        path.parent.mkdir(parents=True, exist_ok=True)
        if table == TableOption.ALL:
            path.mkdir()

        import psycopg

        url = self.get_engine_url().replace("+psycopg", "")

        async with await psycopg.AsyncConnection.connect(url) as connection:
            cursor = connection.cursor()

            async def write(
                destination: Path,
                statement: LiteralString,
            ) -> None:
                statement = sqlstmt(
                    f"""
COPY (
    {sqlexpr(statement, indent=1)}
) TO STDOUT WITH (FORMAT CSV)
"""
                )  # type: ignore

                with destination.open("wb") as stream:
                    async with cursor.copy(statement) as copy:
                        async for row in copy:
                            stream.write(row)

                    stream.flush()

            timestamp = "to_char(timestamp, 'YYYY-MM-DD HH24:MI:SS.US')"

            if table in (TableOption.ALL, TableOption.COMPONENTS):
                await write(
                    path if table == TableOption.COMPONENTS else path / "components.csv",
                    """
                    SELECT address, enabled::TEXT
                    FROM components
                    """,
                )
            if table in (TableOption.ALL, TableOption.MESSAGES):
                await write(
                    path if table == TableOption.MESSAGES else path / "messages.csv",
                    f"""
                    SELECT
                        id,
                        address,
                        {timestamp},
                        direction,
                        encode(content, 'escape')
                    FROM messages
                    """,
                )

            if table in (TableOption.ALL, TableOption.ALERTS):
                await write(
                    path if table == TableOption.ALERTS else path / "alerts.csv",
                    f"""
                    SELECT id, address, {timestamp}, level, code, info FROM alerts
                    """,
                )

            if table in (TableOption.ALL, TableOption.LOG_ENTRIES):
                await write(
                    path if table == TableOption.LOG_ENTRIES else path / "log-entries.csv",
                    f"""
                    SELECT id, address, {timestamp}, level, content FROM log_entries
                    """,
                )

    @override
    async def _load_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()
        paths = _get_csv_dump_paths(table, path)

        from psycopg import AsyncConnection

        destination_engine = self.create_engine()
        await Entity.create_all(destination_engine)
        await destination_engine.dispose()

        url = self.get_engine_url().replace("+psycopg", "")

        async with await AsyncConnection.connect(url) as connection:
            await connection.execute("BEGIN")
            cursor = connection.cursor()

            for table_name, path in paths:
                async with cursor.copy(
                    f"COPY {table_name} FROM STDIN (FORMAT CSV)"  # type: ignore
                ) as copy:
                    with path.open() as stream:
                        while chunk := stream.read(1024):
                            await copy.write(chunk)

            await connection.execute("COMMIT")

    @override
    async def _load_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()

        source_adapter = SQLiteDatabaseAdapter(uuid4(), SQLiteDatabaseConfig(path=path))
        if table == TableOption.ALL:
            temporary_directory = Directory()
            temporary_path = temporary_directory.path
        else:
            temporary_file = NamedTemporaryFile()
            temporary_path = temporary_file.name

        await source_adapter._dump_csv(table, temporary_path)
        await self._load_csv(table, temporary_path)

    @override
    async def _dump_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()
        _remove(path)

        destination_adapter = SQLiteDatabaseAdapter(uuid4(), SQLiteDatabaseConfig(path=path))

        if table == TableOption.ALL:
            temporary_directory = Directory()
            temporary_path = temporary_directory.path
        else:
            temporary_file = NamedTemporaryFile()
            temporary_path = temporary_file.name

        await self._dump_csv(table, temporary_path)
        await destination_adapter._load_csv(table, temporary_path)


def _get_csv_dump_paths(table: TableOption, path: Path) -> list[tuple[str, Path]]:
    if table == TableOption.ALL:
        return [
            ("components", path / "components.csv"),
            ("messages", path / "messages.csv"),
            ("alerts", path / "alerts.csv"),
            ("log_entries", path / "log-entries.csv"),
        ]

    return [(table.table_name, path)]


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, True)
    else:
        path.unlink(missing_ok=True)
