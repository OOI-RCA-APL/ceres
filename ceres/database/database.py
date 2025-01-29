from __future__ import annotations

import csv
import shutil
import traceback
from abc import abstractmethod
from asyncio import Lock as AsyncLock
from functools import cached_property
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from textwrap import dedent
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Self,
    Sequence,
    final,
    override,
)
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import URL, AsyncAdaptedQueuePool, Connection, delete, event, inspect, text
from sqlalchemy.engine.interfaces import DBAPIConnection

from ceres._internal import util
from ceres._internal.auth import get_password_hash, verify_password, verify_password_hash
from ceres._internal.entity import BaseEntity, BaseEntityRow
from ceres._internal.lazy import lazy_imports
from ceres._internal.util import PathLike
from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.data import PasswordHash, jsonify, uuid4
from ceres.database import DatabaseType
from ceres.entity import EntityType
from ceres.error import DatabaseInitError, DatabaseLoadError, Failure
from ceres.threading import spawn

with lazy_imports(__name__):
    import sqlite3

    import asyncpg
    from sqlalchemy.ext.asyncio import (
        AsyncConnection,
        AsyncEngine,
        AsyncSession,
        create_async_engine,
    )

    from ceres.alert import AlertManager
    from ceres.logs import LogManager
    from ceres.message import MessageManager
    from ceres.particle import ParticleManager
    from ceres.setting import SettingManager
    from ceres.statistics import StatisticsManager
    from ceres.user import UserManager
    from ceres.variable import VariableManager

if TYPE_CHECKING:
    from sqlalchemy.dialects.sqlite.aiosqlite import AsyncAdapt_aiosqlite_connection

    _SQLiteConnection = AsyncAdapt_aiosqlite_connection | sqlite3.Connection
else:
    _SQLiteConnection = object


