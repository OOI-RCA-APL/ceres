from abc import abstractmethod
from asyncio import Lock as AsyncLock
from functools import cached_property
from pathlib import Path
from tempfile import gettempdir
from typing import TYPE_CHECKING, Any, Protocol, Self, final, override

from ceres.__internal__.core import Connection, RecordWriter, Store
from ceres.__internal__.database.errors import wrap_database_errors
from ceres.__internal__.lazy import __lazy_imports__
from ceres.concurrency import spawn
from ceres.config import (
    DatabaseConfig,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
    TursoDatabaseConfig,
)
from ceres.data import PasswordHash, uuid4
from ceres.error import DatabaseMigrationError, DatabaseVersionError
from ceres.logs import get_logger

DESTRUCTIVE_MIGRATIONS: dict[str, str] = {}
"""Migrations that discard data, keyed by name, with the warning logged before they run.

A migration belongs here only while operators still have it ahead of them. Once every deployment
has run it the warning is noise on each load, and a warning nobody can act on teaches people to
ignore the ones that matter.
"""

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.entity import BaseEntityManager
    from ceres.database import DatabaseType
    from ceres.database.migrations import Migration
    from ceres.entity import Entity


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
    "MigrationReporter",
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


class MigrationReporter(Protocol):
    """Told which migration is running, for a caller showing progress as they apply.

    A migration is one script the driver runs whole, so there is nothing to report from
    inside one. What a caller can show is which of them is running and how many are left,
    which is what these two say.
    """

    def starting(self, migration: Migration, index: int, total: int) -> None:
        """A migration is about to run. `index` is 0-based, `total` counts the pending."""
        ...

    def finished(self, migration: Migration) -> None:
        """The migration that was running has landed and been recorded."""
        ...


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

    `Database` owns the native store every query runs through, exposes cached entity managers
    for every persisted record type, and handles one-time schema initialization. Instantiating
    the base class dispatches to the appropriate concrete subclass based on the configuration, so
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
        # The first call wins, so that second pass does not overwrite the resolved config with
        # the `None` a caller who wanted the default passed.
        if getattr(self, "_config", None) is not None:
            return

        assert config is not None

        self._id = uuid4()
        self._config = config
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

    @abstractmethod
    def _native_connection(self) -> Connection:
        """Resolve this backend's native connection parameters.

        Everything native, the store, the reader, and the record writer, opens
        from this one description, so the three cannot connect differently.
        """
        ...

    def _reader(self) -> Store:
        """Return the natively-connected read-only store, built once and reused.

        The reader serves record listings through `fetch_sql` without materializing
        Python entities, on a pool of its own so a long listing never starves the
        writable store.
        """
        reader = getattr(self, "_native_reader", None)
        if reader is None:
            reader = Store(self._native_connection(), writable=False)
            self._native_reader = reader

        return reader

    def _record_writer(self) -> RecordWriter:
        """Return the natively-connected record writer, built once and reused.

        The writer upserts flushed record batches without serializing Python entities
        through Pydantic.
        """
        writer = getattr(self, "_native_record_writer", None)
        if writer is None:
            writer = RecordWriter(self._native_connection())
            self._native_record_writer = writer

        return writer

    def _store(self) -> Store:
        """Return the native store this database's queries run through.

        One store serves the whole database, reads and writes alike, and it is the only
        engine in the process, which is what Turso needs. Built once and reused, and it
        connects lazily, so holding one costs nothing until a query runs.
        """
        store = getattr(self, "_native_store", None)
        if store is None:
            store = Store(self._native_connection())
            self._native_store = store

        return store

    @final
    def _native_hooks(self) -> dict[str, Any]:
        """Return the configuration's connection statements, by stage of a connection's life.

        Only what the configuration declared goes across. Each backend already sets its own
        commands on the connections it opens, so passing those again would run them twice.

        The `init` statements go to the store alone, that being the engine a database opens
        for itself, while a reader's and a writer's pools take the per-connection pair
        through `_native_connection_hooks`.
        """
        return {
            "on_init": [*(self.config.hooks.init or ())],
            **self._native_connection_hooks(),
        }

    @final
    def _native_connection_hooks(self) -> dict[str, Any]:
        """Return the configuration's statements for the two ends of a connection's life."""
        return {
            "on_connect": [*(self.config.hooks.connect or ())],
            "on_close": [*(self.config.hooks.close or ())],
        }

    @property
    def ddl(self) -> list[str]:
        """Every script that creates this backend's schema, in the order they run.

        The migrations are the schema, so what initializes a database is the chain a fresh
        one runs rather than a separate description of the result. The bookkeeping table
        comes first, since it is what records the rest as they are applied, and a migration
        with no script for this backend is a recorded no-op that contributes nothing.
        """
        from ceres.database.migrations import MIGRATIONS

        scripts = (migration.render(self.type.value) for migration in MIGRATIONS)
        return [self._migrations_table_ddl(), *(script for script in scripts if script)]

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

    async def ping(self) -> bool:
        """Check whether the database is reachable.

        This asks the database a question it can answer without a schema, so it says
        whether the database can be reached rather than whether it has been set up.

        Returns:
            `True` if the database answered, `False` otherwise.
        """
        try:
            await self._store().fetch("SELECT 1", [])
            return True
        except Exception:
            return False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.dispose()

    async def dispose(self) -> None:
        """Let go of this database's pools, so the connections they hold can close.

        A `close` statement runs as each operation returns its connection rather than
        here, which is what makes it run at all on a backend that opens one connection per
        operation. What this releases is the pools themselves.

        A disposed database is reusable, the same as a disposed engine was. Reaching it
        again opens fresh connections and, because the bootstrap flag goes with the pools,
        re-migrates. That last part matters for a temporary database, whose file is deleted
        on the way out and would otherwise be reopened empty and treated as migrated.

        Waiting on the migration lock is what keeps a database from being disposed out from
        under its own bootstrap. A component stops as soon as it runs out of work, and the
        stop disposes its database, so a query started from outside the component can be
        partway through `ready` when that happens. Closing the connections underneath it
        fails the migration, and the failure names neither the disposal nor the caller.
        """
        async with self._migrate_lock:
            self._native_store = None
            self._native_reader = None
            self._native_record_writer = None
            self._bootstrapped = False

    def _migrations_table_ddl(self) -> str:
        """The bookkeeping table's own DDL, in this backend's spelling."""
        return (
            _MIGRATIONS_TABLE_DDL_POSTGRES
            if self.type.value == "postgres"
            else _MIGRATIONS_TABLE_DDL_SQLITE
        )

    async def _get_applied_migration_ids(self) -> list[int]:
        """Return the IDs of every migration recorded as applied, in ascending order."""
        with wrap_database_errors():
            store = self._store()
            await store.execute_script(self._migrations_table_ddl())
            rows = await store.fetch("SELECT id FROM migrations ORDER BY id", [])
            return [row["id"] for row in rows]

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

    async def migrate(self, reporter: MigrationReporter | None = None) -> list[int]:
        """Apply every pending migration in order, recording each as it completes.

        Holds an instance-level lock for the duration of the call, so concurrent callers on
        the same `Database` instance apply migrations one at a time instead of racing to
        insert the same migration ID.

        Args:
            reporter: Told which migration is starting and when it finished, for a caller
                showing progress. A migration runs as one script, so there is nothing to
                report from inside one, only which of them is running now.

        Returns:
            The IDs of the migrations that were applied.

        Raises:
            DatabaseMigrationError: If a migration fails.
        """
        async with self._migrate_lock:
            return await self._apply_pending_migrations(reporter)

    async def _apply_pending_migrations(
        self,
        reporter: MigrationReporter | None = None,
    ) -> list[int]:
        """Apply each pending migration in its own transaction.

        Returns:
            The IDs of the migrations that were applied.

        Raises:
            DatabaseMigrationError: If a migration fails.
        """
        applied: list[int] = []
        pending = await self.get_pending_migrations()

        for index, migration in enumerate(pending):
            if reporter is not None:
                reporter.starting(migration, index, len(pending))

            warning = DESTRUCTIVE_MIGRATIONS.get(migration.name)
            if warning is not None:
                get_logger("ceres.database").warning(
                    "Migration %s (%s) is destructive. %s",
                    migration.id,
                    migration.name,
                    warning,
                )

            sql = migration.render(self.type.value)
            store = self._store()

            with wrap_database_errors():
                try:
                    # The script and the record that it ran go over as one, so a migration
                    # cannot land without being recorded and then run twice. The driver
                    # separates the statements, which is what lets a script turn foreign
                    # keys off before rebuilding a table, a pragma that does nothing inside
                    # a transaction someone else opened.
                    recorded = f"INSERT INTO migrations (id) VALUES ({migration.id});"
                    await store.execute_script(
                        recorded if sql is None else f"{sql.rstrip().rstrip(';')};\n{recorded}"
                    )
                except Exception as error:
                    raise DatabaseMigrationError(
                        message=(f"Migration {migration.id} ({migration.name}) failed. {error}")
                    ) from error

            applied.append(migration.id)
            if reporter is not None:
                reporter.finished(migration)

        return applied

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
        """Delete every row from every known entity table, preserving the schema itself.

        The tables come from the native layer, which lists a table before anything that
        references it, so deleting in reverse empties a table only once nothing points at
        it. Adding a table there puts it in the right place by the same rule.
        """
        from ceres.__internal__.core import stored_columns

        deletes = [f"DELETE FROM {table};" for table, _ in reversed(stored_columns())]
        with wrap_database_errors():
            await self._store().execute_script("\n".join(deletes))

    async def initialized(self) -> bool:
        """Check whether this schema has been created in the database.

        The question is whether any table this schema owns is there, not whether the
        database holds a table at all. A configuration's `init` hook runs on connections
        opened before any migration has, and one that creates a table of its own would
        otherwise make an empty database look bootstrapped, leaving a project whose
        migrations never run and whose schema is never created.

        Returns:
            `True` if any table this schema owns is present, `False` otherwise.
        """
        with wrap_database_errors():
            rows = await self._store().fetch(*self._table_names_query())

        present = {str(row["name"]) for row in rows}
        return bool(present & self._owned_table_names())

    @staticmethod
    def _owned_table_names() -> set[str]:
        """Every table name this schema is the author of.

        The entity tables come from the native layer, which is the single authority on
        what the schema holds, and `migrations` is added because it is bookkeeping owned
        here rather than an entity row.
        """
        from ceres.__internal__.core import stored_columns

        return {table for table, _ in stored_columns()} | {"migrations"}

    def _table_names_query(self) -> tuple[str, list[Any]]:
        """A statement listing the tables in scope for this connection, each as `name`.

        The wording follows what each backend counts as a table of the caller's. Neither
        backend's internal tables are the caller's, and on PostgreSQL neither is a table in
        a schema this connection does not resolve names against. Scoping to the search path
        rather than to every schema on the server is what makes the answer this database's
        rather than the server's, which matters wherever one server holds more than one.
        """
        if self.type.value == "postgres":
            return (
                "SELECT tablename AS name FROM pg_catalog.pg_tables "
                "WHERE schemaname = ANY(current_schemas(false))",
                [],
            )

        return (
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
            [],
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

    @override
    def _native_connection(self) -> Connection:
        return Connection.sqlite(str(self.path), **self._native_hooks())

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
        """Drop the connections, then remove any temporary database files."""
        try:
            await super().dispose()
        finally:
            self._cleanup_temporary_files()

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
    almost everything is inherited. What differs is `journal_mode = 'mvcc'`, which is the point of
    the backend, and which reports a conflict when a transaction commits rather than when it
    writes, so a caller that loses a race sees an error at commit and has to retry.

    See `TursoDatabaseConfig` for what enabling `mvcc` costs. The engine is compiled into Ceres,
    so nothing has to be installed alongside it.
    """

    @override
    def __new__(cls, /, config: TursoDatabaseConfig | None = None) -> Self:
        instance = object.__new__(cls)
        cls.__init__(instance, config)
        return instance

    @override
    def __init__(self, /, config: TursoDatabaseConfig | None = None) -> None:
        super().__init__(config or TursoDatabaseConfig())

    @property
    @override
    def config(self) -> TursoDatabaseConfig:
        """Return the `TursoDatabaseConfig` this database was constructed from."""
        config = super().config
        assert isinstance(config, TursoDatabaseConfig)
        return config

    @override
    def _native_connection(self) -> Connection:
        return Connection.turso(str(self.path), self.config.mvcc, **self._native_hooks())

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
    def _native_connection(self) -> Connection:
        return Connection.postgres(**self._native_connection_arguments(), **self._native_hooks())
