import traceback
from abc import abstractmethod
from asyncio import Lock as AsyncLock
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from tempfile import gettempdir
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Self, final, override

from sqlalchemy import URL, AsyncAdaptedQueuePool, delete, event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.util import tokenize_bytes
from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.data import PasswordHash, to_json, uuid4
from ceres.error import DatabaseInitError, Failure
from ceres.threading import spawn

if TYPE_CHECKING:
    import sqlite3
    from uuid import UUID

    from sqlalchemy import Connection
    from sqlalchemy.dialects.sqlite.aiosqlite import AsyncAdapt_aiosqlite_connection
    from sqlalchemy.engine.interfaces import DBAPIConnection

    from ceres._internal.entity import BaseEntityManager, BaseEntityRow
    from ceres.database import DatabaseType
    from ceres.entity import Entity

    _SQLiteConnection = AsyncAdapt_aiosqlite_connection | sqlite3.Connection
else:
    _SQLiteConnection = object


with lazy_imports(__name__):
    from ceres._internal.auth import get_password_hash, verify_password, verify_password_hash
    from ceres.alert import AlertManager
    from ceres.logs import LogManager
    from ceres.message import MessageManager
    from ceres.particle import ParticleManager
    from ceres.setting import SettingManager
    from ceres.statistics import StatisticsManager
    from ceres.user import UserManager
    from ceres.variable import VariableManager
    from ceres.workspace import WorkspaceEditManager, WorkspaceManager, WorkspaceMembershipManager


class Database:
    def __new__(cls, config: DatabaseConfig | None = None, /) -> Database:
        if cls is Database:
            match config:
                case None | SQLiteDatabaseConfig():
                    return SQLiteDatabase(config)
                case PostgresDatabaseConfig():
                    return PostgresDatabase(config)

        return cls(config)

    def __init__(self, config: DatabaseConfig | None = None, /) -> None:
        assert config is not None

        self._id = uuid4()
        self._config = config
        self._engine = self._create_engine()
        self._init_lock = AsyncLock()
        self._init_completed = False

    @property
    def __database__(self) -> Database:
        return self

    def __get_filter_defaults__(self) -> dict[str, Any]:
        return {}

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def config(self) -> DatabaseConfig:
        return self._config

    @property
    def type(self) -> DatabaseType:
        return self._config.type

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def ddl(self) -> list[str]:
        commands: list[str] = []

        for cls in _get_entity_row_classes():
            commands.extend(cls.get_ddl(self._engine.sync_engine))

        return commands

    @cached_property
    def messages(self) -> MessageManager:
        return MessageManager(self)

    @cached_property
    def particles(self) -> ParticleManager:
        return ParticleManager(self)

    @cached_property
    def alerts(self) -> AlertManager:
        return AlertManager(self)

    @cached_property
    def logs(self) -> LogManager:
        return LogManager(self)

    @cached_property
    def users(self) -> UserManager:
        return UserManager(self)

    @cached_property
    def variables(self) -> VariableManager:
        return VariableManager(self)

    @cached_property
    def settings(self) -> SettingManager:
        return SettingManager(self)

    @cached_property
    def workspaces(self) -> WorkspaceManager:
        return WorkspaceManager(self)

    @cached_property
    def workspace_memberships(self) -> WorkspaceMembershipManager:
        return WorkspaceMembershipManager(self)

    @cached_property
    def workspace_edits(self) -> WorkspaceEditManager:
        return WorkspaceEditManager(self)

    @cached_property
    def statistics(self) -> StatisticsManager:
        return StatisticsManager(self)

    def __manager__(self, Entity: type[Entity], /) -> BaseEntityManager:
        return util.get_entity_manager(self, Entity)

    @property
    @abstractmethod
    def url(self) -> str: ...

    @abstractmethod
    def _get_engine_config(self) -> dict[str, Any]: ...

    @final
    def _create_engine(self) -> AsyncEngine:
        engine = create_async_engine(self.url, **self._get_engine_config())
        self._setup_engine(engine)
        return engine

    def _setup_engine(self, engine: AsyncEngine) -> None:
        on_init = [*self._get_base_init_commands(), *(self.config.hooks.init or ())]
        on_connect = [*self._get_base_connect_commands(), *(self.config.hooks.connect or ())]
        on_close = [*self._get_base_close_commands(), *(self.config.hooks.close or ())]

        if on_init:
            # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.first_connect
            @event.listens_for(engine.sync_engine, "first_connect")
            def first_connect(connection: DBAPIConnection, *args: object) -> None:
                cursor = connection.cursor()
                try:
                    for statement in on_init:
                        cursor.execute(statement)
                finally:
                    cursor.close()

        if on_connect:
            # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.connect
            @event.listens_for(engine.sync_engine, "connect")
            def connect(connection: DBAPIConnection, *args: object) -> None:
                cursor = connection.cursor()
                try:
                    for statement in on_connect:
                        cursor.execute(statement)
                finally:
                    cursor.close()

        if on_close:
            # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.close
            @event.listens_for(engine.sync_engine, "close")
            def close(connection: DBAPIConnection, *args: object) -> None:
                cursor = connection.cursor()
                try:
                    for statement in on_close:
                        cursor.execute(statement)
                finally:
                    cursor.close()

    @final
    def _get_init_commands(self) -> Iterable[str]:
        """Get all SQL commands to run when first connecting to the database."""
        yield from self._get_base_init_commands()
        yield from self.config.hooks.init or ()

    def _get_base_init_commands(self) -> Iterable[str]:
        """Get base SQL commands to run when first connecting to the database."""
        yield from ()

    @final
    def _get_connect_commands(self) -> Iterable[str]:
        """Get all SQL commands to run when connecting to the database."""
        yield from self._get_base_connect_commands()
        yield from self.config.hooks.connect or ()

    def _get_base_connect_commands(self) -> Iterable[str]:
        """Get base SQL commands to run when connecting to the database."""
        yield from ()

    @final
    def _get_close_commands(self) -> Iterable[str]:
        """Get all SQL commands to run when closing the database connection."""
        yield from self._get_base_close_commands()
        yield from self.config.hooks.close or ()

    def _get_base_close_commands(self) -> Iterable[str]:
        """Get base SQL commands to run when connecting to the database."""
        yield from ()

    def session(self) -> AsyncSession:
        return AsyncSession(self._engine, expire_on_commit=False)

    def connect(self) -> AsyncConnection:
        return self._engine.connect()

    async def use(self) -> AsyncConnection:
        await self.init()
        return self.connect()

    async def ping(self) -> bool:
        try:
            async with self.connect():
                return True
        except Exception:
            return False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.dispose()

    async def dispose(self) -> None:
        with util.wrap_database_errors():
            await self._engine.dispose()

    async def init(self) -> None:
        with util.wrap_database_errors():
            if self._init_completed:
                return

            async with self._init_lock:
                if self._init_completed:
                    return

                try:
                    async with self._engine.begin() as connection:
                        for statement in self.ddl:
                            await connection.execute(text(statement))
                except Exception as error:
                    raise Failure(DatabaseInitError(message=str(error))) from error

                self._init_completed = True

    async def clear(self) -> None:
        with util.wrap_database_errors():
            async with self._engine.begin() as connection:
                for cls in reversed(_get_entity_row_classes()):
                    await connection.execute(delete(cls))

                await connection.commit()

    async def initialized(self) -> bool:
        with util.wrap_database_errors():
            return await self._run_sync(
                lambda connection: bool(inspect(connection).get_table_names())
            )

    #
    # Users
    #

    async def hash_password(self, password: str) -> PasswordHash:
        def execute() -> PasswordHash:
            return get_password_hash(password, self.config.hashing)

        return await spawn(execute)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        hash = await self._maybe_hash_password(hash)

        def execute() -> bool:
            return verify_password(password, hash)

        return await spawn(execute)

    async def _maybe_hash_password(self, password: str) -> PasswordHash:
        if verify_password_hash(password):
            return password

        return await self.hash_password(password)

    async def _run_sync[T](self, callback: Callable[[Connection], T]) -> T:
        with util.wrap_database_errors():
            async with self.connect() as connection:
                return await connection.run_sync(callback)


