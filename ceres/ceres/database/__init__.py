from asyncio import Lock as AsyncLock
from datetime import datetime
from os import PathLike
from typing import Any, Callable, TypeVar, final
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import (
    BinaryExpression,
    ColumnElement,
    Connection,
    SQLColumnExpression,
    Text,
    cast,
    delete,
    func,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.sql import expression
from typing_extensions import Self, Unpack

from ceres.address import Address, AddressSelector
from ceres.alert import Alert
from ceres.config import (
    DatabaseConfig,
    DatabaseKind,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
)
from ceres.data import DataObject
from ceres.database.adapters import (
    DatabaseAdapter,
    DataFormat,
    PostgresDatabaseAdapter,
    SQLiteDatabaseAdapter,
    TableOption,
)
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
from ceres.internal.utilities import escape_like_expression
from ceres.level import Level
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.timing import utc

_T = TypeVar("_T")


class LevelStatistics(DataObject):
    level: Level
    count: int = Field(ge=0)


class AlertStatistics(DataObject):
    count: int = 0
    levels: list[LevelStatistics] = Field(default_factory=list)


class Statistics(DataObject):
    address: Address
    alerts: AlertStatistics = Field(default_factory=AlertStatistics)


@final
class Database:
    @classmethod
    def __create_adapter(cls, id: UUID, config: DatabaseConfig) -> DatabaseAdapter[DatabaseConfig]:
        match config:
            case SQLiteDatabaseConfig():
                return SQLiteDatabaseAdapter(id, config)
            case PostgresDatabaseConfig():
                return PostgresDatabaseAdapter(id, config)

    def __init__(self, /, source: DatabaseConfig | Self | None = None) -> None:
        if source is None or isinstance(source, DatabaseConfig):
            self.__id = uuid4()
            self.__config = source or SQLiteDatabaseConfig()
            self.__adapter = self.__create_adapter(self.__id, self.__config)
            self.__engine = self.__adapter.create_engine()
        else:
            self.__id = source.id
            self.__config = source.config
            self.__adapter = source.__adapter
            self.__engine = AsyncEngine(source.__engine.sync_engine)

        self.__init_lock = AsyncLock()
        self.__completed_init_successfully = False

        self.__create_session = async_sessionmaker(
            self.__engine,
            class_=AsyncSession,
            # Don't unload database entity data on commit. We don't want to issue new SQL queries to
            # the database if we access a column that has already been committed. This is
            # particularly true because we're using async sessions. Accessing a non-loaded column on
            # an async session entity results in an error because the the underlying data fetch is
            # asyncronous but never gets awaited. Let's just keep the data around to make sure that
            # doesn't happen.
            expire_on_commit=False,
        )

    @property
    def id(self) -> UUID:
        return self.__id

    @property
    def config(self) -> DatabaseConfig:
        return self.__config

    @property
    def kind(self) -> DatabaseKind:
        return self.__config.kind

    @property
    def adapter(self) -> DatabaseAdapter[DatabaseConfig]:
        return self.__adapter

    @property
    def engine(self) -> AsyncEngine:
        return self.__engine

    @property
    def ddl(self) -> list[str]:
        commands: list[str] = []

        for cls in Entity.get_entity_classes():
            commands.extend(cls.get_entity_ddl(self.__engine.sync_engine))

        return commands

    def session(self) -> AsyncSession:
        return self.__create_session()

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

    async def dump(self, table: TableOption, path: str | PathLike[str], format: DataFormat) -> None:
        return await self.__adapter.dump(table, path, format)

    async def load(self, table: TableOption, path: str | PathLike[str], format: DataFormat) -> None:
        return await self.__adapter.load(table, path, format)

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
        **kwargs: Unpack[MessageFilterArgs],
    ) -> list[Message]:
        filter = MessageFilter(**kwargs).with_defaults(filter)

        statement = select(MessageEntity.__table__.columns)

        if filter.address is not None:
            statement = statement.where(
                self.__address_selector_matches(MessageEntity.address, filter.address)
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
                    if self.kind == DatabaseKind.SQLITE
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

        return [Message.construct(**row._mapping) for row in rows]  # type: ignore

    async def get_message(
        self,
        filter: MessageFilter | None = None,
        /,
        **kwargs: Unpack[MessageFilterArgs],
    ) -> Message | None:
        messages = await self.get_messages(filter, **{**kwargs, "limit": 1})
        return messages[0] if messages else None

    async def get_alerts(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> list[Alert]:
        filter = AlertFilter(**kwargs).with_defaults(filter)

        statement = select(AlertEntity.__table__.columns)

        if filter.address is not None:
            statement = statement.where(
                self.__address_selector_matches(AlertEntity.address, filter.address)
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
                    if self.kind == DatabaseKind.POSTGRES
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

        return [Alert.construct(**row._mapping) for row in rows]  # type: ignore

    async def get_alert(
        self,
        filter: AlertFilter | None = None,
        /,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Alert | None:
        alerts = await self.get_alerts(filter, **{**kwargs, "limit": 1})
        return alerts[0] if alerts else None

    async def get_log_entries(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> list[LogEntry]:
        filter = LogEntryFilter(**kwargs).with_defaults(filter)

        statement = select(LogEntryEntity.__table__.columns)

        if filter.address is not None:
            statement = statement.where(
                self.__address_selector_matches(LogEntryEntity.address, filter.address)
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

        return [LogEntry.construct(**row._mapping) for row in rows]  # type: ignore

    async def get_log_entry(
        self,
        filter: LogEntryFilter | None = None,
        /,
        **kwargs: Unpack[LogEntryFilterArgs],
    ) -> LogEntry | None:
        alerts = await self.get_log_entries(filter, **{**kwargs, "limit": 1})
        return alerts[0] if alerts else None

    async def get_statistics(
        self,
        filter: StatisticsFilter | None = None,
        /,
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
            if filter.address is None or filter.address.matches(result.address)
        )

    async def __run_sync(self, callback: Callable[[Connection], _T]) -> _T:
        async with self.connect() as connection:
            return await connection.run_sync(callback)

    def __format_timestamp(self, timestamp: SQLColumnExpression[datetime]) -> Any:
        match self.kind:
            case DatabaseKind.SQLITE:
                return timestamp
            case DatabaseKind.POSTGRES:
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

    def __address_selector_matches(
        self,
        address: SQLColumnExpression[Address],
        selector: AddressSelector,
    ) -> ColumnElement[bool]:
        conditions: list[ColumnElement[bool]] = []

        for segment in selector.segments:
            if (
                not segment.endswith(":all")
                and not segment.endswith(":descendants")
                and not segment.endswith(":children")
            ):
                conditions.append(address == segment)

                continue

            if segment.startswith("~"):
                if segment.endswith(":all"):
                    conditions.append(expression.true())
                elif segment.endswith(":descendants"):
                    conditions.append(address != "~")
                elif segment.endswith(":children"):
                    conditions.append(address == "@")

                continue

            if segment == "@":
                if segment.endswith(":all"):
                    conditions.append(address != "~")
                elif segment.endswith(":descendants"):
                    conditions.append(address != "~")
                    conditions.append(address != "@")
                elif segment.endswith(":children"):
                    conditions.append(address.like("@_%"))

                continue

            if not segment.startswith("@"):
                segment = AddressSelector("@" + segment)

            base = (
                segment.removesuffix(":all").removesuffix(":descendants").removesuffix(":children")
            )

            if segment.endswith(":all"):
                conditions.append((address == base) | address.startswith(f"{base}."))
            elif segment.endswith(":descendants"):
                conditions.append(address.startswith(f"{base}."))
            elif segment.endswith(":children"):
                conditions.append(address.startswith(f"{base}.") & address.not_like(f"{base}.%."))

        return or_(*conditions)
