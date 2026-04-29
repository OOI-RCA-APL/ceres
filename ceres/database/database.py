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

from ceres.__internal__.database.bytes import tokenize_bytes
from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.lazy import __lazy_imports__
from ceres.concurrency import spawn
from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.data import PasswordHash, to_json, uuid4
from ceres.error import DatabaseInitError, Failure

if TYPE_CHECKING:
    import sqlite3
    from uuid import UUID

    from sqlalchemy import Connection
    from sqlalchemy.dialects.sqlite.aiosqlite import AsyncAdapt_aiosqlite_connection
    from sqlalchemy.engine.interfaces import DBAPIConnection

    from ceres.__internal__.entity import BaseEntityManager, BaseEntityRow
    from ceres.database import DatabaseType
    from ceres.entity import Entity

    _SQLiteConnection = AsyncAdapt_aiosqlite_connection | sqlite3.Connection
else:
    _SQLiteConnection = object


with __lazy_imports__(__name__):
    from ceres.__internal__.auth import get_password_hash, verify_password, verify_password_hash
    from ceres.alert import AlertManager
    from ceres.logs import LogManager
    from ceres.message import MessageManager
    from ceres.particle import ParticleManager
    from ceres.setting import SettingManager
    from ceres.statistics import StatisticsManager
    from ceres.user import UserManager
    from ceres.variable import VariableManager
    from ceres.workspace import WorkspaceEditManager, WorkspaceManager, WorkspaceMembershipManager

__all__ = [
    "Database",
    "SQLiteDatabase",
    "PostgresDatabase",
]


