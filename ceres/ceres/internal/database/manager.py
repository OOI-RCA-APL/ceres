from __future__ import annotations

from abc import ABC, abstractmethod
from textwrap import dedent
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.sql.elements import TextClause

from ...config import DatabaseConfig, DatabaseKind
from .entity import EntityManager


class DatabaseManager(ABC):
    """
    Database manager that abstracts over SQLAlchemy's async engine type.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        """
        Create a new database manager using the provided configuration.
        """
        self._base_config = config
        self._engine = self._create_engine(config)
        self._session_maker = async_sessionmaker(
            self._engine,
            AsyncSession,
            expire_on_commit=False,
        )

    @staticmethod
    def create(config: DatabaseConfig) -> DatabaseManager:
        from .sqlite import SQLiteDatabaseManager

        match config.kind:
            case DatabaseKind.SQLITE:
                return SQLiteDatabaseManager(config)

        raise NotImplementedError(config.kind)

    @classmethod
    @abstractmethod
    def _create_engine(cls, config: DatabaseConfig) -> AsyncEngine:
        ...

    @abstractmethod
    def _create_ddl_statements(self) -> list[str]:
        ...

    @abstractmethod
    def _create_tables_query(self) -> str:
        ...

    @property
    def kind(self) -> DatabaseKind:
        return self._base_config.kind

    @property
    def ddl(self) -> list[str]:
        return [self.compile(statement) for statement in self._create_ddl_statements()]

    @property
    def engine(self) -> AsyncEngine:
        """
        Access the underlying database async engine.
        """
        return self._engine

    @property
    def entities(self) -> EntityManager:
        return EntityManager(self)

    def session(self) -> AsyncSession:
        return self._session_maker()

    def connect(self) -> AsyncConnection:
        """
        Attempt to create a new database connection.
        """
        return self._engine.connect()

    def begin(self) -> AsyncConnection:
        """
        Attempt to create a new database connection.
        """
        return cast(AsyncConnection, self._engine.begin())

    async def dispose(self) -> None:
        """
        Discard all active database connections.
        """
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
        async with self.connect() as connection:
            return list((await connection.execute(text(self._create_tables_query()))).scalars())
