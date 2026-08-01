import traceback
from abc import abstractmethod
from asyncio import Lock as AsyncLock
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import cached_property
from pathlib import Path
from tempfile import gettempdir
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Self, final, override

from ceres_core import RecordFetcher, RecordWriter, Store
from sqlalchemy import URL, AsyncAdaptedQueuePool, delete, event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import QueuePool

from ceres.__internal__.database.bytes import tokenize_bytes
from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.lazy import __lazy_imports__
from ceres.concurrency import spawn
from ceres.config import (
    DatabaseConfig,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
    TursoDatabaseConfig,
)
from ceres.data import PasswordHash, to_json, uuid4
from ceres.error import DatabaseLoadError, DatabaseMigrationError, DatabaseVersionError
from ceres.logs import get_logger

DESTRUCTIVE_MIGRATIONS: dict[str, str] = {}
"""Migrations that discard data, keyed by name, with the warning logged before they run.

A migration belongs here only while operators still have it ahead of them. Once every deployment
has run it the warning is noise on each load, and a warning nobody can act on teaches people to
ignore the ones that matter.
"""

if TYPE_CHECKING:
    import sqlite3
    from uuid import UUID

    from sqlalchemy import Connection
    from sqlalchemy.dialects.sqlite.aiosqlite import AsyncAdapt_aiosqlite_connection
    from sqlalchemy.engine.interfaces import DBAPIConnection

    from ceres.__internal__.entity import BaseEntityManager, BaseEntityRow
    from ceres.database import DatabaseType
    from ceres.database.migrations import Migration
    from ceres.entity import Entity

    _SQLiteConnection = AsyncAdapt_aiosqlite_connection | sqlite3.Connection
else:
    _SQLiteConnection = object


with __lazy_imports__(__name__):
    from ceres.__internal__.auth import get_password_hash, verify_password, verify_password_hash
    from ceres.alert import AlertManager
    from ceres.group import GroupManager, GroupMembershipManager
    from ceres.logs import LogManager
    from ceres.message import MessageManager
    from ceres.particle import ParticleManager
    from ceres.permission import GroupPermissionManager, UserPermissionManager
    from ceres.setting import SettingManager
    from ceres.statistics import StatisticsManager
    from ceres.user import UserManager
    from ceres.variable import VariableManager
    from ceres.workspace import WorkspaceEditManager, WorkspaceManager

__all__ = [
    "Database",
    "SQLiteDatabase",
    "TursoDatabase",
    "PostgresDatabase",
    "default_database_config",
]


_MIGRATIONS_TABLE_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
)
""".strip()

_MIGRATIONS_TABLE_DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS migrations (
    id INTEGER PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
)
""".strip()
# The migrations table is intentionally not an entity row, it is bookkeeping owned by the
# database layer.


def default_database_config() -> DatabaseConfig:
    """Build the configuration a `Database` uses when it is constructed without one.

    Every unconfigured `Database`, including the one an unconfigured `Engine` creates for itself,
    runs through here. Deployments always pass a config, so in practice this serves throwaway
    databases, and the test suite replaces it to run the same code against another backend.

    Returns:
        A `SQLiteDatabaseConfig` for a temporary on-disk database.
    """
    return SQLiteDatabaseConfig()


