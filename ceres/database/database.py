import csv
import shutil
import sqlite3
import traceback
from abc import abstractmethod
from asyncio import Lock as AsyncLock
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection
from tempfile import NamedTemporaryFile, gettempdir
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    TypeVar,
    final,
)
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import (
    URL,
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
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from typing_extensions import Self, Unpack, override

from ceres.address import Address
from ceres.alert import Alert
from ceres.config import DatabaseConfig, PostgresDatabaseConfig, SQLiteDatabaseConfig
from ceres.data import jsonify
from ceres.database.enums import DatabaseType, ItemType
from ceres.exceptions import DatabaseLoadException
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
    UserFilter,
    UserFilterArgs,
    UserOrder,
)
from ceres.internal.database.entities import (
    AlertEntity,
    Entity,
    LogEntryEntity,
    MessageEntity,
    StoreEntity,
    UserEntity,
)
from ceres.internal.utilities import (
    PathLike,
    as_sequence,
    escape_like_expression,
    get_type_adapter,
    strlist,
)
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.statistics import LevelStatistics, Statistics
from ceres.store import Store
from ceres.threading import spawn
from ceres.timing import utc
from ceres.user import User

_T = TypeVar("_T")


class Database:
    def __new__(cls, /, config: DatabaseConfig | None = None) -> "Database":
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
            commands.extend(cls.get_ddl(self.__engine.sync_engine))

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
    async def dump_csv(self, path: PathLike, item_type: ItemType) -> None:
        ...

    @abstractmethod
    async def load_csv(self, path: PathLike, item_type: ItemType) -> None:
        ...

    @abstractmethod
    async def dump_sqlite(
        self,
        path: PathLike,
        item_types: Sequence[ItemType] | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def load_sqlite(
        self,
        path: PathLike,
        item_types: Sequence[ItemType] | None = None,
    ) -> None:
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

    async def initialized(self) -> bool:
        return await self.__run_sync(lambda connection: bool(inspect(connection).get_table_names()))

    async def get_users(
        self,
        filter: UserFilter | None = None,
        /,
        **kwargs: Unpack[UserFilterArgs],
    ) -> list[User]:
        filter = UserFilter(**kwargs).with_defaults(filter)

        statement = select(*UserEntity.__table__.columns.values())

        if filter.id is not None:
            statement = statement.where(UserEntity.id.in_(as_sequence(filter.id)))
        if filter.username is not None:
            statement = statement.where(UserEntity.username.in_(as_sequence(filter.username)))
        if filter.email is not None:
            # TODO: Normalize the email addresses before searching.
            statement = statement.where(UserEntity.email.in_(filter.email))
        if filter.disabled is not None:
            statement = statement.where(UserEntity.disabled == filter.disabled)

        match filter.order:
            case None | UserOrder.USERNAME:
                statement = statement.order_by(UserEntity.username)
            case UserOrder.EMAIL:
                statement = statement.order_by(UserEntity.email)

        if filter.limit is not None:
            statement = statement.limit(filter.limit)
        if filter.offset is not None and filter.offset > 0:
            statement = statement.offset(filter.offset)

        async with await self.init() as session:
            rows = await session.execute(statement)

        return get_type_adapter(list[User]).validate_python(rows, from_attributes=True)

    async def get_user(
        self,
        filter: UserFilter | None = None,
        /,
        **kwargs: Unpack[UserFilterArgs],
    ) -> User | None:
        users = await self.get_users(filter, **{**kwargs, "limit": 1})
        return users[0] if users else None

    async def create_user(self, data: User | Mapping[str, Any]) -> User:
        if not isinstance(data, User):
            data = get_type_adapter(User).validate_python(data)

        entity = UserEntity(**data.__dict__)

        async with await self.init() as session:
            session.add(entity)
            await session.commit()

        return data

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

    async def create_message(self, data: Message | Mapping[str, Any]) -> Message:
        if not isinstance(data, Message):
            data = get_type_adapter(Message).validate_python(data)

        entity = MessageEntity(**data.__dict__)

        async with await self.init() as session:
            session.add(entity)
            await session.commit()

        return data

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

    async def create_alert(self, data: Alert | Mapping[str, Any]) -> Alert:
        if not isinstance(data, Alert):
            data = get_type_adapter(Alert).validate_python(data)

        entity = AlertEntity(**data.__dict__)

        async with await self.init() as session:
            session.add(entity)
            await session.commit()

        return data

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

    async def create_log_entry(self, data: LogEntry | Mapping[str, Any]) -> LogEntry:
        if not isinstance(data, LogEntry):
            data = get_type_adapter(LogEntry).validate_python(data)

        entity = LogEntryEntity(**data.__dict__)

        async with await self.init() as session:
            session.add(entity)
            await session.commit()

        return data

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
        *,
        relative_to: Address = Address.root(),
        **kwargs: Unpack[StatisticsFilterArgs],
    ) -> list[Statistics]:
        filter = StatisticsFilter(**kwargs).with_defaults(filter)

        statement = select(AlertEntity.address, AlertEntity.level, func.count()).group_by(
            AlertEntity.address,
            AlertEntity.level,
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
        return URL.create(
            "sqlite+aiosqlite",
            database=str(self.path),
        ).render_as_string(hide_password=False)

    @property
    def path(self) -> Path:
        # If a path is provided, create an database at the provided path.
        if self.config.path is not None:
            return self.config.path.absolute()

        # Otherwise create a temporary on-disk database.
        return self.__get_temporary_path()

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
    async def load_csv(self, path: PathLike, item_type: ItemType) -> None:
        path = _prepare_read_path(path)

        await self.init()

        def execute() -> None:
            with sqlite3.connect(self.path) as connection:
                connection.execute("BEGIN")

                columns = _get_columns_joined(item_type)
                placeholders = ", ".join(":" + column for column in _get_columns(item_type))
                statement = f"INSERT INTO {item_type.table} ({columns}) VALUES ({placeholders})"

                for item in _read_csv_items(path, _get_item_cls(item_type)):
                    id = item.__dict__.get("id")
                    if id is not None:
                        item.__dict__["id"] = str(id)

                    connection.execute(statement, item.__dict__)

                connection.execute("COMMIT")

        await spawn(execute)

    @override
    async def dump_csv(self, path: PathLike, item_type: ItemType) -> None:
        path = _prepare_write_path(path)

        await self.init()

        def execute() -> None:
            with sqlite3.connect(self.path) as connection:
                _sqlite_create_functions(connection)

                header = _get_columns(item_type)
                selects = _get_columns_joined(
                    item_type,
                    {
                        ItemType.MESSAGE: {"content": "decode(content, 'latin-1')"},
                    },
                )

                query = f"SELECT {selects} FROM {item_type.table}"

                with path.open("w") as output:
                    writer = csv.writer(output)
                    # Write header.
                    writer.writerow(header)
                    # Write rows directly from the cursor.
                    writer.writerows(connection.execute(query))

        await spawn(execute)

    async def __copy(
        self,
        item_types: Sequence[ItemType] | None,
        source: Path,
        destination_engine: AsyncEngine,
        create: bool,
    ) -> None:
        if item_types is None:
            item_types = list(ItemType)

        async with destination_engine.connect() as destination_connection:
            if create:
                await destination_connection.execute(text("PRAGMA busy_timeout = 30000"))
                await destination_connection.execute(text("PRAGMA synchronous = OFF"))
                await destination_connection.execute(text("PRAGMA foreign_keys = OFF"))
                await destination_connection.execute(text("PRAGMA cache_size = -64000"))

            await destination_connection.execute(
                text("ATTACH DATABASE :path AS source"), {"path": str(source)}
            )

            for type in item_types:
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
        item_types: Sequence[ItemType] | None = None,
    ) -> None:
        if item_types is None:
            item_types = list(ItemType)

        await self.init()

        if set(item_types) == set(ItemType):

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
                item_types,
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
        item_types: Sequence[ItemType] | None = None,
    ) -> None:
        path = _prepare_read_path(path)

        await self.init()

        await self.__copy(
            item_types,
            source=path,
            destination_engine=self.engine,
            create=False,
        )

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
        return str(
            URL.create(
                "postgresql+asyncpg",
                username=self.config.user,
                password=self.config.password.get_secret_value(),
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
            ).render_as_string(hide_password=False)
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
    async def dump_csv(self, path: PathLike, item_type: ItemType) -> None:
        path = _prepare_write_path(path)

        await self.init()

        import asyncpg

        url = self.url.replace("+asyncpg", "")
        connection: asyncpg.Connection = await asyncpg.connect(url)

        try:
            timestamp = "to_char(timestamp, 'YYYY-MM-DD HH24:MI:SS.US') as timestamp"

            async with connection.transaction():
                columns = _get_columns_joined(
                    item_type,
                    {
                        ItemType.STORE: {
                            "enabled": "enabled::TEXT as enabled",
                        },
                        ItemType.MESSAGE: {
                            "timestamp": timestamp,
                            "content": "convert_from(content, 'latin-1') as content",
                        },
                        ItemType.ALERT: {
                            "timestamp": timestamp,
                        },
                        ItemType.LOG_ENTRY: {
                            "timestamp": timestamp,
                        },
                    },
                )
                query = f"""SELECT {columns} FROM {item_type.table}"""

                await connection.copy_from_query(
                    query,
                    output=path,
                    format="csv",
                    header=True,
                )
        finally:
            await connection.close()

    @override
    async def load_csv(self, path: PathLike, item_type: ItemType) -> None:
        path = _prepare_read_path(path)

        await self.init()

        url = self.url.replace("+asyncpg", "")

        import asyncpg
        from asyncpg import Connection

        connection: Connection = await asyncpg.connect(url)  # type: ignore

        try:
            entity = _get_entity_cls(item_type)
            temporary = "__temporary__" + uuid4().hex.replace("-", "")

            async with connection.transaction():
                await connection.execute(
                    entity.get_table_ddl(
                        self.engine.sync_engine,
                        name=temporary,
                        temporary=True,
                    )
                )

                def _get_fields(item: Item):
                    fields = item.__dict__
                    if item_type == ItemType.ALERT:
                        fields["info"] = jsonify(fields["info"])
                    return fields

                records = (
                    tuple(_get_fields(item).values())
                    for item in _read_csv_items(path, _get_item_cls(item_type))
                )

                await connection.copy_records_to_table(
                    temporary,
                    columns=_get_columns(item_type),
                    records=records,
                )

                await connection.execute(f"INSERT INTO {item_type.table} SELECT * FROM {temporary}")
        finally:
            await connection.close()

    @override
    async def dump_sqlite(
        self,
        path: PathLike,
        item_types: Sequence[ItemType] | None = None,
    ) -> None:
        if item_types is None:
            item_types = list(ItemType)

        path = _prepare_write_path(path)

        await self.init()

        destination = Database(SQLiteDatabaseConfig(path=path))
        for item_type in item_types:
            with NamedTemporaryFile() as temporary:
                await self.dump_csv(temporary.name, item_type)
                await destination.load_csv(temporary.name, item_type)

    @override
    async def load_sqlite(
        self,
        path: PathLike,
        item_types: Sequence[ItemType] | None = None,
    ) -> None:
        if item_types is None:
            item_types = list(ItemType)

        path = _prepare_read_path(path)

        await self.init()

        source = SQLiteDatabase(SQLiteDatabaseConfig(path=path))
        for item_type in item_types:
            with NamedTemporaryFile() as temporary:
                await source.dump_csv(temporary.name, item_type)
                await self.load_csv(temporary.name, item_type)


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


if TYPE_CHECKING:
    from ceres.component import Item
else:
    Item = object

_ItemT = TypeVar("_ItemT", bound=Item)


def _read_csv_items(path: Path, item_cls: type[_ItemT]) -> Iterable[_ItemT]:
    rows = _read_csv_rows(path)
    columns = list(item_cls.model_fields.keys())
    header = next(rows)

    if set(header) != set(columns):
        raise ValueError(f"Expected CSV header columns to include {columns}, got: {header}")

    for row in rows:
        while len(row) < len(columns):
            row.append("")

        fields = {column: row[index] for index, column in enumerate(header) if row[index] != ""}

        try:
            item = item_cls.model_validate(fields)
        except ValidationError as error:
            raise DatabaseLoadException(f"Invalid CSV row: {error}") from error

        yield item


def _decode(value: bytes, encoding: str) -> str:
    if isinstance(value, str):  # type: ignore
        return value

    return value.decode(encoding)


def _encode(value: str, encoding: str) -> bytes:
    if isinstance(value, bytes):
        return value

    return value.encode(encoding)


def _sqlite_create_functions(connection: SQLiteConnection) -> None:
    sqlite3.enable_callback_tracebacks(True)
    connection.create_function("decode", 2, _decode)
    connection.create_function("encode", 2, _encode)


_Replace = Mapping[ItemType, Mapping[str, str]]


def _get_columns_joined(item_type: ItemType, replace: _Replace = {}) -> str:
    return ", ".join(_get_columns(item_type, replace))


def _get_columns(item_type: ItemType, replace: _Replace = {}) -> list[str]:
    columns = list(_get_entity_cls(item_type).__table__.columns.keys())
    replaced = replace.get(item_type, {})
    if replaced:
        for i, column in enumerate(columns):
            columns[i] = replaced.get(column, column)

    return columns


def _get_entity_cls(item_type: ItemType) -> type[Entity]:
    match item_type:
        case ItemType.STORE:
            return StoreEntity
        case ItemType.MESSAGE:
            return MessageEntity
        case ItemType.ALERT:
            return AlertEntity
        case ItemType.LOG_ENTRY:
            return LogEntryEntity

    raise ValueError(item_type)


def _get_item_cls(item_type: ItemType) -> type[Item]:
    match item_type:
        case ItemType.STORE:
            return Store
        case ItemType.MESSAGE:
            return Message
        case ItemType.ALERT:
            return Alert
        case ItemType.LOG_ENTRY:
            return LogEntry

    raise ValueError(item_type)


async def _execute_ddl(
    engine: AsyncEngine,
    *,
    tables: bool = True,
    indexes: bool = True,
) -> None:
    async with engine.begin() as connection:
        for cls in Entity.get_entity_classes():
            for statement in cls.get_ddl(
                engine.sync_engine,
                table=tables,
                indexes=indexes,
            ):
                await connection.execute(text(statement))

        await connection.commit()