class Database:
    def __new__(cls, /, config: DatabaseConfig | None = None) -> Database:
        if cls is Database:
            match config:
                case None | SQLiteDatabaseConfig():
                    return SQLiteDatabase(config)
                case PostgresDatabaseConfig():
                    return PostgresDatabase(config)

        return cls(config)  # type: ignore

    def __init__(self, /, config: DatabaseConfig | None = None) -> None:
        assert config is not None

        self.__id = uuid4()
        self.__config = config
        self.__engine = self._create_engine()
        self.__init_lock = AsyncLock()
        self.__completed_init_successfully = False

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def config(self) -> DatabaseConfig:
        return self.__config

    @property
    def type(self) -> DatabaseType:
        return self.__config.type

    @property
    def engine(self) -> AsyncEngine:
        return self.__engine

    @property
    def ddl(self) -> list[str]:
        commands: list[str] = []

        for cls in _get_entity_row_classes():
            commands.extend(cls.get_ddl(self.__engine.sync_engine))

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

    @property
    def log(self) -> LogManager:
        return self.logs

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
    def statistics(self) -> StatisticsManager:
        return StatisticsManager(self)

    @property
    @abstractmethod
    def url(self) -> str: ...

    @abstractmethod
    def _get_engine_config(self) -> dict[str, Any]: ...

    @abstractmethod
    def _pre_configure_engine(self, engine: AsyncEngine) -> None: ...

    @abstractmethod
    async def dump_csv(self, path: PathLike, entity_type: EntityType) -> None: ...

    @abstractmethod
    async def load_csv(self, path: PathLike, entity_type: EntityType) -> None: ...

    @abstractmethod
    async def dump_sqlite(
        self,
        path: PathLike,
        entity_types: Sequence[EntityType] | None = None,
    ) -> None: ...

    @abstractmethod
    async def load_sqlite(
        self,
        path: PathLike,
        entity_types: Sequence[EntityType] | None = None,
    ) -> None: ...

    def _create_base_engine(self) -> AsyncEngine:
        return create_async_engine(self.url, **self._get_engine_config())

    def _create_engine(self) -> AsyncEngine:
        engine = self._create_base_engine()

        self._pre_configure_engine(engine)

        init = util.as_sequence(self.config.hooks.init or ())
        connect = util.as_sequence(self.config.hooks.connect or ())
        disconnect = util.as_sequence(self.config.hooks.close or ())

        if init:

            @event.listens_for(engine.sync_engine, "first_connect")
            def init_hook(connection: DBAPIConnection, *args: object) -> None:
                cursor = connection.cursor()
                for statement in init:
                    cursor.execute(statement)

        if connect:

            @event.listens_for(engine.sync_engine, "connect")
            def connect_hook(connection: DBAPIConnection, *args: object) -> None:
                cursor = connection.cursor()
                for statement in connect:
                    cursor.execute(statement)

        if disconnect:

            @event.listens_for(engine.sync_engine, "close")
            def close_hook(connection: DBAPIConnection, *args: object) -> None:
                cursor = connection.cursor()
                for statement in disconnect:
                    cursor.execute(statement)

        return engine

    def session(self) -> AsyncSession:
        return AsyncSession(self.__engine, expire_on_commit=False)

    def connect(self) -> AsyncConnection:
        return self.__engine.connect()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.dispose()

    async def dispose(self) -> None:
        with util.wrap_database_errors():
            await self.__engine.dispose()

    async def init(self) -> AsyncSession:
        with util.wrap_database_errors():
            if self.__completed_init_successfully:
                return self.session()

            async with self.__init_lock:
                if self.__completed_init_successfully:
                    return self.session()

                try:
                    async with self.__engine.begin() as connection:
                        for statement in self.ddl:
                            await connection.execute(text(statement))
                except Exception as error:
                    raise Failure(DatabaseInitError(message=str(error))) from error

                self.__completed_init_successfully = True

            return self.session()

    async def clear(self) -> None:
        with util.wrap_database_errors():
            async with self.__engine.begin() as connection:
                for cls in reversed(_get_entity_row_classes()):
                    await connection.execute(delete(cls))

                await connection.commit()

    async def initialized(self) -> bool:
        return await self.__run_sync(lambda connection: bool(inspect(connection).get_table_names()))

    #
    # Users
    #

    async def hash_password(self, password: str) -> PasswordHash:
        def execute() -> PasswordHash:
            return get_password_hash(password, self.config.hashing)

        return await spawn(execute)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        hash = await self.__maybe_hash_password(hash)

        def execute() -> bool:
            return verify_password(password, hash)

        return await spawn(execute)

    async def __maybe_hash_password(self, password: str) -> PasswordHash:
        if verify_password_hash(password):
            return password

        return await self.hash_password(password)

    async def __run_sync[T](self, callback: Callable[[Connection], T]) -> T:
        with util.wrap_database_errors():
            async with self.connect() as connection:
                return await connection.run_sync(callback)