@final
class SQLiteDatabase(Database):
    @override
    def __new__(cls, /, config: SQLiteDatabaseConfig | None = None) -> Self:
        instance = object.__new__(cls)
        cls.__init__(instance, config)
        return instance

    @override
    def __init__(self, /, config: SQLiteDatabaseConfig | None = None) -> None:
        super().__init__(config or SQLiteDatabaseConfig())

    @property
    @override
    def config(self) -> SQLiteDatabaseConfig:
        config = super().config
        assert isinstance(config, SQLiteDatabaseConfig)
        return config

    @property
    @override
    def url(self) -> str:
        return URL.create(
            "sqlite+aiosqlite",
            database=str(self.path),
            query=self.config.query or {},
        ).render_as_string(hide_password=False)

    @property
    def path(self) -> Path:
        # If a path is provided, create an database at the provided path.
        if self.config.path is not None:
            return self.config.path.absolute()

        # Otherwise create a temporary on-disk database.
        return self._get_temporary_path()

    def __del__(self) -> None:
        try:
            self._cleanup_temporary_files()
        except Exception:
            pass

    @override
    async def dispose(self) -> None:
        try:
            await super().dispose()
        finally:
            self._cleanup_temporary_files()

    @override
    def _get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_recycle": 15 * 60,  # Recreate connections after fifteen minutes.
            "json_serializer": to_json,  # Serialize any Pydantic compatible object to JSON.
            **self.config.engine,
        }

    @override
    def _setup_engine(self, engine: AsyncEngine) -> None:
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
        def connect(connection: _SQLiteConnection, *args: object) -> None:
            # Clear the isolation level to stop "sqlite3" from:
            #   1. Automatically emitting "BEGIN"
            #   2. Automatically emitting "COMMIT" before any DDL
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.isolation_level = None
            # Create custom functions.
            _sqlite_create_functions(connection)

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.ConnectionEvents.begin
        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN IMMEDIATE")

        # Apply base setup.
        super()._setup_engine(engine)

    @override
    def _get_base_init_commands(self) -> Iterable[str]:
        yield from super()._get_base_init_commands()
        # Enable incremental "auto_vacuum" mode when the first connection to the database is
        # made. This can only be done before database tables are created and is disabled by
        # default, so we do it here just in case "incremental_vacuum" is needed later on.
        # https://www.sqlite.org/pragma.html#pragma_auto_vacuum
        # https://www.sqlite.org/pragma.html#pragma_incremental_vacuum
        yield "PRAGMA auto_vacuum = INCREMENTAL"

    @override
    def _get_base_connect_commands(self) -> Iterable[str]:
        yield from super()._get_base_connect_commands()
        # Enable foreign key handling by default.
        # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#foreign-key-support
        yield "PRAGMA foreign_keys = ON"
        # Set like statements to be case sensitive to match Postgres.
        yield "PRAGMA case_sensitive_like = ON"
        # Enable a 30 second busy timeout.
        yield "PRAGMA busy_timeout = 30000"

    def _get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"

    def _cleanup_temporary_files(self) -> None:
        if self.config.path is None and self._get_temporary_path().exists():
            for path in Path(gettempdir()).glob(f"*{self.id}*"):
                path.unlink(missing_ok=True)


