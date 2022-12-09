import re
from textwrap import dedent
from typing import Any, Callable, Iterable, TypeVar, cast, final

from sqlalchemy import ClauseElement, Connection, Table, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.elements import TextClause

from ...config import (
    DatabaseConfig,
    DatabaseKind,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
)
from .adapter import DatabaseAdapter
from .entity import Entity, EntityManager

_T = TypeVar("_T")


@final
class Database:
    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._adapter = _create_adapter(config)
        self._engine = self._adapter.create_engine()
        self._sessionmaker = async_sessionmaker(
            self._engine,
            AsyncSession,
            expire_on_commit=False,
        )

    @property
    def kind(self) -> DatabaseKind:
        return self._config.kind

    @property
    def adapter(self) -> DatabaseAdapter[DatabaseConfig]:
        return self._adapter

    @property
    def entities(self) -> EntityManager:
        return EntityManager(self)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def ddl(self) -> list[str]:
        def compile(element: ClauseElement) -> str:
            return re.sub(
                r"[\n\r]+\t",
                "\n    ",
                dedent(str(element.compile(self._engine.sync_engine)).strip()),
            )

        def get_table_ddl(table: Table) -> Iterable[str]:
            yield compile(CreateTable(table, if_not_exists=True))
            for index in sorted(table.indexes, key=lambda index: str(index.name)):
                yield compile(CreateIndex(index, if_not_exists=True))  # type: ignore

        commands: list[str] = []
        for table in Entity.metadata.tables.values():
            commands.extend(get_table_ddl(table))

        return commands

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    def connect(self) -> AsyncConnection:
        return self._engine.connect()

    def begin(self) -> AsyncConnection:
        return cast(AsyncConnection, self._engine.begin())

    async def dispose(self) -> None:
        await self._engine.dispose()

    def compile(
        self,
        command: str,
        parameters: dict[str, Any] = {},
    ) -> str:
        return str(
            text(dedent(command).strip())
            .bindparams(**parameters)
            .compile(self._engine.sync_engine, compile_kwargs={"literal_binds": True})
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
        return await self._run_sync(lambda connection: inspect(connection).get_table_names())

    async def _run_sync(self, callback: Callable[[Connection], _T]) -> _T:
        async with self.connect() as connection:
            return await connection.run_sync(callback)


def _create_adapter(config: DatabaseConfig) -> DatabaseAdapter[DatabaseConfig]:
    match config:
        case SQLiteDatabaseConfig():
            from .adapters.sqlite import SQLiteDatabaseAdapter

            return SQLiteDatabaseAdapter(config)
        case PostgresDatabaseConfig():
            from .adapters.postgres import PostgresDatabaseAdapter

            return PostgresDatabaseAdapter(config)