@final
class SQLiteDatabase(Database):  #
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
        return self.__get_temporary_path()

    def __del__(self) -> None:
        try:
            self.__cleanup_temporary_files()
        except Exception:
            pass

    @override
    async def dispose(self) -> None:
        try:
            await super().dispose()
        finally:
            self.__cleanup_temporary_files()

    @override
    def _get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_recycle": 15 * 60,  # Recreate connections after fifteen minutes.
            "json_serializer": jsonify,  # Serialize any Pydantic compatible object to JSON.
            **self.config.engine,
        }

    @override
    def _pre_configure_engine(self, engine: AsyncEngine) -> None:
        # https://docs.sqlalchemy.org/en/latest/core/events.html#sqlalchemy.events.DialectEvents.do_connect
        @event.listens_for(engine.sync_engine, "do_connect")
        def do_connect(*args: object) -> None:
            # Create the directory containing the database file if it doesn't already exist.
            if self.config.path is not None:
                try:
                    self.config.path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    traceback.print_exc()

        @event.listens_for(engine.sync_engine, "first_connect")
        def first_connect(connection: _SQLiteConnection, *args: object) -> None:
            # Enable incremental "auto_vacuum" mode when the first connection to the database is
            # made. This can only be done before database tables are created and is disabled by
            # default, so we do it here just in case "incremental_vacuum" is needed later on.
            # https://www.sqlite.org/pragma.html#pragma_auto_vacuum
            # https://www.sqlite.org/pragma.html#pragma_incremental_vacuum
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.PoolEvents.connect
        @event.listens_for(engine.sync_engine, "connect")
        def connect(connection: _SQLiteConnection, *args: object) -> None:
            # Enable a 30 second busy timeout.
            connection.execute("PRAGMA busy_timeout = 30000")
            # Set like statements to be case sensitive to match Postgres.
            connection.execute("PRAGMA case_sensitive_like = ON")
            # Clear the isolation level to stop "pysqlite" from:
            #   1. Automatically emitting "BEGIN"
            #   2. Automatically emitting "COMMIT" before any DDL
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.isolation_level = None
            # Enable foreign key handling by default.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#foreign-key-support
            connection.execute("PRAGMA foreign_keys = ON")

            _sqlite_create_functions(connection)

        # https://docs.sqlalchemy.org/en/20/core/events.html#sqlalchemy.events.ConnectionEvents.begin
        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection: Connection) -> None:
            # Emit our own "BEGIN" statement.
            # https://docs.sqlalchemy.org/en/latest/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    @override
    async def load_csv(self, path: PathLike, entity_type: EntityType) -> None:
        path = _prepare_read_path(path)

        await self.init()

        def execute() -> None:
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN")

                columns = _get_columns_joined(entity_type)
                placeholders = ", ".join(":" + column for column in _get_columns(entity_type))
                statement = f"INSERT INTO {entity_type.table} ({columns}) VALUES ({placeholders})"

                for entity in _read_csv_entities(path, entity_type.cls):
                    id = entity.__dict__.get("id")
                    if id is not None:
                        entity.__dict__["id"] = str(id)

                    connection.execute(statement, entity.__dict__)

                connection.execute("COMMIT")

        await spawn(execute)

    @override
    async def dump_csv(self, path: PathLike, entity_type: EntityType) -> None:
        path = _prepare_write_path(path)

        await self.init()

        def execute() -> None:
            with sqlite3.connect(self.path) as connection:
                _sqlite_create_functions(connection)

                header = _get_columns(entity_type)
                selects = _get_columns_joined(
                    entity_type,
                    {
                        EntityType.MESSAGE: {"content": "decode(content, 'latin-1')"},
                    },
                )

                query = f"SELECT {selects} FROM {entity_type.table}"

                with path.open("w") as output:
                    writer = csv.writer(output)
                    # Write header.
                    writer.writerow(header)
                    # Write rows directly from the cursor.
                    writer.writerows(connection.execute(query))

        await spawn(execute)

    async def __copy(
        self,
        entity_types: Sequence[EntityType] | None,
        source: Path,
        destination_engine: AsyncEngine,
        create: bool,
    ) -> None:
        if entity_types is None:
            entity_types = list(EntityType)

        async with destination_engine.connect() as destination_connection:
            if create:
                await destination_connection.execute(text("PRAGMA busy_timeout = 30000"))
                await destination_connection.execute(text("PRAGMA synchronous = OFF"))
                await destination_connection.execute(text("PRAGMA foreign_keys = OFF"))
                await destination_connection.execute(text("PRAGMA cache_size = -64000"))

            await destination_connection.execute(
                text("ATTACH DATABASE :path AS source"), {"path": str(source)}
            )

            for type in entity_types:
                await destination_connection.execute(
                    text(f"INSERT INTO main.{type.table} SELECT * FROM source.{type.table}")
                )

            await destination_connection.commit()

            if create:
                await destination_connection.execute(text("PRAGMA synchronous = FULL"))
                await destination_connection.commit()

    @override
    async def dump_sqlite(
        self,
        path: PathLike,
        entity_types: Sequence[EntityType] | None = None,
    ) -> None:
        if entity_types is None:
            entity_types = list(EntityType)

        await self.init()

        if set(entity_types) == set(EntityType):

            def execute() -> None:
                with sqlite3.connect(self.path) as source:
                    _sqlite_create_functions(source)
                    with sqlite3.connect(path) as destination:
                        source.backup(destination)

            await spawn(execute)
            return

        path = _prepare_write_path(path)

        destination_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            await _execute_ddl(destination_engine, tables=True, indexes=False)
            await self.__copy(
                entity_types,
                source=self.path,
                destination_engine=destination_engine,
                create=True,
            )
            await _execute_ddl(destination_engine, tables=False, indexes=True)
        finally:
            await destination_engine.dispose()

    @override
    async def load_sqlite(
        self,
        path: PathLike,
        entity_types: Sequence[EntityType] | None = None,
    ) -> None:
        path = _prepare_read_path(path)

        await self.init()

        await self.__copy(
            entity_types,
            source=path,
            destination_engine=self.engine,
            create=False,
        )

    def __get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"

    def __cleanup_temporary_files(self) -> None:
        if self.config.path is None and self.__get_temporary_path().exists():
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
                """
                CREATE OR REPLACE FUNCTION ceres_decode_latin1(bytes bytea) RETURNS TEXT
                IMMUTABLE
                LANGUAGE plpgsql AS $$
                    BEGIN
                        RETURN convert_from($1, 'latin-1');
                    END;
                $$;
                """
            ).strip()
        )

        commands.append(
            dedent(
                """
                CREATE OR REPLACE FUNCTION ceres_encode_latin1(text text) RETURNS TEXT
                IMMUTABLE
                LANGUAGE plpgsql AS $$
                    BEGIN
                        RETURN convert_to($1, 'latin-1');
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
            "json_serializer": jsonify,  # Serialize any Pydantic compatible object to JSON.
            **self.config.engine,
        }

    @override
    async def dump_csv(self, path: PathLike, entity_type: EntityType) -> None:
        path = _prepare_write_path(path)

        await self.init()

        url = self.url.replace("+asyncpg", "")

        connection: asyncpg.Connection = await asyncpg.connect(url)

        try:
            timestamp = "to_char(timestamp, 'YYYY-MM-DD HH24:MI:SS.US') as timestamp"

            async with connection.transaction():
                columns = _get_columns_joined(
                    entity_type,
                    {
                        EntityType.MESSAGE: {
                            "timestamp": timestamp,
                            "content": "convert_from(content, 'latin-1') as content",
                        },
                        EntityType.ALERT: {
                            "timestamp": timestamp,
                        },
                        EntityType.LOG_ENTRY: {
                            "timestamp": timestamp,
                        },
                    },
                )
                query = f"""SELECT {columns} FROM {entity_type.table}"""

                await connection.copy_from_query(
                    query,
                    output=path,
                    format="csv",
                    header=True,
                )
        finally:
            await connection.close()

    @override
    async def load_csv(self, path: PathLike, entity_type: EntityType) -> None:
        path = _prepare_read_path(path)

        await self.init()

        url = self.url.replace("+asyncpg", "")

        connection: asyncpg.Connection = await asyncpg.connect(url)

        try:
            row_cls = entity_type.cls.Row
            temporary = "__temporary__" + uuid4().hex.replace("-", "")

            async with connection.transaction():
                await connection.execute(
                    row_cls.get_table_ddl(
                        self.engine.sync_engine,
                        name=temporary,
                        temporary=True,
                    )
                )

                def _get_fields(entity: BaseEntity):
                    fields = entity.__dict__
                    if "address" in fields:
                        fields["address"] = str(fields["address"])
                    if entity_type == EntityType.ALERT:
                        fields["info"] = jsonify(fields["info"])
                    elif entity_type == EntityType.VARIABLE:
                        fields["value"] = jsonify(fields["value"])

                    return fields

                records = (
                    tuple(_get_fields(entity).values())
                    for entity in _read_csv_entities(path, entity_type.cls)
                )

                await connection.copy_records_to_table(
                    temporary,
                    columns=_get_columns(entity_type),
                    records=records,
                )

                await connection.execute(
                    f"INSERT INTO {entity_type.table} SELECT * FROM {temporary}"
                )
        finally:
            await connection.close()

    @override
    async def dump_sqlite(
        self,
        path: PathLike,
        entity_types: Sequence[EntityType] | None = None,
    ) -> None:
        if entity_types is None:
            entity_types = list(EntityType)

        path = _prepare_write_path(path)

        await self.init()

        destination = Database(SQLiteDatabaseConfig(path=path))
        for entity_type in entity_types:
            with NamedTemporaryFile() as temporary:
                await self.dump_csv(temporary.name, entity_type)
                await destination.load_csv(temporary.name, entity_type)

    @override
    async def load_sqlite(
        self,
        path: PathLike,
        entity_types: Sequence[EntityType] | None = None,
    ) -> None:
        if entity_types is None:
            entity_types = list(EntityType)

        path = _prepare_read_path(path)

        await self.init()

        source = SQLiteDatabase(SQLiteDatabaseConfig(path=path))
        for entity_type in entity_types:
            with NamedTemporaryFile() as temporary:
                await source.dump_csv(temporary.name, entity_type)
                await self.load_csv(temporary.name, entity_type)


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, True)
    else:
        path.unlink(missing_ok=True)


def _prepare_write_path(path: PathLike) -> Path:
    path = Path(path).absolute()
    _remove(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_read_path(path: PathLike) -> Path:
    path = Path(path).absolute()
    return path


def _read_csv_rows(path: Path) -> Iterator[Any]:
    with open(path, encoding="utf-8", errors="ignore") as stream:
        for row in csv.reader(stream, delimiter=",", lineterminator="\n", quotechar='"'):
            yield row


def _read_csv_entities[T: BaseEntity](
    path: Path,
    entity_cls: type[T],
) -> Iterable[T]:
    rows = _read_csv_rows(path)
    columns = list(entity_cls.model_fields.keys())
    header = next(rows)

    if set(header) != set(columns):
        raise ValueError(f"Expected CSV header columns to include {columns}, got: {header}")

    for row in rows:
        while len(row) < len(columns):
            row.append("")

        fields = {column: row[index] for index, column in enumerate(header) if row[index] != ""}

        try:
            entity = entity_cls.model_validate(fields)
        except ValidationError as error:
            raise Failure(DatabaseLoadError(message=f"invalid CSV row: {error}")) from error

        yield entity


def _decode(value: bytes, encoding: str) -> str:
    if isinstance(value, str):
        return value

    return value.decode(encoding)


def _encode(value: str, encoding: str) -> bytes:
    if isinstance(value, bytes):
        return value

    return value.encode(encoding)


def _sqlite_create_functions(connection: _SQLiteConnection) -> None:
    sqlite3.enable_callback_tracebacks(True)
    connection.create_function("decode", 2, _decode)
    connection.create_function("encode", 2, _encode)


_Replace = Mapping[EntityType, Mapping[str, str]]


def _get_columns_joined(entity_type: EntityType, replace: _Replace = {}) -> str:
    return ", ".join(_get_columns(entity_type, replace))


def _get_columns(entity_type: EntityType, replace: _Replace = {}) -> list[str]:
    columns = list(entity_type.cls.Row.__table__.columns.keys())
    replaced = replace.get(entity_type, {})
    if replaced:
        for i, column in enumerate(columns):
            columns[i] = replaced.get(column, column)

    return columns


async def _execute_ddl(
    engine: AsyncEngine,
    *,
    tables: bool = True,
    indexes: bool = True,
) -> None:
    async with engine.begin() as connection:
        for cls in _get_entity_row_classes():
            for statement in cls.get_ddl(
                engine.sync_engine,
                table=tables,
                indexes=indexes,
            ):
                await connection.execute(text(statement))

        await connection.commit()


def _get_entity_row_classes() -> list[type[BaseEntityRow]]:
    from ceres.alert import AlertRow
    from ceres.logs import LogEntryRow
    from ceres.message import MessageRow
    from ceres.particle import ParticleRow
    from ceres.setting import SettingRow
    from ceres.user import UserRow
    from ceres.variable import VariableRow

    return [
        MessageRow,
        ParticleRow,
        AlertRow,
        LogEntryRow,
        UserRow,
        SettingRow,
        VariableRow,
    ]