class Database:
    """Asynchronous database handle backing all persisted Ceres state.

    `Database` owns the SQLAlchemy async engine, exposes cached entity managers for every
    persisted record type, and handles one-time schema initialization. Instantiating the base
    class dispatches to the appropriate concrete subclass based on the configuration, so
    `Database(SQLiteDatabaseConfig())` returns a `SQLiteDatabase` and
    `Database(PostgresDatabaseConfig(...))` returns a `PostgresDatabase`. Omitting the config
    entirely dispatches on whatever `default_database_config` returns.
    """

    def __new__(cls, config: DatabaseConfig | None = None, /) -> Database:
        if cls is Database:
            match config if config is not None else default_database_config():
                # Turso is matched first because its config subclasses the SQLite one, so the
                # SQLite pattern below would otherwise capture it.
                case TursoDatabaseConfig() as resolved:
                    return TursoDatabase(resolved)
                case SQLiteDatabaseConfig() as resolved:
                    return SQLiteDatabase(resolved)
                case PostgresDatabaseConfig() as resolved:
                    return PostgresDatabase(resolved)

        return cls(config)

    def __init__(self, config: DatabaseConfig | None = None, /) -> None:
        # Every subclass builds itself from `__new__`, and Python then calls `__init__` a second
        # time with the arguments the caller wrote, which are not necessarily the resolved ones.
        # The first call wins, so that second pass neither rebuilds the engine nor overwrites the
        # resolved config with the `None` a caller who wanted the default passed.
        if getattr(self, "_config", None) is not None:
            return

        assert config is not None

        self._id = uuid4()
        self._config = config
        self._concurrent = ContextVar(f"ceres-concurrent-{self._id}", default=False)
        self._engine = self._create_engine()
        self._migrate_lock = AsyncLock()
        self._bootstrapped = False

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
        """Backend kind, one of `DatabaseType.SQLITE`, `DatabaseType.TURSO`, or
        `DatabaseType.POSTGRES`."""
        return self._config.type

    def _record_fetcher(self) -> RecordFetcher | None:
        """Return a natively-connected record fetcher, or `None` when unsupported.

        The fetcher serves record listings without materializing Python entities. Backends
        opt in by overriding, and return `None` whenever a second connection pool cannot
        safely join this database.
        """
        return None

    def _record_writer(self) -> RecordWriter | None:
        """Return a natively-connected record writer, or `None` when unsupported.

        The writer upserts flushed record batches without serializing Python entities
        through Pydantic. The same joinability rules as `_record_fetcher` apply.
        """
        return None

    def _store(self) -> Store | None:
        """Return the native store this database's queries run through, or `None` when a
        second engine cannot safely join this database.

        One store serves the whole database, reads and writes alike, because a second
        pool over the same file is what the backends that withhold a native fetcher are
        avoiding. Built once and reused, and it connects lazily, so holding one costs
        nothing until a query runs.
        """
        store = getattr(self, "_native_store", None)
        if store is None:
            store = self._create_store()
            self._native_store = store

        return store

    @abstractmethod
    def _create_store(self) -> Store:
        """Open a native store on this backend's connection parameters."""
        ...

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
    def workspace_edits(self) -> WorkspaceEditManager:
        """Manager for `WorkspaceEdit` records."""
        return WorkspaceEditManager(self)

    @cached_property
    def groups(self) -> GroupManager:
        """Manager for `Group` records."""
        return GroupManager(self)

    @cached_property
    def group_memberships(self) -> GroupMembershipManager:
        """Manager for `GroupMembership` records."""
        return GroupMembershipManager(self)

    @cached_property
    def user_permissions(self) -> UserPermissionManager:
        """Manager for `UserPermission` records."""
        return UserPermissionManager(self)

    @cached_property
    def group_permissions(self) -> GroupPermissionManager:
        """Manager for `GroupPermission` records."""
        return GroupPermissionManager(self)

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

    async def ready(self) -> None:
        """Bootstrap an empty database through the migration chain.

        Databases that already have tables are left untouched here, `assert_schema_current`
        is what guards against stale schemas on those. Bootstrapping only happens once per
        instance, a cached flag makes every later call zero-I/O. Concurrent first calls may
        each run `initialized()` and `migrate()`, but `migrate()` serializes on the instance's
        migration lock, so migrations are still only applied once.

        Every path that reaches the data has to come through here first, the native store's
        as much as the query layer's, because a database nobody has bootstrapped has no
        tables and, for a temporary one, no file either.
        """
        if not self._bootstrapped:
            if not await self.initialized():
                await self.migrate()

            self._bootstrapped = True

    async def use(self) -> AsyncConnection:
        """Bootstrap an empty database through the migration chain, then open a new connection.

        Returns:
            An `AsyncConnection` ready for use against a bootstrapped database.
        """
        await self.ready()
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
        """Dispose of the underlying engine, closing any pooled connections.

        Waiting on the migration lock is what keeps a database from being disposed out from
        under its own bootstrap. A component stops as soon as it runs out of work, and the
        stop disposes its database, so a query started from outside the component can be
        partway through `ready` when that happens. Closing the connections underneath it
        fails the migration, and the failure names neither the disposal nor the caller.
        """
        async with self._migrate_lock:
            with wrap_database_errors():
                await self._engine.dispose()

    async def _get_applied_migration_ids(self) -> list[int]:
        """Return the IDs of every migration recorded as applied, in ascending order."""
        ddl = (
            _MIGRATIONS_TABLE_DDL_POSTGRES
            if self.type.value == "postgres"
            else _MIGRATIONS_TABLE_DDL_SQLITE
        )
        with wrap_database_errors():
            async with self._engine.begin() as connection:
                await connection.execute(text(ddl))
                result = await connection.execute(text("SELECT id FROM migrations ORDER BY id"))
                return [row[0] for row in result]

    async def get_applied_migrations(self) -> list[Migration]:
        """Return known migrations recorded as applied, in application order."""
        from ceres.database.migrations import MIGRATIONS

        applied = set(await self._get_applied_migration_ids())
        return [migration for migration in MIGRATIONS if migration.id in applied]

    async def get_pending_migrations(self) -> list[Migration]:
        """Return known migrations that have not been applied, in application order."""
        from ceres.database.migrations import MIGRATIONS

        applied = set(await self._get_applied_migration_ids())
        return [migration for migration in MIGRATIONS if migration.id not in applied]

    async def get_unknown_migrations(self) -> list[int]:
        """Return applied migration IDs this version of ceres does not know about."""
        from ceres.database.migrations import MIGRATIONS

        known = {migration.id for migration in MIGRATIONS}
        return [id for id in await self._get_applied_migration_ids() if id not in known]

    async def migrate(self) -> list[int]:
        """Apply every pending migration in order, recording each as it completes.

        Holds an instance-level lock for the duration of the call, so concurrent callers on
        the same `Database` instance apply migrations one at a time instead of racing to
        insert the same migration ID.

        Returns:
            The IDs of the migrations that were applied.

        Raises:
            DatabaseMigrationError: If a migration fails.
        """
        async with self._migrate_lock:
            return await self._apply_pending_migrations()

    @contextmanager
    def concurrent_transactions(self) -> Iterator[None]:
        """Let transactions opened in this scope overlap with other writers.

        Only meaningful on a backend that offers it, and only `TursoDatabase` does. Everywhere
        else this does nothing, because SQLite and PostgreSQL already give their own answer to
        concurrent writers.

        Concurrency is opt-in rather than the default because the backends that support it refuse
        to run schema changes inside such a transaction, and because the transactions are
        optimistic: two that touch the same rows will see the second fail at commit. Callers ask
        for it where writes are frequent, independent, and safe to retry, which in practice means
        the record writer.

        Yields:
            `None`, for the duration of the scope.
        """
        token = self._concurrent.set(True)
        try:
            yield
        finally:
            self._concurrent.reset(token)

    async def _apply_pending_migrations(self) -> list[int]:
        """Apply each pending migration in its own transaction.

        Returns:
            The IDs of the migrations that were applied.

        Raises:
            DatabaseMigrationError: If a migration fails.
        """
        applied: list[int] = []

        for migration in await self.get_pending_migrations():
            warning = DESTRUCTIVE_MIGRATIONS.get(migration.name)
            if warning is not None:
                get_logger("ceres.database").warning(
                    "Migration %s (%s) is destructive. %s",
                    migration.id,
                    migration.name,
                    warning,
                )

            with wrap_database_errors():
                try:
                    async with self._engine.begin() as connection:
                        sql = migration.render(self.type.value)
                        if sql is not None:
                            await self._execute_script(connection, sql)

                        await connection.execute(
                            text("INSERT INTO migrations (id) VALUES (:id)"),
                            {"id": migration.id},
                        )
                except Exception as error:
                    raise DatabaseMigrationError(
                        message=(f"Migration {migration.id} ({migration.name}) failed. {error}")
                    ) from error

            applied.append(migration.id)

        return applied

    @abstractmethod
    async def _execute_script(self, connection: AsyncConnection, sql: str) -> None:
        """Execute a possibly multi-statement SQL script through the backend driver.

        Args:
            connection: Connection whose transaction the script runs within.
            sql: SQL script text, which may contain multiple `;`-terminated statements.
        """
        ...

    async def assert_schema_current(self) -> None:
        """Verify the database schema matches this version of ceres.

        Raises:
            DatabaseVersionError: If migrations are pending or unknown migrations are applied.
        """
        unknown = await self.get_unknown_migrations()
        if unknown:
            raise DatabaseVersionError(
                message=(
                    f"Database contains migrations unknown to this Ceres version: "
                    f"{', '.join(str(id) for id in unknown)}. The database is newer than the "
                    "running version."
                )
            )

        pending = await self.get_pending_migrations()
        if pending:
            count = len(pending)
            raise DatabaseVersionError(
                message=(
                    f"Database has {count} pending migration(s). "
                    f"Run `ceres database migrate` to apply {'it' if count == 1 else 'them'}."
                )
            )

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


