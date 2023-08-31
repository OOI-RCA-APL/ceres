import shutil
import subprocess
import traceback
from abc import abstractmethod
from asyncio import Lock as AsyncLock
from datetime import datetime
from os import PathLike
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import NamedTemporaryFile, gettempdir
from typing import Any, Callable, TypeVar, final
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import (
    AsyncAdaptedQueuePool,
    BinaryExpression,
    Connection,
    SQLColumnExpression,
    Text,
    cast,
    delete,
    event,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from typing_extensions import LiteralString, Self, Unpack, override

from ceres.address import Address
from ceres.alert import Alert
from ceres.config import (
    DatabaseConfig,
    DatabaseType,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
)
from ceres.data import DataObject
from ceres.database.enums import DataFormat, TableOption
from ceres.directory import Directory
from ceres.filter import (
    AlertFilter,
    AlertFilterArgs,
    AlertOrder,
    LogEntryFilter,
    LogEntryFilterArgs,
    LogEntryOrder,
    MessageFilter,
    MessageFilterArgs,
    MessageOrder,
    StatisticsFilter,
    StatisticsFilterArgs,
)
from ceres.internal.database.entities import AlertEntity, Entity, LogEntryEntity, MessageEntity
from ceres.internal.utilities import (
    escape_like_expression,
    get_type_adapter,
    sqlexpr,
    sqlstmt,
    strlist,
)
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.threading import spawn
from ceres.timing import utc

_T = TypeVar("_T")
ConfigT = TypeVar("ConfigT", bound=DatabaseConfig, covariant=True)


class LevelStatistics(DataObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(DataObject):
    count: int = 0
    levels: list[LevelStatistics] = Field(default_factory=list)


class Statistics(DataObject):
    address: Address
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)


class Database:
    def __new__(cls, /, config: DatabaseConfig | None = None) -> Self:
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

        for cls in Entity.get_entity_classes():
            commands.extend(cls.get_entity_ddl(self.__engine.sync_engine))

        return commands

    @property
    @abstractmethod
    def url(self) -> str:
        ...

    @abstractmethod
    def _get_engine_config(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def _pre_configure_engine(self, engine: AsyncEngine) -> None:
        ...

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

    def _create_base_engine(self) -> AsyncEngine:
        return create_async_engine(self.url, **self._get_engine_config())

    def _create_engine(self) -> AsyncEngine:
        engine = self._create_base_engine()

        self._pre_configure_engine(engine)

        init = strlist(self.config.hooks.init)
        connect = strlist(self.config.hooks.connect)
        disconnect = strlist(self.config.hooks.close)

        if init:

            @event.listens_for(engine.sync_engine, "first_connect")
            def init_hook(connection: SQLiteConnection, *args: object) -> None:
                for statement in init:
                    connection.execute(statement)

        if connect:

            @event.listens_for(engine.sync_engine, "connect")
            def connect_hook(connection: SQLiteConnection, *args: object) -> None:
                for statement in connect:
                    connection.execute(statement)

        if disconnect:

            @event.listens_for(engine.sync_engine, "close")
            def close_hook(connection: SQLiteConnection, *args: object) -> None:
                for statement in disconnect:
                    connection.execute(statement)

        return engine

    async def dump(self, table: TableOption, path: str | PathLike[str], format: DataFormat) -> None:
        await self.init()
        match format:
            case DataFormat.CSV:
                return await self._dump_csv(table, path)
            case DataFormat.SQLITE:
                return await self._dump_sqlite(table, path)

    async def load(self, table: TableOption, path: str | PathLike[str], format: DataFormat) -> None:
        await self.init()
        match format:
            case DataFormat.CSV:
                return await self._load_csv(table, path)
            case DataFormat.SQLITE:
                return await self._load_sqlite(table, path)

    def session(self) -> AsyncSession:
        return AsyncSession(self.__engine, expire_on_commit=False)

    def connect(self) -> AsyncConnection:
        return self.__engine.connect()

    async def dispose(self) -> None:
        await self.__engine.dispose()

    async def init(self) -> AsyncSession:
        if self.__completed_init_successfully:
            return self.session()

        async with self.__init_lock:
            if self.__completed_init_successfully:
                return self.session()

            async with self.__engine.begin() as connection:
                for statement in self.ddl:
                    await connection.execute(text(statement))

            self.__completed_init_successfully = True

        return self.session()

    async def clear(self) -> None:
        async with self.__engine.begin() as connection:
            for cls in reversed(Entity.get_entity_classes()):
                await connection.execute(delete(cls))

            await connection.commit()

    async def tables(self) -> list[str]:
        return await self.__run_sync(lambda connection: inspect(connection).get_table_names())

    async def get_messages(
        self,
        filter: MessageFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[MessageFilterArgs],
    ) -> list[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)

        statement = select(*MessageEntity.__table__.columns.values())

        if filter.address is not None:
            statement = statement.where(
                filter.address.matches_expression(MessageEntity.address, relative_to),
            )

        if filter.search:
            pattern = "%" + escape_like_expression(filter.search) + "%"
            statement = statement.where(
                self.__format_like(
                    MessageEntity.address,
                    pattern,
                    filter.search_case_sensitive,
                )
                | self.__format_like(
                    self.__format_timestamp(MessageEntity.timestamp),
                    pattern,
                    filter.search_case_sensitive,
                )
                | self.__format_like(MessageEntity.direction, pattern, filter.search_case_sensitive)
                | (
                    self.__format_like(
                        MessageEntity.content,
                        pattern.encode(),
                        filter.search_case_sensitive,
                    )
                    if self.type == DatabaseType.SQLITE
                    else self.__format_like(
                        func.encode(MessageEntity.content, "escape"),
                        pattern.encode("utf-8").decode("unicode-escape"),
                        filter.search_case_sensitive,
                    )
                ),
            )

        if filter.within is not None:
            statement = statement.where(MessageEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(MessageEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(MessageEntity.timestamp < filter.before)
        if filter.direction is not None:
            statement = statement.where(MessageEntity.direction == filter.direction)
        if filter.prefix is not None:
            statement = statement.where(
                MessageEntity.content.like(escape_like_expression(filter.prefix) + b"%"),
            )
        if filter.suffix is not None:
            statement = statement.where(
                MessageEntity.content.like(b"%" + escape_like_expression(filter.suffix)),
            )

        match filter.order:
            case None | MessageOrder.OLD_TO_NEW:
                statement = statement.order_by(MessageEntity.timestamp)
            case MessageOrder.NEW_TO_OLD:
                statement = statement.order_by(MessageEntity.timestamp.desc())

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        async with await self.init() as session:
            rows = await session.execute(statement)

        return get_type_adapter(list[Message]).validate_python(rows, from_attributes=True)

    async def get_message(
        self,
        filter: MessageFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        messages = await self.get_messages(
            filter,
            **{**kwargs, "limit": 1},
            relative_to=relative_to,
        )
        return messages[0] if messages else None

    async def get_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[AlertFilterArgs],
    ) -> list[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)

        statement = select(*AlertEntity.__table__.columns.values())

        if filter.address is not None:
            statement = statement.where(
                filter.address.matches_expression(AlertEntity.address, relative_to)
            )

        if filter.search is not None:
            pattern = "%" + escape_like_expression(filter.search) + "%"
            statement = statement.where(
                self.__format_like(
                    AlertEntity.address,
                    pattern,
                    filter.search_case_sensitive,
                )
                | self.__format_like(
                    self.__format_timestamp(AlertEntity.timestamp),
                    pattern,
                    filter.search_case_sensitive,
                )
                | self.__format_like(AlertEntity.level, pattern, filter.search_case_sensitive)
                | self.__format_like(AlertEntity.code, pattern, filter.search_case_sensitive)
                | self.__format_like(
                    cast(AlertEntity.info, Text)
                    if self.type == DatabaseType.POSTGRES
                    else AlertEntity.info,
                    pattern,
                    filter.search_case_sensitive,
                ),
            )

        if filter.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(AlertEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(AlertEntity.timestamp < filter.before)
        if filter.level is not None:
            if isinstance(filter.level, Level):
                statement = statement.where(AlertEntity.level == filter.level)
            else:
                statement = statement.where(AlertEntity.level.in_(filter.level))
        if filter.code is not None:
            if isinstance(filter.code, str):
                statement = statement.where(AlertEntity.code == filter.code)
            else:
                statement = statement.where(AlertEntity.code.in_(filter.code))
        if filter.code_regex is not None:
            statement = statement.where(AlertEntity.code.regexp_match(filter.code_regex))

        match filter.order:
            case None | AlertOrder.OLD_TO_NEW:
                statement = statement.order_by(AlertEntity.timestamp)
            case AlertOrder.NEW_TO_OLD:
                statement = statement.order_by(AlertEntity.timestamp.desc())

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        async with await self.init() as session:
            rows = await session.execute(statement)

        return get_type_adapter(list[Alert]).validate_python(rows, from_attributes=True)

    async def get_alert(
        self,
        filter: AlertFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        alerts = await self.get_alerts(filter, **{**kwargs, "limit": 1}, relative_to=relative_to)
        return alerts[0] if alerts else None

    async def get_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> list[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)

        statement = select(*LogEntryEntity.__table__.columns.values())

        if filter.address is not None:
            statement = statement.where(
                filter.address.matches_expression(LogEntryEntity.address, relative_to)
            )

        if filter.search is not None:
            pattern = "%" + escape_like_expression(filter.search) + "%"
            statement = statement.where(
                self.__format_like(
                    LogEntryEntity.address,
                    pattern,
                    filter.search_case_sensitive,
                )
                | self.__format_like(
                    self.__format_timestamp(LogEntryEntity.timestamp),
                    pattern,
                    filter.search_case_sensitive,
                )
                | self.__format_like(LogEntryEntity.level, pattern, filter.search_case_sensitive)
                | self.__format_like(
                    LogEntryEntity.content,
                    pattern,
                    filter.search_case_sensitive,
                ),
            )

        if filter.within is not None:
            statement = statement.where(LogEntryEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(LogEntryEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(LogEntryEntity.timestamp < filter.before)
        if filter.level is not None:
            if isinstance(filter.level, Level):
                statement = statement.where(LogEntryEntity.level == filter.level)
            else:
                statement = statement.where(LogEntryEntity.level.in_(filter.level))
        if filter.prefix is not None:
            statement = statement.where(
                LogEntryEntity.content.like(escape_like_expression(filter.prefix) + "%"),
            )
        if filter.suffix is not None:
            statement = statement.where(
                LogEntryEntity.content.like("%" + escape_like_expression(filter.suffix)),
            )

        match filter.order:
            case None | LogEntryOrder.OLD_TO_NEW:
                statement = statement.order_by(LogEntryEntity.timestamp)
            case LogEntryOrder.NEW_TO_OLD:
                statement = statement.order_by(LogEntryEntity.timestamp.desc())

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        async with await self.init() as session:
            rows = await session.execute(statement)

        return get_type_adapter(list[LogEntry]).validate_python(rows, from_attributes=True)

    async def get_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        alerts = await self.get_log_entries(
            filter,
            **{**kwargs, "limit": 1},
            relative_to=relative_to,
        )
        return alerts[0] if alerts else None

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        filter = StatisticsFilter(**kwargs).with_defaults(filter)

        statement = select(AlertEntity.address, AlertEntity.level, func.count("*")).group_by(
            AlertEntity.address, AlertEntity.level
        )

        if filter.within is not None:
            statement = statement.where(AlertEntity.timestamp >= utc() - filter.within)
        if filter.after is not None:
            statement = statement.where(AlertEntity.timestamp >= filter.after)
        if filter.before is not None:
            statement = statement.where(AlertEntity.timestamp < filter.before)

        results: dict[Address, Statistics] = {}

        async with await self.init() as session:
            for address, level, count in await session.execute(statement):
                address: Address
                for ancestor in address.path:
                    if filter.root is not None:
                        if not filter.root.contains(ancestor):
                            continue

                    current = results.setdefault(ancestor, Statistics(address=ancestor))
                    current.alerts.count += count
                    for entry in current.alerts.levels:
                        if entry.level == level:
                            entry.count += count
                            break
                    else:
                        current.alerts.levels.append(LevelStatistics(level=level, count=count))
                        current.alerts.levels.sort(key=lambda entry: entry.level)

        return list(
            result
            for result in results.values()
            if filter.address is None or filter.address.matches(result.address, relative_to)
        )

    async def __run_sync(self, callback: Callable[[Connection], _T]) -> _T:
        async with self.connect() as connection:
            return await connection.run_sync(callback)

    def __format_timestamp(self, timestamp: SQLColumnExpression[datetime]) -> Any:
        match self.type:
            case DatabaseType.SQLITE:
                return timestamp
            case DatabaseType.POSTGRES:
                return func.to_char(timestamp, "YYYY-MM-DD HH24:MI:SS.US")

    def __format_like(
        self,
        expression: SQLColumnExpression[Any],
        pattern: str | bytes,
        case_sensitive: bool = False,
    ) -> BinaryExpression[bool]:
        if case_sensitive:
            return expression.like(pattern)
        return expression.ilike(pattern)


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
        return f"sqlite+aiosqlite:///{self.path}"

    def __del__(self) -> None:
        if self.config.path is not None or not self.__get_temporary_path().exists():
            return

        try:
            for path in Path(gettempdir()).glob(f"*{self.id}*"):
                path.unlink(missing_ok=True)
        except Exception:
            pass

    @override
    def _get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": AsyncAdaptedQueuePool,
            "pool_size": 10,  # Keep a maximum of ten connections alive continuously.
            "max_overflow": -1,  # Allow an infinite number of connections to be created if needed.
            "pool_recycle": 15 * 60,  # Recreate connections after fifteen minutes.
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
        def first_connect(connection: SQLiteConnection, *args: object) -> None:
            # Enable incremental "auto_vacuum" mode when the first connection to the database is
            # made. This can only be done before database tables are created and is disabled by
            # default, so we do it here just in case "incremental_vacuum" is needed later on.
            # https://www.sqlite.org/pragma.html#pragma_auto_vacuum
            # https://www.sqlite.org/pragma.html#pragma_incremental_vacuum
            connection.execute("PRAGMA auto_vacuum = INCREMENTAL")

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
    async def _load_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        def execute() -> None:
            nonlocal path
            path = Path(path).absolute()

            for table_name, path in _get_csv_dump_paths(table, path):
                result = subprocess.run(
                    [
                        "sqlite3",
                        str(self.path),
                        ".mode csv",
                        f".import '{path}' {table_name}",
                    ],
                    capture_output=True,
                )

                if result.returncode != 0:
                    raise RuntimeError(
                        f"Failed to load CSV file '{path}' into table '{table}'. "
                        + f"{result.stderr.decode('latin-1')}"
                    )

        await spawn(execute)

    @override
    async def _dump_csv(self, table: TableOption, path: str | PathLike[str]) -> None:
        def execute() -> None:
            nonlocal path
            path = Path(path).absolute()
            _remove(path)

            if table == TableOption.ALL:
                path.mkdir(parents=True, exist_ok=True)

            for table_name, path in _get_csv_dump_paths(table, Path(path)):
                result = subprocess.run(
                    [
                        "sqlite3",
                        str(self.path),
                        ".mode csv",
                        f".output '{path}'",
                        f"SELECT * FROM {table_name};",
                    ],
                    capture_output=True,
                )

                if result.returncode != 0:
                    raise RuntimeError(
                        f"Failed to dump table '{table}' to CSV file '{path}'. "
                        + f"{result.stderr.decode('latin-1')}"
                    )

        await spawn(execute)

    async def __copy(
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
                result = subprocess.run(
                    [
                        "sqlite3",
                        str(self.path),
                        f".backup '{path}'",
                    ],
                    check=True,
                    capture_output=True,
                )

                if result.returncode != 0:
                    raise RuntimeError(
                        f"Failed to dump database to SQLite file '{path}'. "
                        + f"{result.stderr.decode('latin-1')}"
                    )

            await spawn(execute)
            return

        destination_engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

        try:
            await Entity.create_all(destination_engine)
            await self.__copy(
                table,
                source=self.path,
                destination_engine=destination_engine,
                create=True,
            )
        finally:
            await destination_engine.dispose()

    @override
    async def _load_sqlite(self, table: TableOption, path: str | PathLike[str]) -> None:
        path = Path(path).absolute()

        await self.__copy(
            table,
            source=path,
            destination_engine=self.engine,
            create=False,
        )

    @property
    def path(self) -> Path:
        # If a path is provided, create an database at the provided path.
        if self.config.path is not None:
            return self.config.path.absolute()

        # Otherwise create a temporary on-disk database.
        return self.__get_temporary_path()

    def __get_temporary_path(self) -> Path:
        return Path(gettempdir()) / f"ceres-{self.id}.sqlite"


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
        return (
            "postgresql+psycopg://"
            + f"{self.config.user}:{self.config.password.get_secret_value()}"
            + f"@{self.config.host}:{self.config.port}/{self.config.database}"
        )

    def _get_engine_config(self) -> dict[str, Any]:
        return {
            "poolclass": AsyncAdaptedQueuePool,
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

        url = self.url.replace("+psycopg", "")

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

        url = self.url.replace("+psycopg", "")

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

        source_adapter = SQLiteDatabase(SQLiteDatabaseConfig(path=path))
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

        destination_adapter = Database(SQLiteDatabaseConfig(path=path))

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