class Database:
    """Asynchronous database handle backing all persisted Ceres state.

    `Database` owns the SQLAlchemy async engine, exposes cached entity managers for every
    persisted record type, and handles one-time schema initialization. Instantiating the base
    class dispatches to the appropriate concrete subclass based on the configuration, so
    `Database(SQLiteDatabaseConfig())` returns a `SQLiteDatabase` and
    `Database(PostgresDatabaseConfig(...))` returns a `PostgresDatabase`.
    """

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
        """Identifier unique to this `Database` instance for this process."""
        return self._id

    @property
    def config(self) -> DatabaseConfig:
        """Configuration object the database was constructed from."""
        return self._config

    @property
    def type(self) -> DatabaseType:
        """Backend kind, either `DatabaseType.SQLITE` or `DatabaseType.POSTGRES`."""
        return self._config.type

    @property
    def engine(self) -> AsyncEngine:
        """Underlying SQLAlchemy async engine."""
        return self._engine

    @property
    def ddl(self) -> list[str]:
        """Collect every DDL statement needed to create the schema on this backend."""
        commands: list[str] = []

        for cls in _get_entity_row_classes():
            commands.extend(cls.get_ddl(self._engine.sync_engine))

        return commands

    @cached_property
    def messages(self) -> MessageManager:
        """Manager for `Message` records."""
        return MessageManager(self)

    @cached_property
    def particles(self) -> ParticleManager:
        """Manager for `Particle` records."""
        return ParticleManager(self)

    @cached_property
    def alerts(self) -> AlertManager:
        """Manager for `Alert` records."""
        return AlertManager(self)

    @cached_property
    def logs(self) -> LogManager:
        """Manager for log entry records."""
        return LogManager(self)

    @cached_property
    def users(self) -> UserManager:
        """Manager for `User` records."""
        return UserManager(self)

    @cached_property
    def variables(self) -> VariableManager:
        """Manager for `Variable` records."""
        return VariableManager(self)

    @cached_property
    def settings(self) -> SettingManager:
        """Manager for `Setting` records."""
        return SettingManager(self)

    @cached_property
    def workspaces(self) -> WorkspaceManager:
        """Manager for `Workspace` records."""
        return WorkspaceManager(self)

    @cached_property
    def workspace_memberships(self) -> WorkspaceMembershipManager:
        """Manager for `WorkspaceMembership` records."""
        return WorkspaceMembershipManager(self)

    @cached_property
    def workspace_edits(self) -> WorkspaceEditManager:
        """Manager for `WorkspaceEdit` records."""
        return WorkspaceEditManager(self)

    @cached_property
    def statistics(self) -> StatisticsManager:
        """Manager for aggregate statistics across persisted records."""
        return StatisticsManager(self)

    def __manager__(self, Entity: type[Entity], /) -> BaseEntityManager:
        from ceres.__internal__.entity import get_entity_manager

        return get_entity_manager(self, Entity)

    @property
    @abstractmethod
    def url(self) -> str:
        """SQLAlchemy connection URL string used to build the engine."""
        ...

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
        """Yield every SQL command to run the first time the database is connected to."""
        yield from self._get_base_init_commands()
        yield from self.config.hooks.init or ()

    def _get_base_init_commands(self) -> Iterable[str]:
        """Yield the base backend-defined SQL commands run on first connect."""
        yield from ()

    @final
    def _get_connect_commands(self) -> Iterable[str]:
        """Yield every SQL command to run on each new connection."""
        yield from self._get_base_connect_commands()
        yield from self.config.hooks.connect or ()

    def _get_base_connect_commands(self) -> Iterable[str]:
        """Yield the base backend-defined SQL commands run on each new connection."""
        yield from ()

    @final
    def _get_close_commands(self) -> Iterable[str]:
        """Yield every SQL command to run when a connection is being closed."""
        yield from self._get_base_close_commands()
        yield from self.config.hooks.close or ()

    def _get_base_close_commands(self) -> Iterable[str]:
        """Yield the base backend-defined SQL commands run when a connection is closed."""
        yield from ()

    def session(self) -> AsyncSession:
        """Open a new ORM session bound to this database's engine.

        Returns:
            A fresh `AsyncSession` with `expire_on_commit=False` so loaded objects remain
            usable after a commit.
        """
        return AsyncSession(self._engine, expire_on_commit=False)

    def connect(self) -> AsyncConnection:
        """Open a new low-level async connection from the engine's pool.

        Returns:
            An `AsyncConnection` the caller is responsible for entering as a context manager
            to release back to the pool.
        """
        return self._engine.connect()

    async def use(self) -> AsyncConnection:
        """Ensure the schema is initialized, then open a new connection.

        Returns:
            An `AsyncConnection` ready for use against an initialized database.
        """
        await self.init()
        return self.connect()

    async def ping(self) -> bool:
        """Check whether the database is reachable.

        Returns:
            `True` if a connection can be opened successfully, `False` otherwise.
        """
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
        """Dispose of the underlying engine, closing any pooled connections."""
        with wrap_database_errors():
            await self._engine.dispose()

    async def init(self) -> None:
        """Run every DDL statement needed to bring the schema up to date.

        The work runs at most once per `Database` instance, subsequent calls are a cheap no-op so
        it is safe to call at the start of any operation that needs the schema.

        Raises:
            Failure: If schema creation fails, wrapping a `DatabaseInitError`.
        """
        with wrap_database_errors():
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
        """Delete every row from every known entity table, preserving the schema itself."""
        with wrap_database_errors():
            async with self._engine.begin() as connection:
                for cls in reversed(_get_entity_row_classes()):
                    await connection.execute(delete(cls))

                await connection.commit()

    async def initialized(self) -> bool:
        """Check whether the database already has tables in it.

        Returns:
            `True` if any tables exist in the database, `False` on a fresh database.
        """
        with wrap_database_errors():
            return await self._run_sync(
                lambda connection: bool(inspect(connection).get_table_names())
            )

    async def hash_password(self, password: str) -> PasswordHash:
        """Hash a plaintext password using the configured hashing parameters.

        The hashing work runs on a worker thread so it does not block the event loop.

        Args:
            password: Plaintext password to hash.

        Returns:
            The resulting password hash.
        """

        def execute() -> PasswordHash:
            return get_password_hash(password, self.config.hashing)

        return await spawn(execute)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        """Check whether a plaintext password matches a stored hash.

        If `hash` is not already a valid password hash it is first hashed with the configured
        parameters, so passing a plaintext value in both arguments verifies the value against
        itself. The comparison runs on a worker thread.

        Args:
            password: Plaintext password to verify.
            hash: Stored password hash to compare against.

        Returns:
            `True` if the password matches the hash, `False` otherwise.
        """
        hash = await self._maybe_hash_password(hash)

        def execute() -> bool:
            return verify_password(password, hash)

        return await spawn(execute)

    async def _maybe_hash_password(self, password: str) -> PasswordHash:
        if verify_password_hash(password):
            return password

        return await self.hash_password(password)

    async def _run_sync[T](self, callback: Callable[[Connection], T]) -> T:
        with wrap_database_errors():
            async with self.connect() as connection:
                return await connection.run_sync(callback)


@final
class SQLiteDatabase(Database):
    """`Database` backed by a local SQLite file or a per-process temporary file.

    When `config.path` is unset, `SQLiteDatabase` creates a temporary on-disk database whose files
    are cleaned up when the instance is disposed.
    """

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
        """Filesystem path of the SQLite database file.

        Returns the configured `config.path` when set, otherwise a temporary path derived
        from this instance's `id`.
        """
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
    """`Database` backed by a PostgreSQL server reached over `asyncpg`."""

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