class SQLiteDatabase(Database):
    """`Database` backed by a local SQLite file, or a per-process temporary file.

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
        """Return the `SQLiteDatabaseConfig` this database was constructed from."""
        config = super().config
        assert isinstance(config, SQLiteDatabaseConfig)
        return config

    @property
    @override
    def url(self) -> str:
        """Build and return the `sqlite+aiosqlite` connection URL for this database."""
        return URL.create(
            "sqlite+aiosqlite",
            database=str(self.path),
            query=self.config.query or {},
        ).render_as_string(hide_password=False)

    @override
    def _create_store(self) -> Store:
        return Store.sqlite(str(self.path))

    @override
    def _record_fetcher(self) -> RecordFetcher | None:
        fetcher = getattr(self, "_native_record_fetcher", None)
        if fetcher is None:
            fetcher = RecordFetcher.sqlite(str(self.path))
            self._native_record_fetcher = fetcher

        return fetcher

    @override
    def _record_writer(self) -> RecordWriter | None:
        writer = getattr(self, "_native_record_writer", None)
        if writer is None:
            writer = RecordWriter.sqlite(str(self.path))
            self._native_record_writer = writer

        return writer

    @property
    def path(self) -> Path:
        """Filesystem path of the SQLite database file.

        Returns the configured `config.path` when set, otherwise a temporary path derived from
        this instance's `id`.
        """
        path = self.config.path
        if path is None:
            # No path was provided, create a temporary on-disk database.
            return self._get_temporary_path()

        return path.absolute()

    def __del__(self) -> None:
        try:
            self._cleanup_temporary_files()
        except Exception:
            pass

    @override
    async def dispose(self) -> None:
        """Dispose of the engine, then remove any temporary database files."""
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
        # Enable a 30 second busy timeout.
        yield "PRAGMA busy_timeout = 30000"

    @override
    async def _execute_script(self, connection: AsyncConnection, sql: str) -> None:
        # Run the script through aiosqlite's "executescript", which handles multiple
        # ";"-terminated statements in a single call.
        raw = await connection.get_raw_connection()
        assert raw.driver_connection is not None
        await raw.driver_connection.executescript(sql)

    def _get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"

    def _cleanup_temporary_files(self) -> None:
        if self.config.path is None and self._get_temporary_path().exists():
            for path in Path(gettempdir()).glob(f"*{self.id}*"):
                path.unlink(missing_ok=True)


@final
class TursoDatabase(SQLiteDatabase):
    """`Database` backed by a Turso file, which is SQLite's format with concurrent writers.

    Turso reads and writes the same file a `SQLiteDatabase` does and accepts the same schema, so
    almost everything is inherited. Two things differ. Write transactions open with
    `BEGIN CONCURRENT` under `journal_mode = 'mvcc'`, which is the point of the backend, and
    conflicts are reported when a transaction commits rather than when it writes, so a caller that
    loses a race sees an error at commit and has to retry.

    See `TursoDatabaseConfig` for what enabling `mvcc` costs, and note that `pyturso` is an extra
    rather than an installed dependency.
    """

    @override
    def __new__(cls, /, config: TursoDatabaseConfig | None = None) -> Self:
        instance = object.__new__(cls)
        cls.__init__(instance, config)
        return instance

    @override
    def __init__(self, /, config: TursoDatabaseConfig | None = None) -> None:
        _assert_turso_installed()
        super().__init__(config or TursoDatabaseConfig())

    @property
    @override
    def config(self) -> TursoDatabaseConfig:
        """Return the `TursoDatabaseConfig` this database was constructed from."""
        config = super().config
        assert isinstance(config, TursoDatabaseConfig)
        return config

    @override
    def _create_store(self) -> Store:
        return Store.turso(str(self.path), self.config.mvcc)

    @override
    def _store(self) -> Store | None:
        # Withheld for the same reason as the fetcher below, and the query layer is the
        # other engine in that pair, so running it on a store here is exactly the two
        # copies that lose each other's writes.
        return None

    @override
    def _record_fetcher(self) -> RecordFetcher | None:
        # Turso coordinates the engines sharing a database file through in-process state
        # and an fcntl file lock. A second copy of the engine in the same process, which
        # is exactly what a native fetcher would be next to the driver's, bypasses both,
        # because fcntl locks never conflict within one process. The two copies then
        # overwrite each other's WAL frames, verified empirically as lost committed
        # writes. Native record paths for this backend wait until the Rust core owns the
        # only engine in the process.
        return None

    @override
    def _record_writer(self) -> RecordWriter | None:
        # Withheld for the same reasons as the fetcher, and doubly so for writes.
        return None

    @property
    @override
    def url(self) -> str:
        """Build and return the `sqlite+aioturso` connection URL for this database."""
        return URL.create(
            "sqlite+aioturso",
            database=str(self.path),
            query=self.config.query or {},
        ).render_as_string(hide_password=False)

    @override
    def _setup_engine(self, engine: AsyncEngine) -> None:
        # "SQLiteDatabase" registers Python functions on each connection and opens transactions
        # with "BEGIN IMMEDIATE". Turso offers no way to register a function, and "BEGIN IMMEDIATE"
        # takes the write lock and so gives up the concurrency this backend exists for, which is
        # why none of that setup is reused and "Database._setup_engine" is called directly.
        @event.listens_for(engine.sync_engine, "do_connect")
        def do_connect(*args: object) -> None:
            if self.config.path is not None:
                try:
                    self.config.path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    traceback.print_exc()

        @event.listens_for(engine.sync_engine, "connect")
        def connect(adapted: Any, *args: object) -> None:
            # Unlike aiosqlite's, Turso's adapter does not proxy attributes through to the
            # connection underneath it, so reach the driver's own object to configure it.
            connection = getattr(adapted, "driver_connection", adapted)

            # Stop the driver emitting its own "BEGIN", the same as the SQLite backend.
            connection.isolation_level = None

            if self.config.mvcc:
                # A statement that returns rows does not run until something reads from it, and
                # "journal_mode" reports the mode it selected. Without the fetch this is a silent
                # no-op and "BEGIN CONCURRENT" later fails claiming MVCC is disabled.
                # Statements go through the adapted connection, whose cursor drives the driver's
                # coroutines for us. This event is synchronous, so the driver's own cursor would
                # hand back coroutines nobody can await.
                cursor = adapted.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode = 'mvcc'")
                    mode = cursor.fetchone()
                finally:
                    cursor.close()

                if mode is None or str(mode[0]).lower() != "mvcc":
                    raise DatabaseLoadError(
                        message=(
                            "Turso would not enable MVCC, which concurrent writes require. "
                            f"'PRAGMA journal_mode' reported {mode[0] if mode else 'nothing'}. "
                            "Set 'mvcc' to false to run this database with a single "
                            "writer instead."
                        )
                    )

        @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
        def before_cursor_execute(
            connection: Connection,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> tuple[str, Any]:
            # SQLAlchemy hands binary columns over as "memoryview". Python's own driver takes it
            # through the buffer protocol, Turso's takes only exact bytes and rejects everything
            # else, so a message's data would never insert.
            return statement, _to_turso_parameters(parameters, executemany)

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # "BEGIN CONCURRENT" is what lets two connections write at once. It is optimistic, so
            # a transaction that touched the same rows as another fails at commit rather than
            # waiting here. Turso rejects DDL inside one, so schema changes take the plain form and
            # everything else takes the concurrent one.
            #
            # The plain form is "BEGIN" rather than the "BEGIN IMMEDIATE" the SQLite backend uses.
            # Taking the write lock up front costs Turso far more than it costs SQLite, enough to
            # serialize reads behind unrelated writes and turn a second of work into minutes.
            if self.config.mvcc and self._concurrent.get():
                connection.exec_driver_sql("BEGIN CONCURRENT")
            else:
                connection.exec_driver_sql("BEGIN")

        Database._setup_engine(self, engine)

    @override
    def _get_base_init_commands(self) -> Iterable[str]:
        # Deliberately not "SQLiteDatabase"'s, which sets "auto_vacuum". Turso rejects that PRAGMA
        # unless the server was started with an experimental flag.
        yield from Database._get_base_init_commands(self)

    @override
    def _get_base_connect_commands(self) -> Iterable[str]:
        yield from Database._get_base_connect_commands(self)
        yield "PRAGMA foreign_keys = ON"
        yield "PRAGMA busy_timeout = 30000"
        # "case_sensitive_like" is deliberately absent. Turso accepts it and does not honor it, so
        # setting it would suggest "LIKE" matches case where it does not.

    @override
    async def _execute_script(self, connection: AsyncConnection, sql: str) -> None:
        # Turso's "executescript" runs the script in a transaction of its own, so calling it here,
        # inside the one a migration already opened, leaves every statement after the first
        # unapplied and the next migration fails on a table that looks missing. Running the
        # statements one at a time keeps them in the migration's transaction, where a failure part
        # way through rolls the whole migration back.
        #
        # Splitting on ";" is only safe because these scripts are plain DDL. A statement carrying
        # its own ";", such as a trigger body, would need a real parser.
        for statement in sql.split(";"):
            if statement.strip():
                await connection.exec_driver_sql(statement)

    @override
    def _get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.turso"


@final
class PostgresDatabase(Database):
    """`Database` backed by a PostgreSQL server reached over `asyncpg`."""

    def __new__(cls, /, config: PostgresDatabaseConfig | None = None) -> Self:
        instance = object.__new__(cls)
        cls.__init__(instance, config)
        return instance

    def __init__(self, /, config: PostgresDatabaseConfig | None = None) -> None:
        super().__init__(config)

    @property
    @override
    def config(self) -> PostgresDatabaseConfig:
        """Return the `PostgresDatabaseConfig` this database was constructed from."""
        config = super().config
        assert isinstance(config, PostgresDatabaseConfig)
        return config

    def _native_connection_arguments(self) -> dict[str, Any]:
        """Resolve the arguments a native pool connects with.

        Per-connection server settings like `search_path` shape what queries see, and
        connection string parameters are applied by name, so a configuration naming
        `sslmode` connects the way it says it does. A parameter the native pool does not
        recognize is refused there rather than dropped here, because a connection that
        quietly ignored one would not be the connection that was configured.
        """
        config = self.config
        connect_args: dict[str, Any] = config.engine.get("connect_args", {})
        settings: dict[str, str] = connect_args.get("server_settings", {})
        parameters: list[tuple[str, str]] = [
            (key, value)
            for key, held in (config.query or {}).items()
            for value in (held if isinstance(held, list) else [held])
        ]
        return {
            "parameters": parameters,
            "host": config.host,
            "database": config.database,
            "user": config.user,
            "port": config.port,
            "password": config.password.get_secret_value() if config.password is not None else None,
            "settings": list(settings.items()),
        }

    @override
    def _create_store(self) -> Store:
        return Store.postgres(**self._native_connection_arguments())

    @override
    def _record_fetcher(self) -> RecordFetcher | None:
        fetcher = getattr(self, "_native_record_fetcher", None)
        if fetcher is None:
            fetcher = RecordFetcher.postgres(**self._native_connection_arguments())
            self._native_record_fetcher = fetcher

        return fetcher

    @override
    def _record_writer(self) -> RecordWriter | None:
        writer = getattr(self, "_native_record_writer", None)
        if writer is None:
            writer = RecordWriter.postgres(**self._native_connection_arguments())
            self._native_record_writer = writer

        return writer

    @property
    @override
    def url(self) -> str:
        """Build and return the `postgresql+asyncpg` connection URL for this database."""
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
        """Collect every DDL statement needed for PostgreSQL, including extensions and functions."""
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
        config: dict[str, Any] = {
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_pre_ping": True,  # Check to see if a connection has closed before use.
            "pool_recycle": 60 * 5,  # Recreate connections after five minutes.
            "json_serializer": to_json,  # Serialize any Pydantic compatible object to JSON.
            **self.config.engine,
        }

        # Pools that hold nothing between checkouts, such as `NullPool`, reject the sizing
        # arguments outright, so they only travel with a pool that queues connections.
        if not issubclass(config["poolclass"], QueuePool):
            config.pop("pool_size", None)
            config.pop("max_overflow", None)

        return config

    @override
    async def _execute_script(self, connection: AsyncConnection, sql: str) -> None:
        # asyncpg's simple query protocol executes an entire multi-statement string in one
        # call, including the "$$"-quoted function bodies the baseline schema defines.
        raw = await connection.get_raw_connection()
        assert raw.driver_connection is not None
        await raw.driver_connection.execute(sql)


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


def _to_turso_parameters(parameters: Any, executemany: bool) -> Any:
    """Convert bound parameters into the handful of types Turso's driver accepts.

    Only `memoryview` needs converting today, which is how SQLAlchemy presents a binary column.

    Args:
        parameters: The bound parameters, either one set or a sequence of them.
        executemany: Whether `parameters` is a sequence of parameter sets.

    Returns:
        The parameters, with any value the driver would reject replaced by one it accepts.
    """

    def convert(value: Any) -> Any:
        return bytes(value) if isinstance(value, memoryview) else value

    def convert_set(values: Any) -> Any:
        if isinstance(values, dict):
            return {key: convert(value) for key, value in values.items()}

        if isinstance(values, list | tuple):
            return type(values)(convert(value) for value in values)

        return values

    if executemany and isinstance(parameters, list | tuple):
        return type(parameters)(convert_set(values) for values in parameters)

    return convert_set(parameters)


def _assert_turso_installed() -> None:
    """Check that Turso is importable and its SQLAlchemy dialect can be built.

    `pyturso` is an extra, so a deployment that never asks for this backend does not carry it.

    The dialect it registers subclasses SQLAlchemy's aiosqlite dialect, whose constructor reads
    `dbapi.has_stop`. Turso's DBAPI shim does not define it, so `create_async_engine` raises an
    `AttributeError` before it ever reaches the database. Defaulting it here keeps that upstream
    gap from surfacing as an unrelated error, and the attribute can be dropped once a release
    defines it.

    Raises:
        DatabaseLoadError: If `pyturso` is not installed.
    """
    try:
        from turso.sqlalchemy.dialect import AsyncAdapt_turso_dbapi
    except ImportError as error:
        raise DatabaseLoadError(
            message=(
                "The Turso backend needs the 'pyturso' package, which Ceres does not install by "
                "default. Add it with 'pip install \"ceres[turso]\"', or use the 'sqlite' "
                "backend, which reads and writes the same file."
            )
        ) from error

    if not hasattr(AsyncAdapt_turso_dbapi, "has_stop"):
        setattr(AsyncAdapt_turso_dbapi, "has_stop", False)  # noqa: B010


def _get_entity_row_classes() -> list[type[BaseEntityRow]]:
    from ceres.alert import AlertRow
    from ceres.group import GroupMembershipRow, GroupRow
    from ceres.logs import LogEntryRow
    from ceres.message import MessageRow
    from ceres.particle import ParticleRow
    from ceres.permission import GroupPermissionRow, UserPermissionRow
    from ceres.setting import SettingRow
    from ceres.user import UserRow
    from ceres.variable import VariableRow
    from ceres.workspace import WorkspaceEditRow, WorkspaceRow

    return [
        MessageRow,
        ParticleRow,
        AlertRow,
        LogEntryRow,
        UserRow,
        SettingRow,
        VariableRow,
        WorkspaceRow,
        WorkspaceEditRow,
        GroupRow,
        GroupMembershipRow,
        UserPermissionRow,
        GroupPermissionRow,
    ]