@final
class PostgresDatabase(Database):
    def __new__(cls, /, config: PostgresDatabaseConfig) -> Self:
        instance = object.__new__(cls)
        cls.__init__(instance, config)
        return instance

    def __init__(self, /, config: PostgresDatabaseConfig) -> None:
        super().__init__(config)

    @property
    @override
    def config(self) -> PostgresDatabaseConfig:
        config = super().config
        assert isinstance(config, PostgresDatabaseConfig)
        return config

    @property
    @override
    def url(self) -> str:
        return str(
            URL.create(
                "postgresql+asyncpg",
                username=self.config.user,
                password=self.config.password.get_secret_value()
                if self.config.password is not None
                else None,
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                query=self.config.query or {},
            ).render_as_string(hide_password=False)
        )

    @property
    @override
    def ddl(self) -> list[str]:
        commands: list[str] = []

        commands.append("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        commands.append(
            dedent(
                r"""
                CREATE OR REPLACE FUNCTION ceres_tokenize_bytes(bytes bytea) RETURNS TEXT
                IMMUTABLE
                LANGUAGE plpgsql AS $$
                    BEGIN
                        RETURN regexp_replace(encode($1, 'hex'), '(.{2})', '\1 ', 'g');
                    END;
                $$;
                """
            ).strip()
        )

        commands.extend(super().ddl)
        return commands

    @override
    def _get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Recreate connections after five minutes.
            "json_serializer": to_json,  # Serialize any Pydantic compatible object to JSON.
            **self.config.engine,
        }


def _ceres_tokenize_bytes(value: bytes) -> str:
    return tokenize_bytes(value)


def _ceres_date_bin(
    interval: float | object,
    value: str | object,
    origin: str | object,
) -> str | None:
    if not isinstance(interval, int | float):
        return None
    if not isinstance(value, str):
        return None
    if not isinstance(origin, str):
        return None

    value = datetime.fromisoformat(value)
    origin = datetime.fromisoformat(origin)
    delta = value - origin

    binned_seconds = (delta.total_seconds() // interval) * interval
    binned_time = origin + timedelta(seconds=binned_seconds)

    return binned_time.isoformat(" ")


def _sqlite_create_functions(connection: _SQLiteConnection) -> None:
    import sqlite3

    sqlite3.enable_callback_tracebacks(True)
    connection.create_function("ceres_tokenize_bytes", 1, _ceres_tokenize_bytes)
    connection.create_function("date_bin", 3, _ceres_date_bin)


def _get_entity_row_classes() -> list[type[BaseEntityRow]]:
    from ceres.alert import AlertRow
    from ceres.logs import LogEntryRow
    from ceres.message import MessageRow
    from ceres.particle import ParticleRow
    from ceres.setting import SettingRow
    from ceres.user import UserRow
    from ceres.variable import VariableRow
    from ceres.workspace import WorkspaceEditRow, WorkspaceMembershipRow, WorkspaceRow

    return [
        MessageRow,
        ParticleRow,
        AlertRow,
        LogEntryRow,
        UserRow,
        SettingRow,
        VariableRow,
        WorkspaceRow,
        WorkspaceMembershipRow,
        WorkspaceEditRow,
    ]
