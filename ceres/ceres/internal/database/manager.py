from __future__ import annotations

import re
from textwrap import dedent
from typing import Any, Iterable, cast

from sqlalchemy import ClauseElement, Table, inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.elements import TextClause

from ...config import (
    DatabaseConfig,
    DatabaseKind,
    PostgresDatabaseConfig,
    SQLiteDatabaseConfig,
)
from ..utilities import run_in_thread, unreachable
from .adapter import DatabaseAdapter
from .entity import Entity, EntityManager


class DatabaseManager:
    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._adapter = self._create_adapter(config)
        self._engine = self._adapter.create_async_engine()
        self._session_maker = async_sessionmaker(
            self._engine,
            AsyncSession,
            expire_on_commit=False,
        )

    @property
    def kind(self) -> DatabaseKind:
        return self._config.kind

    @property
    def entities(self) -> EntityManager:
        return EntityManager(self)

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
            for index in table.indexes:
                yield compile(CreateIndex(index, if_not_exists=True))  # type: ignore

        commands: list[str] = []
        for table in Entity.metadata.tables.values():
            commands.extend(get_table_ddl(table))

        return commands

    @classmethod
    def _create_adapter(cls, config: DatabaseConfig) -> DatabaseAdapter[DatabaseConfig]:
        match config:
            case SQLiteDatabaseConfig():
                from .sqlite import SQLiteDatabaseAdapter

                return SQLiteDatabaseAdapter(config)  # type: ignore
            case PostgresDatabaseConfig():
                from .postgres import PostgresDatabaseAdapter

                return PostgresDatabaseAdapter(config)

        unreachable()

    def session(self) -> AsyncSession:
        return self._session_maker()

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
        engine = self._adapter.create_sync_engine()
        inspector = inspect(engine)

        try:
            return await run_in_thread(lambda: inspector.get_table_names())
        finally:
            engine.dispose()
