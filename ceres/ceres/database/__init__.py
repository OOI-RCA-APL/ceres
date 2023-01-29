import re
from textwrap import dedent
from typing import Any, Callable, Iterable, TypeVar, cast, final
from uuid import UUID, uuid4

from sqlalchemy import ClauseElement, Connection, Table, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.elements import TextClause
from typing_extensions import Self

from ..config import (
    DatabaseConfig,
    DatabaseKind,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
)
from .adapter import DatabaseAdapter
from .entity import Entity

_T = TypeVar("_T")


@final
class Database:
    @classmethod
    def __create_adapter(cls, id: UUID, config: DatabaseConfig) -> DatabaseAdapter[DatabaseConfig]:
        match config:
            case SQLiteDatabaseConfig():
                from .adapters.sqlite import SQLiteDatabaseAdapter

                return SQLiteDatabaseAdapter(id, config)
            case PostgresDatabaseConfig():
                from .adapters.postgres import PostgresDatabaseAdapter

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
        def compile(element: ClauseElement) -> str:
            return re.sub(
                r"[\n\r]+\t",
                "\n    ",
                dedent(str(element.compile(self.__engine.sync_engine)).strip()),
            )

        def get_table_ddl(table: Table) -> Iterable[str]:
            yield compile(CreateTable(table, if_not_exists=True))
            for index in sorted(table.indexes, key=lambda index: str(index.name)):
                yield compile(CreateIndex(index, if_not_exists=True))

        commands: list[str] = []
        for table in Entity.metadata.tables.values():
            commands.extend(get_table_ddl(table))

        return commands

    def session(self) -> AsyncSession:
        return self.__create_session()

    def connect(self) -> AsyncConnection:
        return self.__engine.connect()

    def begin(self) -> AsyncConnection:
        return cast(AsyncConnection, self.__engine.begin())

    async def dispose(self) -> None:
        await self.__engine.dispose()

    def compile(
        self,
        command: str,
        parameters: dict[str, Any] = {},
    ) -> str:
        return str(
            text(dedent(command).strip())
            .bindparams(**parameters)
            .compile(self.__engine.sync_engine, compile_kwargs={"literal_binds": True})
        )

    def sql(
        self,
        command: str,
        parameters: dict[str, Any] = {},
    ) -> TextClause:
        return text(self.compile(command, parameters))

    async def init(self) -> None:
        async with self.begin() as connection:
            for statement in self.ddl:
                await connection.execute(text(statement))

    async def tables(self) -> list[str]:
        return await self.__run_sync(lambda connection: inspect(connection).get_table_names())

    async def __run_sync(self, callback: Callable[[Connection], _T]) -> _T:
        async with self.connect() as connection:
            return await connection.run_sync(callback)
